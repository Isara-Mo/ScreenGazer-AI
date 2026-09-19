"""
主控制窗口
Main Window - control hub for the VN translation tool
"""

from __future__ import annotations

from typing import Optional
import threading
import time

from PIL import Image
from PySide6.QtCore import Qt, QTimer, Slot, QPoint
from PySide6.QtGui import QFont, QIcon, QAction, QColor, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QSystemTrayIcon, QMenu,
    QStatusBar, QGroupBox, QFormLayout, QComboBox,
    QApplication, QMessageBox, QFileDialog,
    QDialog, QDialogButtonBox, QScrollArea,
)

from src.utils.config_manager import ConfigManager
from src.utils.hotkey_manager import HotkeyManager
from src.core.capture import (
    CaptureRegion, capture_region, find_window_by_title,
    list_windows, WindowInfo,
    get_window_info,
)
from src.core.ocr_engine import create_engine
from src.core.llm_client import create_client
from src.core.translator import Translator
from src.core.game_capture import GENSHIN_DIALOGUE_REGION, prepare_genshin_dialogue, detect_genshin_choices
from src.core.dialogue_content import prepare_scene_image, recognize_scene, unpack_scene_text, scene_image_parts
from src.core.glossary import GameGlossary
from src.core.watcher import WatchTiming, normalize_ocr_text
from src.core.timing_summary import format_timing_summary
from src.workers.watch_worker import WatchWorker
from src.workers.translate_worker import TranslateWorker
from src.workers.word_lookup_worker import WordLookupWorker
from src.ui.overlay import RegionSelectorOverlay, SelectedRegion
from src.ui.result_panel import ResultPanel
from src.ui.choice_panel import ReplyChoicesPanel
from src.ui.word_tooltip import WordTooltipWidget
from src.ui.config_dialog import ConfigDialog


MAIN_STYLE = """
QMainWindow {
    background-color: #0f0f1a;
}
QWidget#centralWidget {
    background-color: #0f0f1a;
}
QGroupBox {
    color: #7c3aed;
    font-size: 12px;
    font-weight: bold;
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}
QLabel {
    color: #cbd5e1;
}
QPushButton {
    background-color: #1e1e3a;
    color: #94a3b8;
    border: 1px solid #374151;
    border-radius: 7px;
    padding: 8px 16px;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #2d2d5a;
    color: #e2e8f0;
    border-color: #6366f1;
}
QPushButton:disabled {
    color: #374151;
    border-color: #1e1e3a;
}
QPushButton#startBtn {
    background-color: #1e4a2a;
    color: #4ade80;
    border-color: #166534;
    font-weight: bold;
}
QPushButton#startBtn:hover {
    background-color: #166534;
}
QPushButton#stopBtn {
    background-color: #4a1e1e;
    color: #f87171;
    border-color: #7f1d1d;
    font-weight: bold;
}
QPushButton#stopBtn:hover {
    background-color: #7f1d1d;
}
QPushButton#selectBtn {
    background-color: #1e2a4a;
    color: #60a5fa;
    border-color: #1d4ed8;
}
QStatusBar {
    background-color: #060612;
    color: #94a3b8;
    font-size: 11px;
    border-top: 1px solid #1e1e3a;
}
QComboBox {
    background-color: #1a1a3a;
    color: #e2e8f0;
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #1a1a3a;
    color: #e2e8f0;
    selection-background-color: #4c1d95;
}
"""


class AutoRefreshComboBox(QComboBox):
    """展开列表时自动触发刷新的 ComboBox"""
    def __init__(self, refresh_callback=None, parent=None):
        super().__init__(parent)
        self._refresh_cb = refresh_callback

    def showPopup(self):
        if self._refresh_cb:
            self._refresh_cb()
        super().showPopup()


class MainWindow(QMainWindow):
    """
    主控制窗口
    管理所有核心组件的生命周期和协调通信
    """

    def __init__(self) -> None:
        super().__init__()
        self._cfg = ConfigManager()
        self._hotkey_mgr = HotkeyManager()

        # 状态
        self._capture_region: Optional[CaptureRegion] = None
        self._target_window: Optional[WindowInfo] = None
        self._is_watching: bool = False
        self._closing = False
        self._retired_watch_workers = []
        self._ocr_lock = threading.Lock()

        # 组件（延迟初始化）
        self._ocr_engine = None
        self._ocr_engine_config = None
        self._llm_client = None
        self._translator: Optional[Translator] = None
        self._watch_worker: Optional[WatchWorker] = None
        self._translate_worker: Optional[TranslateWorker] = None
        self._lookup_worker: Optional[WordLookupWorker] = None
        self._lookup_client = None

        # UI 组件
        self._overlay: Optional[RegionSelectorOverlay] = None
        self._result_panel: Optional[ResultPanel] = None
        self._choice_panel: Optional[ReplyChoicesPanel] = None
        self._last_reply_choices = []
        self._last_reply_choice_texts = ()
        self._choice_hide_timer = QTimer(self)
        self._choice_hide_timer.setSingleShot(True)
        self._choice_hide_timer.setInterval(600)
        self._choice_hide_timer.timeout.connect(self._suspend_reply_choices)
        self._word_tooltip: Optional[WordTooltipWidget] = None
        self._translation_stage = ""
        self._translation_stage_started = 0.0
        self._watch_observation = None
        self._watch_submission = None
        self._translation_source = None
        self._deferred_translation = None
        self._translation_timing = None
        self._translation_received_at = None
        self._translation_progress_timer = QTimer(self)
        self._translation_progress_timer.setInterval(1000)
        self._translation_progress_timer.timeout.connect(self._update_translation_progress)
        self._pending_watch_status = None
        self._last_watch_status_at = float("-inf")
        self._watch_status_timer = QTimer(self)
        self._watch_status_timer.setSingleShot(True)
        self._watch_status_timer.timeout.connect(self._flush_watch_status)

        self.setWindowTitle("VN 翻译助手")
        self.setMinimumSize(440, 660)
        self.resize(480, 700)
        self.setStyleSheet(MAIN_STYLE)

        self._setup_ui()
        self._setup_tray()
        self._rebuild_components()
        self._register_hotkey()

        # 加载保存的区域
        saved_region = self._cfg.get("capture", "region")
        if saved_region and len(saved_region) == 4:
            l, t, w, h = saved_region
            self._capture_region = CaptureRegion(l, t, w, h)
            title = self._cfg.get("capture", "window_title", default="")
            relative = self._cfg.get("capture", "relative_region")
            if title and isinstance(relative, list) and len(relative) == 4:
                window = find_window_by_title(title)
                if window:
                    self._target_window = window
                    self._capture_region.hwnd = window.hwnd
                    (self._capture_region.rel_x, self._capture_region.rel_y,
                     self._capture_region.rel_w, self._capture_region.rel_h) = relative
            self._update_region_label()

    # ─── UI 构建 ─────────────────────────────────────────────
    def _setup_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        # ── 标题 ──
        title_row = QHBoxLayout()
        emoji = QLabel("🎮")
        emoji.setStyleSheet("font-size: 24px;")
        title_col = QVBoxLayout()
        app_title = QLabel("VN 翻译助手")
        app_title.setStyleSheet("color: #a78bfa; font-size: 18px; font-weight: bold;")
        subtitle = QLabel("视觉小说英语学习工具")
        subtitle.setStyleSheet("color: #4b5563; font-size: 11px;")
        title_col.addWidget(app_title)
        title_col.addWidget(subtitle)
        title_col.setSpacing(2)
        title_row.addWidget(emoji)
        title_row.addSpacing(8)
        title_row.addLayout(title_col)
        title_row.addStretch()

        export_btn = QPushButton("📤 导出单词")
        export_btn.clicked.connect(self._export_vocab)
        
        config_btn = QPushButton("⚙ 设置")
        config_btn.clicked.connect(self._open_config)
        title_row.addWidget(export_btn)
        title_row.addWidget(config_btn)
        layout.addLayout(title_row)

        # ── 捕获区域 ──
        capture_group = QGroupBox("📸 捕获区域")
        cg_layout = QVBoxLayout(capture_group)
        cg_layout.setSpacing(6)

        self._region_label = QLabel("未选择区域")
        self._region_label.setStyleSheet("color: #6b7280; font-size: 11px;")

        select_btn = QPushButton("🖱 拖拽选择区域")
        select_btn.setObjectName("selectBtn")
        select_btn.clicked.connect(self._start_region_select)

        window_row = QHBoxLayout()
        window_lbl = QLabel("目标窗口:")
        window_lbl.setFixedWidth(70)
        self._window_combo = AutoRefreshComboBox(refresh_callback=self._refresh_windows)
        self._window_combo.setPlaceholderText("（可选）先选窗口再框选")

        window_row.addWidget(window_lbl)
        window_row.addWidget(self._window_combo)

        cg_layout.addWidget(self._region_label)
        cg_layout.addLayout(window_row)
        cg_layout.addWidget(select_btn)
        game_row = QHBoxLayout()
        genshin_btn = QPushButton("原神对白区域")
        genshin_btn.setToolTip("先选择原神窗口，再一键覆盖底部多行对白并启用原神适配")
        genshin_btn.clicked.connect(self._use_genshin_region)
        preview_btn = QPushButton("预览识别范围")
        preview_btn.clicked.connect(self._show_capture_preview)
        game_row.addWidget(genshin_btn)
        game_row.addWidget(preview_btn)
        cg_layout.addLayout(game_row)
        layout.addWidget(capture_group)

        # ── 识别模式 ──
        mode_group = QGroupBox("⚡ 当前配置")
        mg_layout = QFormLayout(mode_group)
        self._mode_label = QLabel()
        self._provider_label = QLabel()
        self._ocr_label = QLabel()
        self._game_label = QLabel()
        mg_layout.addRow("识别模式:", self._mode_label)
        mg_layout.addRow("AI 提供商:", self._provider_label)
        mg_layout.addRow("OCR 引擎:", self._ocr_label)
        mg_layout.addRow("游戏适配:", self._game_label)
        layout.addWidget(mode_group)

        # ── 控制按钮 ──
        ctrl_group = QGroupBox("🎮 控制")
        ctrl_layout = QVBoxLayout(ctrl_group)
        ctrl_layout.setSpacing(6)

        btn_row1 = QHBoxLayout()
        self._start_btn = QPushButton("▶ 开始监视")
        self._start_btn.setObjectName("startBtn")
        self._start_btn.clicked.connect(self._start_watching)

        self._stop_btn = QPushButton("■ 停止监视")
        self._stop_btn.setObjectName("stopBtn")
        self._stop_btn.clicked.connect(self._stop_watching)
        self._stop_btn.setEnabled(False)

        btn_row1.addWidget(self._start_btn)
        btn_row1.addWidget(self._stop_btn)

        btn_row2 = QHBoxLayout()
        translate_now_btn = QPushButton("🔄 立即翻译 (手动)")
        translate_now_btn.clicked.connect(self._manual_translate)

        show_panel_btn = QPushButton("📋 显示全部浮窗")
        show_panel_btn.clicked.connect(self._show_result_panel)

        btn_row2.addWidget(translate_now_btn)
        btn_row2.addWidget(show_panel_btn)

        btn_row3 = QHBoxLayout()
        show_zh_btn = QPushButton("🇨🇳 中文翻译长条框")
        show_zh_btn.clicked.connect(lambda: self._result_panel and self._result_panel.show_chinese_only())

        show_en_btn = QPushButton("🔤 英文原文框")
        show_en_btn.clicked.connect(lambda: self._result_panel and self._result_panel.show_english_only())

        btn_row3.addWidget(show_zh_btn)
        btn_row3.addWidget(show_en_btn)

        hotkey_hint = QLabel(f"快捷键: {self._cfg.get('hotkey', default='ctrl+shift+t').upper()} 立即翻译")
        hotkey_hint.setStyleSheet("color: #4b5563; font-size: 10px; text-align: center;")
        hotkey_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hotkey_hint_label = hotkey_hint

        ctrl_layout.addLayout(btn_row1)
        ctrl_layout.addLayout(btn_row2)
        ctrl_layout.addLayout(btn_row3)
        ctrl_layout.addWidget(hotkey_hint)
        layout.addWidget(ctrl_group)

        self._last_timing_label = QLabel("最近翻译耗时：完成一次翻译后显示各阶段汇总")
        self._last_timing_label.setWordWrap(True)
        self._last_timing_label.setTextFormat(Qt.TextFormat.PlainText)
        self._last_timing_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._last_timing_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self._last_timing_label.setToolTip(
            "从首次检测到新文字的那轮截图开始计时；手动翻译从开始处理该次采集时计时。\n"
            "无法测量游戏实际出字到首次采样之间的延迟。文字确认包含多轮截图、OCR 和等待，不能重复相加。\n"
            "监视中手动翻译不包含按下按钮后等待前一轮 OCR 完成的时间。\n"
            "界面更新指写入浮窗文本，不包含显示器呈现延迟。可选中这些文字复制。"
        )
        layout.addWidget(self._last_timing_label)

        layout.addStretch()

        # ── 状态栏 ──
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("就绪 — 请先选择捕获区域")

        self._refresh_windows()
        self._update_config_labels()

    def _setup_tray(self) -> None:
        """系统托盘图标"""
        self._tray = QSystemTrayIcon(self)
        # 使用内置图标
        self._tray.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_ComputerIcon
        ))
        self._tray.setToolTip("VN 翻译助手")

        tray_menu = QMenu()
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.show)
        show_panel_action = QAction("显示全部翻译面板", self)
        show_panel_action.triggered.connect(self._show_result_panel)
        show_zh_action = QAction("🇨🇳 显示中文字幕长条框", self)
        show_zh_action.triggered.connect(lambda: self._result_panel and self._result_panel.show_chinese_only())
        show_en_action = QAction("🔤 显示英文原文框", self)
        show_en_action.triggered.connect(lambda: self._result_panel and self._result_panel.show_english_only())
        toggle_mode_action = QAction("🧱/📦 切换拆分/合并模式", self)
        toggle_mode_action.triggered.connect(lambda: self._result_panel and self._result_panel.toggle_split_mode())
        translate_action = QAction("立即翻译", self)
        translate_action.triggered.connect(self._manual_translate)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit_app)

        tray_menu.addAction(show_action)
        tray_menu.addAction(show_panel_action)
        tray_menu.addAction(show_zh_action)
        tray_menu.addAction(show_en_action)
        tray_menu.addAction(toggle_mode_action)
        tray_menu.addSeparator()
        tray_menu.addAction(translate_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()

    # ─── 组件管理 ────────────────────────────────────────────
    def _rebuild_components(self) -> None:
        """根据当前配置重新构建核心组件"""
        self._cancel_translation()
        try:
            # OCR 引擎
            ocr_config = (
                self._cfg.get("ocr", "engine", default="tesseract"),
                self._cfg.get("ocr", "tesseract_path", default="tesseract"),
                self._cfg.get("ocr", "tesseract_lang", default="eng"),
                self._cfg.get("ocr", "paddleocr_lang", default="en"),
            )
            # Changing the region, game or monitoring preset does not require
            # loading Paddle's models again. Retired workers share the OCR lock.
            if self._ocr_engine is None or ocr_config != self._ocr_engine_config:
                self._ocr_engine = create_engine(
                    ocr_config[0], tesseract_path=ocr_config[1],
                    tesseract_lang=ocr_config[2], paddleocr_lang=ocr_config[3],
                )
                self._ocr_engine_config = ocr_config

            # 主 LLM 客户端
            active_profile = self._cfg.get_active_model_profile()
            self._llm_client = create_client(active_profile)

            # 查词客户端
            lookup_profile = self._cfg.get_active_lookup_model_profile()
            self._lookup_client = create_client(lookup_profile)

            # 翻译协调器
            game_profile = self._cfg.get("game", "profile", default="generic")
            glossary = None
            if game_profile == "genshin" and self._cfg.get("game", "genshin", "use_glossary", default=True):
                glossary = GameGlossary.load_bundled(
                    self._cfg.get("game", "genshin", "custom_terms", default={})
                )
            self._translator = Translator(
                llm_client=self._llm_client,
                ocr_engine=self._ocr_engine,
                translate_text_prompt=self._cfg.get("prompts", "translate_text", default=""),
                translate_vl_prompt=self._cfg.get("prompts", "translate_vl", default=""),
                ocr_lock=self._ocr_lock,
                game_profile=game_profile,
                glossary=glossary,
            )

            # Workers
            if self._translate_worker:
                self._translate_worker.update_translator(self._translator)
            else:
                self._translate_worker = TranslateWorker(self._translator)
                self._translate_worker.result_ready.connect(self._on_translate_result)
                self._translate_worker.error_occurred.connect(self._on_translate_error)
                self._translate_worker.started_working.connect(self._on_translate_start)
                self._translate_worker.progress_changed.connect(self._on_translate_progress)
                self._translate_worker.queued.connect(self._on_translate_queued)

            if self._lookup_worker:
                self._lookup_worker.update_translator(self._translator)
            else:
                self._lookup_worker = WordLookupWorker(self._translator)
                self._lookup_worker.result_ready.connect(self._on_lookup_result)
                self._lookup_worker.error_occurred.connect(self._on_lookup_error)

            # 结果面板
            if self._result_panel is None:
                self._result_panel = ResultPanel()
                self._result_panel.word_lookup_requested.connect(self._on_word_lookup_request)

            # 词义弹窗
            if self._word_tooltip is None:
                self._word_tooltip = WordTooltipWidget()

            self._update_config_labels()

        except Exception as e:
            self._status_bar.showMessage(f"组件初始化失败: {e}")

    def _rebuild_watch_worker(self) -> None:
        """重新构建监视 Worker"""
        self._retire_watch_worker()
        region = self._game_capture_region()
        engine = self._ocr_engine
        adaptive = self._genshin_adaptive_enabled()

        def capture_fn(require_dialogue: bool = True) -> Optional[Image.Image]:
            if region is None:
                return None
            image = capture_region(region)
            if not adaptive:
                return image
            return self._prepare_genshin_scene(image, require_dialogue=require_dialogue)

        def quick_ocr_fn(img: Image.Image) -> str:
            # A single Paddle instance must not run inference from the manual
            # translation thread and monitor thread at the same time.
            with self._ocr_lock:
                return recognize_scene(img, engine.recognize)

        self._watch_worker = WatchWorker(
            capture_fn=capture_fn,
            manual_capture_fn=lambda: capture_fn(require_dialogue=False),
            empty_capture_status=("等待原神对白（未确认对白，已暂停自动识别）"
                                  if adaptive else "未配置捕获区域"),
            quick_ocr_fn=quick_ocr_fn,
            poll_interval=self._cfg.get("watcher", "poll_interval", default=0.3),
            stability_count=self._cfg.get("watcher", "stability_count", default=2),
            hash_threshold=self._cfg.get("watcher", "hash_threshold", default=5),
            cooldown_seconds=self._cfg.get("watcher", "cooldown_seconds", default=0.5),
            preset=self._cfg.get("watcher", "preset", default="auto"),
        )
        self._watch_worker.translation_needed.connect(self._on_translation_needed)
        self._watch_worker.observation_changed.connect(self._on_watch_observation)
        self._watch_worker.status_changed.connect(self._on_watch_status)
        self._watch_worker.error_occurred.connect(self._on_watch_error)

    def _retire_watch_worker(self) -> None:
        worker, self._watch_worker = self._watch_worker, None
        if worker is None:
            return
        if worker.isRunning():
            self._retired_watch_workers.append(worker)
            worker.finished.connect(lambda w=worker: self._release_watch_worker(w))
            worker.stop()
        else:
            worker.deleteLater()

    def _release_watch_worker(self, worker) -> None:
        if worker in self._retired_watch_workers:
            self._retired_watch_workers.remove(worker)
        worker.deleteLater()

    # ─── 区域选择 ────────────────────────────────────────────
    def _genshin_adaptive_enabled(self) -> bool:
        return (self._cfg.get("game", "profile", default="generic") == "genshin"
                and self._cfg.get("game", "genshin", "adaptive_dialogue", default=True))

    def _game_capture_region(self):
        """Include reply choices inside the bound game window, without changing saved selections."""
        region = self._capture_region
        if (region is None or not self._genshin_adaptive_enabled() or not region.hwnd
                or region.rel_w <= 0 or region.rel_h <= 0):
            return region
        window = get_window_info(region.hwnd)
        if window is None or window.width <= 0 or window.height <= 0:
            return region
        x, y, w, h = GENSHIN_DIALOGUE_REGION
        left, top = max(0.0, min(region.rel_x, x)), max(0.0, min(region.rel_y, y))
        right = min(1.0, max(region.rel_x + region.rel_w, x + w))
        bottom = min(1.0, max(region.rel_y + region.rel_h, y + h))
        return CaptureRegion(
            window.left + int(left * window.width), window.top + int(top * window.height),
            max(1, int((right - left) * window.width)), max(1, int((bottom - top) * window.height)),
            hwnd=region.hwnd, rel_x=left, rel_y=top, rel_w=right - left, rel_h=bottom - top,
        )

    @staticmethod
    def _prepare_genshin_scene(image, *, require_dialogue=True):
        crop = prepare_genshin_dialogue(image)
        choices = detect_genshin_choices(image)
        if choices:
            return prepare_scene_image(crop.image if crop.detected else None,
                                       [choice.image for choice in choices])
        if require_dialogue and not crop.detected:
            return None
        return crop.image

    def _save_capture_region(self) -> None:
        region = self._capture_region
        self._cfg.set("capture", "region", [region.left, region.top, region.width, region.height])
        self._cfg.set("capture", "window_title", self._target_window.title if region.hwnd and self._target_window else "")
        self._cfg.set("capture", "relative_region",
                      [region.rel_x, region.rel_y, region.rel_w, region.rel_h] if region.hwnd else None)
        self._cfg.save()

    def _use_genshin_region(self) -> None:
        title = self._window_combo.currentText()
        window = find_window_by_title(title) if self._window_combo.currentIndex() > 0 else None
        if window is None or window.width <= 0 or window.height <= 0:
            QMessageBox.information(self, "选择游戏窗口", "请先在“目标窗口”中选择正在运行的原神窗口。")
            return
        was_watching = self._is_watching
        if was_watching:
            self._stop_watching()
        elif self._translate_worker:
            self._cancel_translation()
        rx, ry, rw, rh = GENSHIN_DIALOGUE_REGION
        self._target_window = window
        self._capture_region = CaptureRegion(
            window.left + int(window.width * rx), window.top + int(window.height * ry),
            max(1, int(window.width * rw)), max(1, int(window.height * rh)),
            hwnd=window.hwnd, rel_x=rx, rel_y=ry, rel_w=rw, rel_h=rh,
        )
        self._cfg.set("game", "profile", "genshin")
        self._cfg.set("game", "genshin", "adaptive_dialogue", True)
        self._save_capture_region()
        self._rebuild_components()
        self._update_region_label()
        if was_watching:
            self._start_watching()
        self._status_bar.showMessage("已启用原神适配；可用“预览识别范围”确认最长对白是否完整")

    def _show_capture_preview(self) -> None:
        if self._capture_region is None:
            QMessageBox.information(self, "预览识别范围", "请先选择捕获区域或使用“原神对白区域”。")
            return
        try:
            original = capture_region(self._game_capture_region())
            crop = prepare_genshin_dialogue(original) if self._genshin_adaptive_enabled() else None
            choices = detect_genshin_choices(original) if crop else ()
            processed = (prepare_scene_image(crop.image if crop.detected else None,
                                             [choice.image for choice in choices])
                         if choices else crop.image if crop else original)
            detected = bool(crop and (crop.detected or choices))
        except Exception as exc:
            QMessageBox.warning(self, "预览失败", f"截图失败：{exc}")
            return
        from PIL.ImageQt import ImageQt

        dialog = QDialog(self)
        dialog.setWindowTitle("识别范围预览")
        dialog.resize(940, 620)
        dialog.setStyleSheet("QDialog, QWidget#capturePreview { background: #111128; } QLabel { color: #e2e8f0; }")
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("capturePreview")
        content = QVBoxLayout(body)
        if crop:
            confirmation = QLabel(f"已确认对白 / 回复选项（{len(choices)} 条），可进入自动识别" if detected
                                  else "当前画面未通过对白判断，自动翻译正在等待")
            confirmation.setWordWrap(True)
            confirmation.setStyleSheet(
                "color: #4ade80; font-weight: bold;" if detected
                else "color: #fbbf24; font-weight: bold;"
            )
            content.addWidget(confirmation)
        processed_label = ("手动翻译画面（自动监视正在等待对白）"
                           if crop and not detected else "实际识别的对白与选项（分块处理）")
        for label, frame in (("捕获范围（应覆盖人名、称号、最长对白及右侧选项）", original),
                             (processed_label, processed)):
            content.addWidget(QLabel(f"{label} · {frame.width} × {frame.height}"))
            preview = QLabel()
            pixmap = QPixmap.fromImage(ImageQt(frame.convert("RGB")))
            preview.setPixmap(pixmap.scaled(880, 240, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
            content.addWidget(preview)
        detection_note = "通用模式使用完整选区。"
        if crop:
            detection_note = ("已识别金色人名 / 称号，保留下方完整对白。" if crop.detected
                              else "未确认原神对白：自动监视暂停 OCR 和翻译，避免识别血条、等级和按键；"
                                   "对白出现后自动恢复。手动翻译仍可识别完整选区。")
            if choices:
                detection_note = f"已提取 {len(choices)} 条回复选项，按从上到下编号，与角色台词分开识别和显示。"
        note = QLabel(detection_note +
                      "\n绑定原神窗口时会自动补足右侧选项范围；未绑定窗口时请把选项一起框入选区。"
                      "\n预览是打开时的截图。漏识别时可保存捕获原图，保留检测所需的完整像素。")
        note.setWordWrap(True)
        content.addWidget(note)
        content.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        save_button = buttons.addButton("保存捕获原图", QDialogButtonBox.ButtonRole.ActionRole)
        save_button.setToolTip("保存本次未经预览缩放的捕获图，便于核对漏识别原因")

        def save_capture() -> None:
            path, _ = QFileDialog.getSaveFileName(dialog, "保存捕获原图", "capture-original.png", "PNG 图片 (*.png)")
            if path:
                try:
                    original.save(path, format="PNG")
                except Exception as exc:
                    QMessageBox.warning(dialog, "保存失败", str(exc))

        save_button.clicked.connect(save_capture)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _start_region_select(self) -> None:
        """启动区域选择浮层"""
        if self._overlay is None:
            self._overlay = RegionSelectorOverlay()
            self._overlay.region_selected.connect(self._on_region_selected)
            self._overlay.cancelled.connect(lambda: self._status_bar.showMessage("区域选择已取消"))

        # 如果有选定窗口，先将其置于前台
        self._target_window = None
        selected_title = self._window_combo.currentText()
        if selected_title and selected_title != "（可选）先选窗口再框选":
            win = find_window_by_title(selected_title)
            if win:
                self._target_window = win
                from src.core.capture import bring_window_to_front
                bring_window_to_front(win.hwnd)

        self.hide()
        QTimer.singleShot(300, self._overlay.start_selection)

    @Slot(object)
    def _on_region_selected(self, region: SelectedRegion) -> None:
        """区域选择完成"""
        was_watching = self._is_watching
        if was_watching:
            self._stop_watching()
        elif self._translate_worker:
            self._cancel_translation()
        hwnd = None
        rel_x = rel_y = rel_w = rel_h = 0.0

        if self._target_window:
            from src.core.capture import get_window_info
            current_win = get_window_info(self._target_window.hwnd)
            if current_win:
                self._target_window = current_win
                hwnd = current_win.hwnd
                # 动态计算相对比例
                rel_x = (region.left - current_win.left) / current_win.width
                rel_y = (region.top - current_win.top) / current_win.height
                rel_w = region.width / current_win.width
                rel_h = region.height / current_win.height

        self._capture_region = CaptureRegion(
            left=region.left,
            top=region.top,
            width=region.width,
            height=region.height,
            hwnd=hwnd,
            rel_x=rel_x,
            rel_y=rel_y,
            rel_w=rel_w,
            rel_h=rel_h,
        )

        self._save_capture_region()
        self._update_region_label()
        self.show()
        self._status_bar.showMessage(
            f"已选择区域: {region.left},{region.top} 大小 {region.width}×{region.height}"
        )
        if was_watching:
            self._start_watching()

    def _update_region_label(self) -> None:
        if self._capture_region:
            r = self._capture_region
            self._region_label.setText(
                f"📍 区域: ({r.left}, {r.top}) — {r.width} × {r.height} px"
            )
            self._region_label.setStyleSheet("color: #4ade80; font-size: 11px;")
        else:
            self._region_label.setText("⚠ 未选择区域")
            self._region_label.setStyleSheet("color: #f87171; font-size: 11px;")

    # ─── 窗口列表 ────────────────────────────────────────────
    def _refresh_windows(self) -> None:
        current_text = self._window_combo.currentText()
        self._window_combo.blockSignals(True)
        self._window_combo.clear()
        self._window_combo.addItem("（可选）先选窗口再框选")
        wins = list_windows()
        for win in wins:
            self._window_combo.addItem(win.title)

        # 恢复先前选中的项
        idx = self._window_combo.findText(current_text)
        if idx >= 0:
            self._window_combo.setCurrentIndex(idx)
        else:
            self._window_combo.setCurrentIndex(0)
        self._window_combo.blockSignals(False)
        self._status_bar.showMessage(f"已自动扫描刷新窗口列表 (共 {len(wins)} 个活跃窗口)", 2500)

    # ─── 监视控制 ────────────────────────────────────────────
    def _start_watching(self) -> None:
        if self._closing or self._is_watching:
            return
        if self._capture_region is None:
            QMessageBox.warning(self, "提示", "请先选择捕获区域！")
            return

        if not self._cfg.get("watcher", "enabled", default=True):
            QMessageBox.information(self, "提示", "自动监视已在设置中禁用。\n请使用快捷键或手动翻译按钮。")
            return

        if self._ocr_engine is None:
            QMessageBox.warning(
                self, "自动监视需要本地 OCR",
                "请在设置中配置可用的 OCR 引擎。自动监视使用本地文字检测节省 API 调用；"
                "VL 模式仍可通过“立即翻译”手动识图。",
            )
            return

        self._rebuild_watch_worker()
        self._watch_worker.start()
        self._is_watching = True
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status_bar.showMessage("监视中... 正在确认文字，首次 OCR 加载可能稍慢")

    def _stop_watching(self) -> None:
        self._is_watching = False
        self._retire_watch_worker()
        self._cancel_translation()
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_bar.showMessage("已停止监视")

    # ─── 翻译触发 ────────────────────────────────────────────
    def _cancel_translation(self) -> None:
        self._translation_progress_timer.stop()
        self._clear_watch_status()
        self._last_watch_status_at = float("-inf")
        self._translation_stage = ""
        self._watch_observation = None
        self._watch_submission = None
        self._translation_source = None
        self._deferred_translation = None
        self._translation_timing = None
        self._translation_received_at = None
        self._choice_hide_timer.stop()
        self._last_reply_choices = []
        self._last_reply_choice_texts = ()
        if self._choice_panel:
            self._choice_panel.clear_choices()
        if self._result_panel:
            self._result_panel.clear_progress()
        if self._translate_worker:
            self._translate_worker.cancel_pending()

    @Slot()
    def _manual_translate(self) -> None:
        """手动立即翻译"""
        started_at = time.monotonic()
        if self._closing:
            return
        if self._capture_region is None:
            QMessageBox.warning(self, "提示", "请先选择捕获区域！")
            return

        if (self._is_watching and self._watch_worker
                and self._cfg.get("recognition_mode", default="ocr") != "vl"):
            self._watch_worker.force_trigger()
            return

        # 将目标窗口带到前台，以防被遮挡导致截取到桌面
        if self._target_window:
            from src.core.capture import bring_window_to_front
            bring_window_to_front(self._target_window.hwnd)
            time.sleep(0.1)  # 等待窗口重绘

        try:
            capture_started = time.monotonic()
            img = capture_region(self._game_capture_region())
            if self._genshin_adaptive_enabled():
                img = self._prepare_genshin_scene(img, require_dialogue=False)
            captured_at = time.monotonic()
            self._trigger_translation(img, monitor_timing=WatchTiming(
                started_at=started_at, submitted_at=captured_at,
                capture_seconds=captured_at - capture_started,
                ocr_seconds=0.0, ocr_samples=0, stable_seconds=0.0,
            ))
        except Exception as e:
            self._status_bar.showMessage(f"截图失败: {e}")

    def _hotkey_callback(self) -> None:
        """快捷键回调（在 keyboard 线程中调用，通过 Qt 信号转发）"""
        from PySide6.QtCore import QMetaObject
        QMetaObject.invokeMethod(self, "_manual_translate", Qt.ConnectionType.QueuedConnection)

    @Slot(object, str)
    def _on_translation_needed(self, img: Image.Image, ocr_text: str) -> None:
        """WatchWorker 发出翻译信号"""
        if self._is_watching and self.sender() is self._watch_worker:
            submission, self._watch_submission = self._watch_submission, None
            # The submitted observation is emitted immediately before this
            # signal by the same worker, including explicit manual requests.
            manual = (submission is not None and submission.manual
                      and submission.text == normalize_ocr_text(ocr_text))
            self._trigger_translation(
                img, ocr_text, automatic=not manual,
                monitor_timing=getattr(submission, "timing", None),
            )

    def _trigger_translation(self, img: Image.Image, ocr_text: str | None = None,
                             *, automatic: bool = False,
                             monitor_timing: WatchTiming | None = None) -> None:
        if self._translate_worker is None:
            return
        self._translation_source = normalize_ocr_text(ocr_text) if automatic else None
        self._deferred_translation = None
        mode = self._cfg.get("recognition_mode", default="ocr")
        self._translation_received_at = None
        scene = unpack_scene_text(ocr_text or "")
        parts = scene_image_parts(img)
        self._translation_timing = {
            "monitor": monitor_timing,
            "started_at": monitor_timing.started_at if monitor_timing else time.monotonic(),
            "manual": not automatic,
            "ocr_mode": "unused" if mode == "vl" else ("reused" if ocr_text is not None else "request"),
            "only_choices": bool((scene and not scene.dialogue) or (parts and parts.dialogue is None)),
        }
        self._translate_worker.translate(img, mode, ocr_text=ocr_text)

    @Slot(object)
    def _on_watch_observation(self, observation) -> None:
        if not self._is_watching or self.sender() is not self._watch_worker:
            return
        if observation.kind == "submitted":
            self._watch_submission = observation
            if observation.manual:
                return
        self._watch_observation = observation
        self._observe_reply_choices(observation)
        if self._deferred_translation is not None:
            source, result, error = self._deferred_translation
            if self._matches_observed_dialogue(source):
                self._deferred_translation = None
                if error is not None:
                    self._on_translate_error(error)
                else:
                    self._on_translate_result(result)
                return
        self._update_watch_notice()

    def _suspend_reply_choices(self):
        if self._choice_panel:
            self._choice_panel.suspend()

    def _observe_reply_choices(self, observation):
        scene = unpack_scene_text(observation.text)
        texts = tuple(normalize_ocr_text(text) for text in scene.choices) if scene else ()
        if texts:
            self._choice_hide_timer.stop()
            if texts == self._last_reply_choice_texts and self._choice_panel:
                self._choice_panel.show_choices(self._last_reply_choices)
            elif observation.kind == "submitted":
                self._suspend_reply_choices()
        elif observation.kind == "submitted":
            self._choice_hide_timer.stop()
            self._suspend_reply_choices()
        elif self._choice_panel and not self._choice_hide_timer.isActive():
            # A one-frame detection miss should not blink the choice panel.
            self._choice_hide_timer.start()

    def _matches_observed_dialogue(self, source: str | None) -> bool:
        observation = self._watch_observation
        return (source is None or observation is None or
                (observation.kind not in ("unavailable", "empty") and observation.text == source))

    def _update_watch_notice(self) -> None:
        # Per-sample OCR changes belong in the main window. Floating subtitles
        # stay still until a translation actually starts, finishes or fails.
        if self._watch_observation is None or self._translation_progress_timer.isActive():
            return
        observation = self._watch_observation
        if observation.kind == "unavailable":
            message = "未确认对白 · 保留上次结果"
        elif observation.kind == "empty":
            message = "未识别到文字 · 保留上次结果"
        elif observation.kind == "candidate":
            message = "正在确认新句 · 保留上次结果"
        elif self._deferred_translation is not None:
            message = "等待当前对白 · 保留上次结果"
        else:
            message = ""
        if message:
            self._queue_watch_status(message)

    # ─── Slots: 翻译结果 ─────────────────────────────────────
    @Slot()
    def _on_translate_start(self) -> None:
        only_choices = self._translation_timing and self._translation_timing.get("only_choices")
        if self._result_panel and not only_choices:
            self._result_panel.show_loading()
        self._on_translate_progress("准备翻译")

    @Slot(str)
    def _on_translate_progress(self, stage: str) -> None:
        if self._closing:
            return
        self._clear_watch_status()
        self._translation_stage = stage
        self._translation_stage_started = time.perf_counter()
        self._translation_progress_timer.start()
        self._update_translation_progress()

    @Slot()
    def _on_translate_queued(self) -> None:
        self._on_translate_progress("已保留最新对白，等待上一条请求结束")

    def _update_translation_progress(self) -> None:
        if (self._closing or not self._translation_stage or not self._translate_worker
                or not self._translate_worker._busy):
            self._translation_progress_timer.stop()
            return
        elapsed = time.perf_counter() - self._translation_stage_started
        message = f"{self._translation_stage} · {elapsed:.1f}s"
        if self._is_watching and not self._matches_observed_dialogue(self._translation_source):
            observation = self._watch_observation
            waiting = "新句待确认" if observation and observation.text else "等待对白"
            message = f"{waiting} · 上条请求处理中 · {elapsed:.1f}s"
        self._status_bar.showMessage(message)

    @Slot(object)
    def _on_translate_result(self, result) -> None:
        self._translation_progress_timer.stop()
        self._clear_watch_status()
        received_at = time.monotonic()
        if self._translation_received_at is None:
            self._translation_received_at = received_at
        if self._is_watching and not self._matches_observed_dialogue(self._translation_source):
            # Keep the result for a transient OCR error (A -> B -> A), without
            # presenting A as the answer to B. Cancelling A would deadlock the
            # watcher's text deduplication if the observation returned to A.
            self._deferred_translation = (self._translation_source, result, None)
            if self._result_panel:
                self._result_panel.clear_progress()
            self._update_watch_notice()
            return
        warning = getattr(result, "warning", "")
        hits = getattr(result, "glossary_hits", [])
        error = getattr(result, "error", "")
        status = (f"翻译失败，保留识别原文：{error}" if error else "翻译完成 ✓")
        status += f" · 匹配 {len(hits)} 条原神术语" if hits else ""
        self._status_bar.showMessage(f"{status} · {warning}" if warning else status)
        display_started = time.monotonic()
        choices = getattr(result, "choices", [])
        has_dialogue = bool(result.corrected or result.translation)
        if self._result_panel and (has_dialogue or not choices):
            self._result_panel.show_result(
                corrected=result.corrected,
                translation=result.translation,
                original_ocr=result.original_ocr,
            )
        elif self._result_panel:
            self._result_panel.clear_progress()
        if self._result_panel and has_dialogue and not self._result_panel.isVisible():
            self._result_panel.show()
        self._last_reply_choices = choices
        self._last_reply_choice_texts = tuple(
            normalize_ocr_text(choice.original_ocr or choice.corrected) for choice in choices
        )
        if choices:
            if self._choice_panel is None:
                self._choice_panel = ReplyChoicesPanel()
            self._choice_hide_timer.stop()
            self._choice_panel.show_choices(choices)
        elif self._choice_panel:
            self._choice_panel.clear_choices()
        displayed_at = time.monotonic()
        timings = dict(getattr(result, "timings", {}))
        trace = self._translation_timing
        if timings or trace:
            if trace:
                timings["ocr_mode"] = trace["ocr_mode"]
            self._last_timing_label.setText(format_timing_summary(
                timings,
                monitor=trace["monitor"] if trace else None,
                total_seconds=max(0.0, displayed_at - trace["started_at"]) if trace else None,
                display_seconds=max(0.0, displayed_at - display_started),
                held_seconds=max(0.0, received_at - self._translation_received_at),
                manual=trace["manual"] if trace else False,
            ))
        self._last_watch_status_at = displayed_at
        if self._translation_source is not None:
            self._update_watch_notice()

    @Slot(str)
    def _on_translate_error(self, error: str) -> None:
        self._translation_progress_timer.stop()
        self._clear_watch_status()
        if self._is_watching and not self._matches_observed_dialogue(self._translation_source):
            self._deferred_translation = (self._translation_source, None, error)
            if self._result_panel:
                self._result_panel.clear_progress()
            self._update_watch_notice()
            return
        self._status_bar.showMessage(f"翻译失败: {error}")
        self._last_watch_status_at = time.monotonic()
        if self._result_panel:
            self._result_panel.show_error(error)

    @Slot(str)
    def _on_watch_status(self, status: str) -> None:
        if self._is_watching and self.sender() is self._watch_worker and not (
            self._translate_worker and self._translate_worker._busy
        ):
            self._queue_watch_status(status)

    def _clear_watch_status(self) -> None:
        self._watch_status_timer.stop()
        self._pending_watch_status = None

    def _queue_watch_status(self, message: str) -> None:
        """Coalesce routine diagnostics without delaying capture or translation."""
        if self._closing or not self._is_watching or (
            self._translate_worker and self._translate_worker._busy
        ):
            return
        self._pending_watch_status = (self._watch_worker, message)
        remaining = 2.0 - (time.monotonic() - self._last_watch_status_at)
        if remaining <= 0:
            self._flush_watch_status()
        elif not self._watch_status_timer.isActive():
            self._watch_status_timer.start(max(1, int(remaining * 1000) + 1))

    @Slot()
    def _flush_watch_status(self) -> None:
        self._watch_status_timer.stop()
        pending, self._pending_watch_status = self._pending_watch_status, None
        if (pending is None or self._closing or not self._is_watching
                or pending[0] is not self._watch_worker
                or (self._translate_worker and self._translate_worker._busy)):
            return
        self._last_watch_status_at = time.monotonic()
        if pending[1] != self._status_bar.currentMessage():
            self._status_bar.showMessage(pending[1])

    @Slot(str)
    def _on_watch_error(self, error: str) -> None:
        if self._is_watching and self.sender() is self._watch_worker:
            self._clear_watch_status()
            self._last_watch_status_at = time.monotonic()
            self._status_bar.showMessage(f"监视错误: {error}")

    # ─── Slots: 查词 ─────────────────────────────────────────
    @Slot(str, str)
    def _on_word_lookup_request(self, selected_text: str, context: str) -> None:
        """结果面板请求查词"""
        if self._word_tooltip is None or self._lookup_worker is None:
            return

        # 立即显示加载状态（使用 QCursor.pos() 获取全局鼠标位置）
        from PySide6.QtGui import QCursor
        cursor_pos = QCursor.pos()
        self._word_tooltip.show_loading(
            selected_text,
            pos=QPoint(cursor_pos.x() + 15, cursor_pos.y() + 15)
        )

        # 启动查词 Worker
        self._lookup_worker.lookup(
            selected_text=selected_text,
            context=context,
            lookup_client=self._lookup_client,
            prompt_template=self._cfg.get("prompts", "word_lookup", default=""),
        )

    @Slot(dict)
    def _on_lookup_result(self, data: dict) -> None:
        if self._word_tooltip:
            self._word_tooltip.show_result(data)

    @Slot(str)
    def _on_lookup_error(self, error: str) -> None:
        if self._word_tooltip:
            self._word_tooltip.show_error(error)

    # ─── 单词本管理 ──────────────────────────────────────────
    def _export_vocab(self) -> None:
        from src.utils.vocabulary import get_all_words
        words = get_all_words()
        if not words:
            QMessageBox.information(self, "导出单词本", "当前收藏夹为空！没有可以导出的单词。")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出单词本", "vocab.txt", "文本文件 (*.txt)"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    for w in words:
                        f.write(f"{w}\n")
                QMessageBox.information(self, "导出成功", f"成功导出 {len(words)} 个单词！\n收藏夹中的单词已保留。")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"导出时发生错误:\n{e}")

    # ─── 配置与 UI 更新 ──────────────────────────────────────
    def _open_config(self) -> None:
        dialog = ConfigDialog(self)
        dialog.config_changed.connect(self._on_config_changed)
        dialog.exec()

    @Slot()
    def _on_config_changed(self) -> None:
        was_watching = self._is_watching
        if was_watching:
            self._stop_watching()

        self._rebuild_components()
        self._register_hotkey()
        self._update_config_labels()

        if was_watching:
            self._start_watching()

    def _update_config_labels(self) -> None:
        mode = self._cfg.get("recognition_mode", default="ocr")
        active_profile = self._cfg.get_active_model_profile()
        ocr_engine = self._cfg.get("ocr", "engine", default="tesseract")

        mode_text = "OCR + 文本LLM" if mode == "ocr" else "VL 大模型直接识别"
        self._mode_label.setText(mode_text)

        if active_profile:
            p_name = active_profile.get("name", "未配置")
            m_name = active_profile.get("text_model", "")
            display_str = f"{p_name} ({m_name})" if m_name else p_name
        else:
            display_str = "未配置模型"

        self._provider_label.setText(display_str)
        self._ocr_label.setText(ocr_engine.capitalize())
        game_label = "通用"
        if self._cfg.get("game", "profile", default="generic") == "genshin":
            features = ["原神"]
            if self._genshin_adaptive_enabled():
                features.append("对白与选项")
            if self._cfg.get("game", "genshin", "use_glossary", default=True):
                features.append("本地术语")
            game_label = " · ".join(features)
        self._game_label.setText(game_label)
        self._hotkey_hint_label.setText(
            f"快捷键: {self._cfg.get('hotkey', default='ctrl+shift+t').upper()} 立即翻译"
        )

    def _register_hotkey(self) -> None:
        """延迟注册快捷键，等待 Qt 事件循环启动后再安装 Windows hook"""
        self._hotkey_mgr.unregister_all()
        hotkey = self._cfg.get("hotkey", default="ctrl+shift+t")
        # 用 singleShot 延迟 1.5s，确保在事件循环启动后注册
        self._hotkey_mgr.register_delayed(hotkey, self._hotkey_callback, delay_ms=1500)

    def _show_result_panel(self) -> None:
        if self._result_panel:
            self._result_panel.show()
            self._result_panel.raise_()
        if self._choice_panel:
            self._choice_panel.reveal()

    # ─── 托盘 ────────────────────────────────────────────────
    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.raise_()

    # ─── 关闭事件 ────────────────────────────────────────────
    def closeEvent(self, event) -> None:
        """Wait asynchronously for in-flight work before destroying QThreads."""
        event.ignore()
        self.quit_app()

    def quit_app(self) -> None:
        """完全退出程序并释放资源"""
        if self._closing:
            return
        self._closing = True
        self._stop_watching()
        for worker in (self._translate_worker, self._lookup_worker):
            if worker:
                worker.cancel_pending()
        self._hotkey_mgr.unregister_all()
        if hasattr(self, "_tray") and self._tray:
            self._tray.hide()
        if self._result_panel:
            self._result_panel.close()
        if self._choice_panel:
            self._choice_panel.close()
        if self._word_tooltip:
            self._word_tooltip.close()
        self.setEnabled(False)
        self._status_bar.showMessage("正在退出，等待后台任务结束...")
        self._finish_quit()

    def _finish_quit(self) -> None:
        workers = [self._translate_worker, self._lookup_worker, *self._retired_watch_workers]
        if any(worker is not None and worker.isRunning() for worker in workers):
            QTimer.singleShot(100, self._finish_quit)
            return
        QApplication.quit()
