"""
主控制窗口
Main Window - control hub for the VN translation tool
"""

from __future__ import annotations

from typing import Optional

from PIL import Image
from PySide6.QtCore import Qt, QTimer, Slot, QPoint
from PySide6.QtGui import QFont, QIcon, QAction, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QSystemTrayIcon, QMenu,
    QStatusBar, QGroupBox, QFormLayout, QComboBox,
    QApplication, QMessageBox, QFileDialog,
)

from src.utils.config_manager import ConfigManager
from src.utils.hotkey_manager import HotkeyManager
from src.core.capture import (
    CaptureRegion, capture_region, find_window_by_title,
    list_windows, WindowInfo,
)
from src.core.ocr_engine import create_engine, TesseractEngine
from src.core.llm_client import create_client
from src.core.translator import Translator
from src.core.watcher import ChangeWatcher
from src.workers.watch_worker import WatchWorker
from src.workers.translate_worker import TranslateWorker
from src.workers.word_lookup_worker import WordLookupWorker
from src.ui.overlay import RegionSelectorOverlay, SelectedRegion
from src.ui.result_panel import ResultPanel
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
    color: #4b5563;
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

        # 组件（延迟初始化）
        self._ocr_engine = None
        self._llm_client = None
        self._translator: Optional[Translator] = None
        self._watch_worker: Optional[WatchWorker] = None
        self._translate_worker: Optional[TranslateWorker] = None
        self._lookup_worker: Optional[WordLookupWorker] = None
        self._lookup_client = None

        # UI 组件
        self._overlay: Optional[RegionSelectorOverlay] = None
        self._result_panel: Optional[ResultPanel] = None
        self._word_tooltip: Optional[WordTooltipWidget] = None

        self.setWindowTitle("VN 翻译助手")
        self.setMinimumSize(400, 520)
        self.resize(440, 560)
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
        layout.addWidget(capture_group)

        # ── 识别模式 ──
        mode_group = QGroupBox("⚡ 当前配置")
        mg_layout = QFormLayout(mode_group)
        self._mode_label = QLabel()
        self._provider_label = QLabel()
        self._ocr_label = QLabel()
        mg_layout.addRow("识别模式:", self._mode_label)
        mg_layout.addRow("AI 提供商:", self._provider_label)
        mg_layout.addRow("OCR 引擎:", self._ocr_label)
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
        quit_action.triggered.connect(QApplication.quit)

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
        try:
            # OCR 引擎
            self._ocr_engine = create_engine(
                self._cfg.get("ocr", "engine", default="tesseract"),
                tesseract_path=self._cfg.get("ocr", "tesseract_path", default="tesseract"),
                tesseract_lang=self._cfg.get("ocr", "tesseract_lang", default="eng"),
                paddleocr_lang=self._cfg.get("ocr", "paddleocr_lang", default="en"),
            )

            # 主 LLM 客户端
            active_profile = self._cfg.get_active_model_profile()
            self._llm_client = create_client(active_profile)

            # 查词客户端
            lookup_profile = self._cfg.get_active_lookup_model_profile()
            self._lookup_client = create_client(lookup_profile)

            # 翻译协调器
            self._translator = Translator(
                llm_client=self._llm_client,
                ocr_engine=self._ocr_engine,
                translate_text_prompt=self._cfg.get("prompts", "translate_text", default=""),
                translate_vl_prompt=self._cfg.get("prompts", "translate_vl", default=""),
            )

            # Workers
            if self._translate_worker:
                self._translate_worker.update_translator(self._translator)
            else:
                self._translate_worker = TranslateWorker(self._translator)
                self._translate_worker.result_ready.connect(self._on_translate_result)
                self._translate_worker.error_occurred.connect(self._on_translate_error)
                self._translate_worker.started_working.connect(self._on_translate_start)

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
        if self._watch_worker and self._watch_worker.isRunning():
            self._watch_worker.stop()
            self._watch_worker.wait(3000)

        def capture_fn() -> Optional[Image.Image]:
            if self._capture_region is None:
                return None
            try:
                return capture_region(self._capture_region)
            except Exception:
                return None

        def quick_ocr_fn(img: Image.Image) -> str:
            try:
                if isinstance(self._ocr_engine, TesseractEngine):
                    return self._ocr_engine.quick_recognize(img)
                return self._ocr_engine.recognize(img)
            except Exception:
                return ""

        self._watch_worker = WatchWorker(
            capture_fn=capture_fn,
            quick_ocr_fn=quick_ocr_fn,
            poll_interval=self._cfg.get("watcher", "poll_interval", default=0.3),
            stability_count=self._cfg.get("watcher", "stability_count", default=2),
            hash_threshold=self._cfg.get("watcher", "hash_threshold", default=5),
            cooldown_seconds=self._cfg.get("watcher", "cooldown_seconds", default=0.5),
        )
        self._watch_worker.translation_needed.connect(self._on_translation_needed)
        self._watch_worker.status_changed.connect(self._on_watch_status)
        self._watch_worker.error_occurred.connect(self._on_watch_error)

    # ─── 区域选择 ────────────────────────────────────────────
    def _start_region_select(self) -> None:
        """启动区域选择浮层"""
        if self._overlay is None:
            self._overlay = RegionSelectorOverlay()
            self._overlay.region_selected.connect(self._on_region_selected)
            self._overlay.cancelled.connect(lambda: self._status_bar.showMessage("区域选择已取消"))

        # 如果有选定窗口，先将其置于前台
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

        # 简单保存绝对坐标供下次恢复用（实际运行时会用 hwnd 动态计算）
        self._cfg.set("capture", "region", list(region.to_tuple()))
        self._cfg.save()
        self._update_region_label()
        self.show()
        self._status_bar.showMessage(
            f"已选择区域: {region.left},{region.top} 大小 {region.width}×{region.height}"
        )

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
        if self._capture_region is None:
            QMessageBox.warning(self, "提示", "请先选择捕获区域！")
            return

        if not self._cfg.get("watcher", "enabled", default=True):
            QMessageBox.information(self, "提示", "自动监视已在设置中禁用。\n请使用快捷键或手动翻译按钮。")
            return

        self._rebuild_watch_worker()
        self._watch_worker.start()
        self._is_watching = True
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status_bar.showMessage("监视中... 等待画面变化")

    def _stop_watching(self) -> None:
        if self._watch_worker and self._watch_worker.isRunning():
            self._watch_worker.stop()
            self._watch_worker.wait(3000)
        self._is_watching = False
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_bar.showMessage("已停止监视")

    # ─── 翻译触发 ────────────────────────────────────────────
    def _manual_translate(self) -> None:
        """手动立即翻译"""
        if self._capture_region is None:
            QMessageBox.warning(self, "提示", "请先选择捕获区域！")
            return

        # 将目标窗口带到前台，以防被遮挡导致截取到桌面
        if self._target_window:
            from src.core.capture import bring_window_to_front
            bring_window_to_front(self._target_window.hwnd)
            import time
            time.sleep(0.1)  # 等待窗口重绘

        try:
            img = capture_region(self._capture_region)
            self._trigger_translation(img)
        except Exception as e:
            self._status_bar.showMessage(f"截图失败: {e}")

    def _hotkey_callback(self) -> None:
        """快捷键回调（在 keyboard 线程中调用，通过 Qt 信号转发）"""
        if self._is_watching and self._watch_worker:
            self._watch_worker.force_trigger()
        else:
            # 用 invokeMethod 安全地调用 Qt 主线程方法
            from PySide6.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(self, "_manual_translate", Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _on_translation_needed(self, img: Image.Image) -> None:
        """WatchWorker 发出翻译信号"""
        self._trigger_translation(img)

    def _trigger_translation(self, img: Image.Image) -> None:
        if self._translate_worker is None:
            return
        mode = self._cfg.get("recognition_mode", default="ocr")
        self._translate_worker.translate(img, mode)

    # ─── Slots: 翻译结果 ─────────────────────────────────────
    @Slot()
    def _on_translate_start(self) -> None:
        self._status_bar.showMessage("翻译中...")
        if self._result_panel:
            self._result_panel.show_loading()

    @Slot(object)
    def _on_translate_result(self, result) -> None:
        self._status_bar.showMessage("翻译完成 ✓")
        if self._result_panel:
            self._result_panel.show_result(
                corrected=result.corrected,
                translation=result.translation,
                original_ocr=result.original_ocr,
            )
        if not self._result_panel.isVisible():
            self._result_panel.show()

    @Slot(str)
    def _on_translate_error(self, error: str) -> None:
        self._status_bar.showMessage(f"翻译失败: {error}")
        if self._result_panel:
            self._result_panel.show_error(error)

    @Slot(str)
    def _on_watch_status(self, status: str) -> None:
        self._status_bar.showMessage(status)

    @Slot(str)
    def _on_watch_error(self, error: str) -> None:
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
        self._word_tooltip.show_result(
            {"word": selected_text, "meaning": "查询中...", "part_of_speech": "", "note": ""},
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
            from PySide6.QtGui import QCursor
            cursor_pos = QCursor.pos()
            self._word_tooltip.show_result(
                data,
                pos=QPoint(cursor_pos.x() + 15, cursor_pos.y() + 15)
            )

    @Slot(str)
    def _on_lookup_error(self, error: str) -> None:
        if self._word_tooltip:
            self._word_tooltip.show_error(error)

    # ─── 单词本管理 ──────────────────────────────────────────
    def _export_vocab(self) -> None:
        from src.utils.vocabulary import get_all_words, clear_vocab
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
                clear_vocab()
                QMessageBox.information(self, "导出成功", f"成功导出 {len(words)} 个单词！\n已清空当前收藏夹。")
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

    # ─── 托盘 ────────────────────────────────────────────────
    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.raise_()

    # ─── 关闭事件 ────────────────────────────────────────────
    def closeEvent(self, event) -> None:
        """关闭主窗口时彻底退出程序"""
        self.quit_app()
        event.accept()

    def quit_app(self) -> None:
        """完全退出程序并释放资源"""
        self._stop_watching()
        self._hotkey_mgr.unregister_all()
        if hasattr(self, "_tray") and self._tray:
            self._tray.hide()
        if self._result_panel:
            self._result_panel.close()
        if self._word_tooltip:
            self._word_tooltip.close()
        QApplication.quit()
