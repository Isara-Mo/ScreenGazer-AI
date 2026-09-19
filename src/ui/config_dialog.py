"""
配置对话框
Config Dialog - tabbed settings for models, OCR, prompts, and hotkeys
"""

from __future__ import annotations

import time
import unicodedata
from PySide6.QtCore import Qt, Signal, QThread, Slot
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QLabel, QLineEdit, QTextEdit, QPushButton,
    QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QFormLayout, QFileDialog, QFrame,
    QScrollArea, QMessageBox, QSlider, QListWidget,
    QListWidgetItem,
)

from src.utils.config_manager import ConfigManager
from src.core.glossary import GameGlossary, canonical_term_name


DIALOG_STYLE = """
QDialog {
    background-color: #0f0f1a;
    color: #e2e8f0;
}
QTabWidget::pane {
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    background-color: #111128;
}
QTabBar::tab {
    background-color: #1a1a3a;
    color: #6b7280;
    padding: 8px 18px;
    border-radius: 6px 6px 0 0;
    margin-right: 2px;
    font-size: 12px;
}
QTabBar::tab:selected {
    background-color: #111128;
    color: #a78bfa;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background-color: #1e1e4a;
    color: #c4b5fd;
}
QGroupBox {
    color: #7c3aed;
    font-size: 12px;
    font-weight: bold;
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}
QLabel {
    color: #cbd5e1;
    font-size: 12px;
}
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #1a1a3a;
    color: #e2e8f0;
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: #7c3aed;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #1a1a3a;
    color: #e2e8f0;
    selection-background-color: #4c1d95;
}
QListWidget {
    background-color: #141428;
    color: #e2e8f0;
    border: 1px solid #1e1e3a;
    border-radius: 6px;
    padding: 4px;
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 4px;
    margin-bottom: 2px;
}
QListWidget::item:selected {
    background-color: #4c1d95;
    color: #ffffff;
    font-weight: bold;
}
QListWidget::item:hover:!selected {
    background-color: #1e1e3a;
}
QPushButton {
    background-color: #1e1e3a;
    color: #94a3b8;
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #2d2d5a;
    color: #e2e8f0;
    border-color: #6366f1;
}
QPushButton#saveBtn {
    background-color: #5b21b6;
    color: #ede9fe;
    border-color: #7c3aed;
    font-weight: bold;
    padding: 8px 24px;
}
QPushButton#saveBtn:hover {
    background-color: #6d28d9;
}
QCheckBox {
    color: #cbd5e1;
    font-size: 12px;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #374151;
    border-radius: 4px;
    background: #1a1a3a;
}
QCheckBox::indicator:checked {
    background: #7c3aed;
    border-color: #7c3aed;
}
"""


def make_divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("border: none; border-top: 1px solid #1e1e3a; margin: 4px 0;")
    return line


def parse_custom_terms(text: str) -> dict[str, str]:
    """Validate editable terminology before making any changes to configuration."""
    terms: dict[str, str] = {}
    seen: dict[str, int] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.count("=") != 1:
            raise ValueError(f"第 {line_number} 行格式不正确：每行应为 English = 中文，且只能有一个 =。")
        english, chinese = (part.strip() for part in line.split("=", 1))
        if not english or not chinese:
            raise ValueError(f"第 {line_number} 行有空值：英文名称和中文译名都不能为空。")
        try:
            GameGlossary(overrides={english: chinese})
        except ValueError as exc:
            raise ValueError(f"第 {line_number} 行：{exc}") from exc
        normalized = canonical_term_name(unicodedata.normalize("NFKC", english)).casefold()
        if normalized in seen:
            raise ValueError(
                f"第 {line_number} 行的英文名称“{english}”与第 {seen[normalized]} 行重复，"
                "请合并为一条（不区分大小写、全半角及多余空白）。"
            )
        seen[normalized] = line_number
        terms[english] = chinese
    return terms


class TestConnectionWorker(QThread):
    """在后台线程中测试模型连接，避免阻塞 GUI 主线程"""
    test_finished = Signal(bool, str, str)  # (success, response_or_error, profile_name)

    def __init__(self, profile: dict, parent=None) -> None:
        super().__init__(parent)
        self._profile = dict(profile)

    def run(self) -> None:
        profile_name = self._profile.get("name", "未命名模型")
        try:
            from src.core.llm_client import create_client
            # 为测试连接设置较短超时（如 15s），避免长时间挂起
            client = create_client(self._profile)
            response = client.chat([{"role": "user", "content": "Say 'OK' in one word."}])
            self.test_finished.emit(True, response[:100], profile_name)
        except Exception as e:
            self.test_finished.emit(False, str(e), profile_name)


class ConfigDialog(QDialog):
    """配置对话框，应用更改时发出信号通知主窗口重新初始化"""

    config_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("⚙ 翻译助手设置")
        self.setMinimumSize(720, 580)
        self.resize(760, 640)
        self.setStyleSheet(DIALOG_STYLE)
        self._cfg = ConfigManager()

        self._model_profiles: list[dict] = []
        self._active_model_id: str = "dashscope_default"
        self._active_lookup_model_id: str = "same"
        self._current_profile_index: int = -1
        self._test_worker: TestConnectionWorker | None = None

        self._setup_ui()
        self._load_values()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 12)
        main_layout.setSpacing(10)

        # 标题
        title = QLabel("⚙ 设置")
        title.setStyleSheet("color: #a78bfa; font-size: 18px; font-weight: bold;")
        main_layout.addWidget(title)

        # 选项卡
        self._tabs = QTabWidget()
        main_layout.addWidget(self._tabs)

        self._tabs.addTab(self._build_model_tab(), "🤖 模型配置")
        self._tabs.addTab(self._build_ocr_tab(), "🔍 OCR")
        self._tabs.addTab(self._build_mode_tab(), "⚡ 识别模式")
        self._game_tab = self._build_game_tab()
        self._tabs.addTab(self._game_tab, "🎮 游戏适配")
        self._tabs.addTab(self._build_prompt_tab(), "📝 提示词")
        self._tabs.addTab(self._build_trigger_tab(), "⌨ 触发设置")
        self._tabs.addTab(self._build_ui_tab(), "🎨 界面")

        # 底部按钮
        btn_row = QHBoxLayout()
        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._reset_defaults)

        save_btn = QPushButton("保存并应用")
        save_btn.setObjectName("saveBtn")
        save_btn.clicked.connect(self._save_and_close)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)

        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        main_layout.addLayout(btn_row)

    # ─── 模型配置 Tab ────────────────────────────────────────
    def _build_model_tab(self) -> QWidget:
        container = QWidget()
        main_layout = QHBoxLayout(container)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(12)

        # ── 左侧：模型配置列表与操作按钮 ──
        left_box = QGroupBox("模型配置列表")
        left_layout = QVBoxLayout(left_box)
        left_layout.setSpacing(8)

        self._profile_list = QListWidget()
        self._profile_list.setMinimumWidth(210)
        self._profile_list.currentRowChanged.connect(self._on_profile_list_selection_changed)
        left_layout.addWidget(self._profile_list)

        # 操作按钮 Row 1: 新建 / 复制 / 删除
        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(4)
        add_btn = QPushButton("➕ 新建")
        add_btn.setToolTip("添加一个新的 AI 模型配置")
        add_btn.clicked.connect(self._add_profile)

        copy_btn = QPushButton("📋 复制")
        copy_btn.setToolTip("复制当前选中的模型配置")
        copy_btn.clicked.connect(self._copy_profile)

        self._del_profile_btn = QPushButton("🗑 删除")
        self._del_profile_btn.setToolTip("删除当前选中的模型配置")
        self._del_profile_btn.clicked.connect(self._del_profile)

        btn_row1.addWidget(add_btn)
        btn_row1.addWidget(copy_btn)
        btn_row1.addWidget(self._del_profile_btn)
        left_layout.addLayout(btn_row1)

        # 操作按钮 Row 2: 设为主模型 / 设为查词模型
        btn_row2 = QVBoxLayout()
        btn_row2.setSpacing(4)
        self._set_main_btn = QPushButton("⭐ 设为主翻译模型")
        self._set_main_btn.clicked.connect(self._set_as_main_model)

        self._set_lookup_btn = QPushButton("🔍 设为查词模型")
        self._set_lookup_btn.clicked.connect(self._set_as_lookup_model)

        btn_row2.addWidget(self._set_main_btn)
        btn_row2.addWidget(self._set_lookup_btn)
        left_layout.addLayout(btn_row2)

        main_layout.addWidget(left_box, stretch=4)

        # ── 右侧：模型参数编辑区 ──
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_inner = QWidget()
        right_layout = QVBoxLayout(right_inner)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(10)

        edit_group = QGroupBox("模型参数编辑")
        form_layout = QFormLayout(edit_group)
        form_layout.setSpacing(8)

        self._profile_name_edit = QLineEdit()
        self._profile_name_edit.setPlaceholderText("例如: 通义千问 3.7 / DeepSeek-V3")
        self._profile_name_edit.textEdited.connect(self._on_form_edited)

        self._profile_type_combo = QComboBox()
        self._profile_type_combo.addItems([
            "dashscope (阿里云 DashScope)",
            "openai (OpenAI 兼容 API)",
            "ollama (Ollama 本地)",
        ])
        self._profile_type_combo.currentIndexChanged.connect(self._on_form_edited)

        self._profile_base_url_edit = QLineEdit()
        self._profile_base_url_edit.setPlaceholderText("https://dashscope.aliyuncs.com/api/v1")
        self._profile_base_url_edit.textEdited.connect(self._on_form_edited)

        self._profile_api_key_edit = QLineEdit()
        self._profile_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._profile_api_key_edit.setPlaceholderText("sk-xxxxxxxxxxxxxxxx")
        self._profile_api_key_edit.textEdited.connect(self._on_form_edited)

        self._profile_text_model_edit = QLineEdit()
        self._profile_text_model_edit.setPlaceholderText("例如: qwen3.7-flash / gpt-4o-mini")
        self._profile_text_model_edit.textEdited.connect(self._on_form_edited)

        self._profile_vl_model_edit = QLineEdit()
        self._profile_vl_model_edit.setPlaceholderText("例如: qwen-vl-max / gpt-4o")
        self._profile_vl_model_edit.textEdited.connect(self._on_form_edited)

        self._profile_thinking_combo = QComboBox()
        self._profile_thinking_combo.addItem("默认 (不发送参数 / API 自动决定)", "default")
        self._profile_thinking_combo.addItem("强制关闭 (发送 false / 极速模式)", "off")
        self._profile_thinking_combo.addItem("强制开启 (发送 true / 深度思考)", "on")
        self._profile_thinking_combo.currentIndexChanged.connect(self._on_form_edited)

        form_layout.addRow("模型配置名称:", self._profile_name_edit)
        form_layout.addRow("接口类型:", self._profile_type_combo)
        form_layout.addRow("Base URL:", self._profile_base_url_edit)
        form_layout.addRow("API Key:", self._profile_api_key_edit)
        form_layout.addRow("文本模型名称:", self._profile_text_model_edit)
        form_layout.addRow("VL 视觉模型名称:", self._profile_vl_model_edit)
        form_layout.addRow("Thinking 模式:", self._profile_thinking_combo)

        thinking_note = QLabel("提示:『默认』不向 API 发送任何思考参数，避免标准模型报错；『强制关闭』显式发送 false 禁用思考；『强制开启』显式发送 true 触发推理。")
        thinking_note.setStyleSheet("color: #6b7280; font-size: 11px;")
        thinking_note.setWordWrap(True)
        form_layout.addRow(thinking_note)

        right_layout.addWidget(edit_group)

        self._test_profile_btn = QPushButton("🧪 测试当前模型连接")
        self._test_profile_btn.clicked.connect(self._test_connection)
        right_layout.addWidget(self._test_profile_btn)

        right_layout.addStretch()
        right_scroll.setWidget(right_inner)

        main_layout.addWidget(right_scroll, stretch=6)
        return container

    def _on_profile_list_selection_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._model_profiles):
            return

        self._current_profile_index = row
        p = self._model_profiles[row]

        # 填充右侧表单
        self._profile_name_edit.blockSignals(True)
        self._profile_type_combo.blockSignals(True)
        self._profile_base_url_edit.blockSignals(True)
        self._profile_api_key_edit.blockSignals(True)
        self._profile_text_model_edit.blockSignals(True)
        self._profile_vl_model_edit.blockSignals(True)

        self._profile_name_edit.setText(p.get("name", ""))
        api_type_map = {"dashscope": 0, "openai": 1, "ollama": 2}
        self._profile_type_combo.setCurrentIndex(api_type_map.get(p.get("api_type", "openai"), 1))
        self._profile_base_url_edit.setText(p.get("base_url", ""))
        self._profile_api_key_edit.setText(p.get("api_key", ""))
        self._profile_text_model_edit.setText(p.get("text_model", ""))
        self._profile_vl_model_edit.setText(p.get("vl_model", ""))

        self._profile_thinking_combo.blockSignals(True)
        mode_val = p.get("thinking_mode", "default")
        idx = self._profile_thinking_combo.findData(mode_val)
        if idx >= 0:
            self._profile_thinking_combo.setCurrentIndex(idx)
        else:
            self._profile_thinking_combo.setCurrentIndex(0)
        self._profile_thinking_combo.blockSignals(False)

        self._profile_name_edit.blockSignals(False)
        self._profile_type_combo.blockSignals(False)
        self._profile_base_url_edit.blockSignals(False)
        self._profile_api_key_edit.blockSignals(False)
        self._profile_text_model_edit.blockSignals(False)
        self._profile_vl_model_edit.blockSignals(False)

        # 按钮状态控制
        self._del_profile_btn.setEnabled(len(self._model_profiles) > 1)
        p_id = p.get("id", "")
        self._set_main_btn.setEnabled(p_id != self._active_model_id)
        self._set_lookup_btn.setEnabled(p_id != self._active_lookup_model_id)

    def _on_form_edited(self) -> None:
        if self._current_profile_index < 0 or self._current_profile_index >= len(self._model_profiles):
            return
        p = self._model_profiles[self._current_profile_index]
        p["name"] = self._profile_name_edit.text().strip()
        api_types = ["dashscope", "openai", "ollama"]
        p["api_type"] = api_types[self._profile_type_combo.currentIndex()]
        p["base_url"] = self._profile_base_url_edit.text().strip()
        p["api_key"] = self._profile_api_key_edit.text().strip()
        p["text_model"] = self._profile_text_model_edit.text().strip()
        p["vl_model"] = self._profile_vl_model_edit.text().strip()
        p["thinking_mode"] = self._profile_thinking_combo.currentData() or "default"

        # 实时更新 ListWidget 中的标题
        item = self._profile_list.item(self._current_profile_index)
        if item:
            badges = []
            if p["id"] == self._active_model_id:
                badges.append("⭐主模型")
            if p["id"] == self._active_lookup_model_id:
                badges.append("🔍查词")
            display_text = p["name"] or "未命名模型"
            if badges:
                display_text += f" [{', '.join(badges)}]"
            item.setText(display_text)

        self._refresh_lookup_combo()

    def _refresh_profile_list(self, select_id: str | None = None) -> None:
        self._profile_list.blockSignals(True)
        self._profile_list.clear()
        target_row = 0
        for idx, p in enumerate(self._model_profiles):
            p_id = p.get("id", "")
            badges = []
            if p_id == self._active_model_id:
                badges.append("⭐主模型")
            if p_id == self._active_lookup_model_id:
                badges.append("🔍查词")
            display_text = p.get("name", "未命名模型")
            if badges:
                display_text += f" [{', '.join(badges)}]"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, p_id)
            self._profile_list.addItem(item)
            if select_id and p_id == select_id:
                target_row = idx

        self._profile_list.blockSignals(False)
        if self._model_profiles:
            target_row = min(target_row, len(self._model_profiles) - 1)
            self._profile_list.setCurrentRow(target_row)
            self._on_profile_list_selection_changed(target_row)

        self._refresh_lookup_combo()

    def _refresh_profile_list_badges(self) -> None:
        """刷新列表各项的徽章标记（⭐主模型 / 🔍查词）而无需重新载入全部控件"""
        for idx, p in enumerate(self._model_profiles):
            p_id = p.get("id", "")
            badges = []
            if p_id == self._active_model_id:
                badges.append("⭐主模型")
            if p_id == self._active_lookup_model_id:
                badges.append("🔍查词")
            display_text = p.get("name", "未命名模型")
            if badges:
                display_text += f" [{', '.join(badges)}]"

            item = self._profile_list.item(idx)
            if item:
                item.setText(display_text)

        if 0 <= self._current_profile_index < len(self._model_profiles):
            current_id = self._model_profiles[self._current_profile_index].get("id", "")
            self._set_main_btn.setEnabled(current_id != self._active_model_id)
            self._set_lookup_btn.setEnabled(current_id != self._active_lookup_model_id)

    def _refresh_lookup_combo(self) -> None:
        if not hasattr(self, "_lookup_provider_combo"):
            return
        self._lookup_provider_combo.blockSignals(True)
        self._lookup_provider_combo.clear()
        self._lookup_provider_combo.addItem("与主翻译模型相同", "same")
        for p in self._model_profiles:
            self._lookup_provider_combo.addItem(f"{p.get('name', '未命名')} ({p.get('api_type', '')})", p.get("id"))

        idx = self._lookup_provider_combo.findData(self._active_lookup_model_id)
        if idx >= 0:
            self._lookup_provider_combo.setCurrentIndex(idx)
        else:
            self._lookup_provider_combo.setCurrentIndex(0)
        self._lookup_provider_combo.blockSignals(False)

    def _on_lookup_combo_changed(self) -> None:
        """识别模式 Tab 中下拉框切换查词模型时的实时回调"""
        lookup_data = self._lookup_provider_combo.currentData()
        if lookup_data is not None:
            self._active_lookup_model_id = str(lookup_data)
            self._refresh_profile_list_badges()

    def _add_profile(self) -> None:
        new_id = f"profile_{int(time.time() * 1000)}"
        new_profile = {
            "id": new_id,
            "name": f"自定义模型 {len(self._model_profiles) + 1}",
            "api_type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "text_model": "gpt-4o-mini",
            "vl_model": "",
            "thinking_mode": "default",
        }
        self._model_profiles.append(new_profile)
        self._refresh_profile_list(select_id=new_id)

    def _copy_profile(self) -> None:
        if self._current_profile_index < 0 or self._current_profile_index >= len(self._model_profiles):
            return
        orig = self._model_profiles[self._current_profile_index]
        copied = dict(orig)
        copied["id"] = f"profile_{int(time.time() * 1000)}"
        copied["name"] = f"{orig.get('name', '模型')} (副本)"
        self._model_profiles.insert(self._current_profile_index + 1, copied)
        self._refresh_profile_list(select_id=copied["id"])

    def _del_profile(self) -> None:
        if len(self._model_profiles) <= 1:
            QMessageBox.warning(self, "提示", "至少保留一个模型配置！")
            return
        if self._current_profile_index < 0 or self._current_profile_index >= len(self._model_profiles):
            return

        p = self._model_profiles[self._current_profile_index]
        p_id = p.get("id", "")
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除模型配置【{p.get('name', '')}】吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._model_profiles.pop(self._current_profile_index)
            if self._active_model_id == p_id:
                self._active_model_id = self._model_profiles[0]["id"]
            if self._active_lookup_model_id == p_id:
                self._active_lookup_model_id = "same"
            self._refresh_profile_list()

    def _set_as_main_model(self) -> None:
        if self._current_profile_index >= 0 and self._current_profile_index < len(self._model_profiles):
            p_id = self._model_profiles[self._current_profile_index]["id"]
            self._active_model_id = p_id
            self._refresh_profile_list_badges()
            self._refresh_lookup_combo()

    def _set_as_lookup_model(self) -> None:
        if self._current_profile_index >= 0 and self._current_profile_index < len(self._model_profiles):
            p_id = self._model_profiles[self._current_profile_index]["id"]
            self._active_lookup_model_id = p_id
            self._refresh_profile_list_badges()
            self._refresh_lookup_combo()

    # ─── OCR Tab ─────────────────────────────────────────────
    def _build_ocr_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        engine_group = QGroupBox("OCR 引擎")
        eg_layout = QFormLayout(engine_group)

        self._ocr_engine_combo = QComboBox()
        self._ocr_engine_combo.addItems(["Tesseract", "PaddleOCR"])
        self._ocr_engine_combo.currentIndexChanged.connect(self._on_ocr_engine_changed)

        eg_layout.addRow("引擎:", self._ocr_engine_combo)
        layout.addWidget(engine_group)

        # Tesseract 设置
        self._tess_group = QGroupBox("Tesseract 配置")
        tess_layout = QFormLayout(self._tess_group)

        tess_path_row = QHBoxLayout()
        self._tess_path = QLineEdit()
        self._tess_path.setPlaceholderText("E:/Tool/Tesseract/tesseract.exe")
        browse_btn = QPushButton("浏览...")
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(self._browse_tesseract)
        tess_path_row.addWidget(self._tess_path)
        tess_path_row.addWidget(browse_btn)

        self._tess_lang = QLineEdit()
        self._tess_lang.setPlaceholderText("eng (或 chi_sim+eng)")

        tess_layout.addRow("可执行文件:", tess_path_row)
        tess_layout.addRow("语言参数 -l:", self._tess_lang)

        note = QLabel("提示: 识别视觉小说英文建议使用 eng，中英混合用 chi_sim+eng")
        note.setStyleSheet("color: #6b7280; font-size: 11px;")
        note.setWordWrap(True)
        tess_layout.addRow(note)

        layout.addWidget(self._tess_group)

        # PaddleOCR 设置
        self._paddle_group = QGroupBox("PaddleOCR 配置")
        paddle_layout = QFormLayout(self._paddle_group)

        self._paddle_lang = QLineEdit()
        self._paddle_lang.setPlaceholderText("en")
        paddle_layout.addRow("语言:", self._paddle_lang)

        paddle_note = QLabel(
            "PaddleOCR 首次使用会自动下载模型文件（约 200MB）\n"
            "安装命令: uv pip install paddlepaddle paddleocr"
        )
        paddle_note.setStyleSheet("color: #6b7280; font-size: 11px;")
        paddle_note.setWordWrap(True)
        paddle_layout.addRow(paddle_note)

        layout.addWidget(self._paddle_group)
        layout.addStretch()
        return w

    def _on_ocr_engine_changed(self, idx: int) -> None:
        self._tess_group.setEnabled(idx == 0)
        self._paddle_group.setEnabled(idx == 1)

    def _browse_tesseract(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Tesseract 可执行文件",
            "E:/Tool/Tesseract",
            "可执行文件 (*.exe);;所有文件 (*)"
        )
        if path:
            self._tess_path.setText(path.replace("/", "/"))

    # ─── 识别模式 Tab ────────────────────────────────────────
    def _build_mode_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        mode_group = QGroupBox("识别翻译模式")
        mg_layout = QVBoxLayout(mode_group)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems([
            "模式1: OCR 识别 + 文本大模型矫正翻译",
            "模式2: VL 视觉大模型直接识别翻译",
        ])
        mg_layout.addWidget(QLabel("当前模式:"))
        mg_layout.addWidget(self._mode_combo)

        desc_ocr = QLabel(
            "• 模式1: 先用 OCR 提取文字 → 发送给文本 LLM 矫正+翻译\n"
            "  优点: 速度快，token 消耗少\n"
            "  缺点: OCR 可能识别不准，字体艺术字效果差"
        )
        desc_ocr.setStyleSheet("color: #6b7280; font-size: 11px;")
        desc_ocr.setWordWrap(True)

        desc_vl = QLabel(
            "• 模式2: 直接将截图发给 VL 大模型\n"
            "  优点: 识别准确，支持艺术字和复杂布局\n"
            "  缺点: 较慢，token 消耗较多，需要 VL 模型支持"
        )
        desc_vl.setStyleSheet("color: #6b7280; font-size: 11px;")
        desc_vl.setWordWrap(True)

        mg_layout.addWidget(desc_ocr)
        mg_layout.addWidget(make_divider())
        mg_layout.addWidget(desc_vl)
        layout.addWidget(mode_group)

        # 查词模型独立配置
        lookup_group = QGroupBox("查词模型设置")
        lk_layout = QFormLayout(lookup_group)

        self._lookup_provider_combo = QComboBox()
        self._lookup_provider_combo.currentIndexChanged.connect(self._on_lookup_combo_changed)
        lk_layout.addRow("查词模型:", self._lookup_provider_combo)

        lookup_note = QLabel("提示: 与【🤖 模型配置】中的『🔍 设为查词模型』完全实时同步。选择『与主翻译模型相同』则自动随主模型切换。")
        lookup_note.setStyleSheet("color: #6b7280; font-size: 11px;")
        lookup_note.setWordWrap(True)
        lk_layout.addRow(lookup_note)

        layout.addWidget(lookup_group)
        layout.addStretch()
        return w

    # ─── 游戏适配 Tab ────────────────────────────────────────
    def _build_game_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: #111128; } "
            "QWidget#gameSettings { background: #111128; } "
            "QCheckBox:disabled, QLabel:disabled { color: #64748b; } "
            "QTextEdit:disabled { color: #64748b; background: #141428; } "
            "QScrollBar:vertical { background: #111128; width: 10px; } "
            "QScrollBar::handle:vertical { background: #374151; border-radius: 4px; min-height: 24px; } "
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; } "
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }"
        )
        inner = QWidget()
        inner.setObjectName("gameSettings")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        game_form = QFormLayout()
        self._game_profile = QComboBox()
        self._game_profile.addItem("通用（所有游戏）", "generic")
        self._game_profile.addItem("原神", "genshin")
        game_form.addRow("当前游戏:", self._game_profile)
        layout.addLayout(game_form)

        self._genshin_group = QGroupBox("原神对白与译名")
        group_layout = QVBoxLayout(self._genshin_group)
        group_layout.setSpacing(10)

        self._genshin_adaptive_dialogue = QCheckBox("自动排除金色人名 / 称号，适应多行对白")
        self._genshin_use_glossary = QCheckBox("使用本地中英术语表，优先采用原神译名")
        group_layout.addWidget(self._genshin_adaptive_dialogue)

        capture_note = QLabel(
            "保存后，在主窗口选择游戏窗口，点击“原神对白区域”，一次覆盖底部多行台词。"
            "也可以手动框大一些并用“预览识别范围”检查，范围应同时包含人名、称号和完整对白。"
            "识别时会根据金色人名 / 称号的位置排除标题；框外的文字无法恢复。"
        )
        capture_note.setWordWrap(True)
        capture_note.setStyleSheet("color: #94a3b8; font-size: 11px;")
        group_layout.addWidget(capture_note)
        group_layout.addWidget(make_divider())
        group_layout.addWidget(self._genshin_use_glossary)

        glossary_note = QLabel(
            "仅将当前对白命中的中英对应项提供给模型，保留英文学习原文。"
            "内置词表来自 Genshin Dictionary 社区公开数据，可能存在缺漏；识别时只查询本地词表。"
            "下方自定义项可补充新角色、称号或覆盖内置译名。"
        )
        glossary_note.setWordWrap(True)
        glossary_note.setStyleSheet("color: #94a3b8; font-size: 11px;")
        group_layout.addWidget(glossary_note)
        source_link = QLabel(
            '<a href="https://genshin-dictionary.com/en/opendata" style="color: #a78bfa;">'
            "查看词表来源与开放数据说明</a>"
        )
        source_link.setOpenExternalLinks(True)
        group_layout.addWidget(source_link)
        group_layout.addWidget(QLabel("自定义术语（选填，每行 English = 中文）:"))
        self._genshin_custom_terms = QTextEdit()
        self._genshin_custom_terms.setAcceptRichText(False)
        self._genshin_custom_terms.setPlaceholderText("Paimon = 派蒙\nLiyue = 璃月")
        self._genshin_custom_terms.setMinimumHeight(105)
        self._genshin_custom_terms.setMaximumHeight(135)
        group_layout.addWidget(self._genshin_custom_terms)

        cost_note = QLabel(
            "建议使用“OCR + 文本大模型”模式。启用词表后，VL 识图遇到新增命中的术语时，"
            "最多追加一次校正请求，增加耗时和 API 用量。切回通用游戏会保留以上选项。"
        )
        cost_note.setWordWrap(True)
        cost_note.setStyleSheet("color: #94a3b8; font-size: 11px;")
        group_layout.addWidget(cost_note)
        layout.addWidget(self._genshin_group)
        layout.addStretch()
        scroll.setWidget(inner)
        self._game_profile.currentIndexChanged.connect(self._on_game_profile_changed)
        self._on_game_profile_changed()
        return scroll

    def _on_game_profile_changed(self, _index: int = -1) -> None:
        self._genshin_group.setEnabled(self._game_profile.currentData() == "genshin")

    # ─── 提示词 Tab ──────────────────────────────────────────
    def _build_prompt_tab(self) -> QWidget:
        w = QScrollArea()
        w.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        def make_prompt_editor(label: str, placeholder: str = "") -> QTextEdit:
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #a78bfa; font-size: 12px; font-weight: bold;")
            layout.addWidget(lbl)
            editor = QTextEdit()
            editor.setPlaceholderText(placeholder)
            editor.setFixedHeight(130)
            editor.setStyleSheet(
                "background: #141428; color: #e2e8f0; border: 1px solid #374151; "
                "border-radius: 6px; padding: 8px; font-size: 11px; font-family: Consolas;"
            )
            layout.addWidget(editor)
            return editor

        self._prompt_text = make_prompt_editor(
            "📖 OCR 模式翻译 Prompt（{text} 占位符会被替换为 OCR 文本）"
        )
        self._prompt_vl = make_prompt_editor(
            "🖼 VL 模式翻译 Prompt（直接发送图片时使用）"
        )
        self._prompt_lookup = make_prompt_editor(
            "🔍 查词 Prompt（{context} = 上下文，{selected} = 选中词）"
        )

        layout.addStretch()
        w.setWidget(inner)
        return w

    # ─── 触发设置 Tab ────────────────────────────────────────
    def _build_trigger_tab(self) -> QWidget:
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setFrameShape(QFrame.Shape.NoFrame)
        w.setStyleSheet("QScrollArea { background: #111128; } QWidget#triggerSettings { background: #111128; }")
        inner = QWidget()
        inner.setObjectName("triggerSettings")
        layout = QVBoxLayout(inner)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        hotkey_group = QGroupBox("全局快捷键")
        hk_layout = QFormLayout(hotkey_group)

        self._hotkey_edit = QLineEdit()
        self._hotkey_edit.setPlaceholderText("ctrl+shift+t")
        hk_layout.addRow("触发快捷键:", self._hotkey_edit)

        hk_note = QLabel("支持的格式: ctrl+shift+t, alt+f1, shift+f5 等")
        hk_note.setStyleSheet("color: #6b7280; font-size: 11px;")
        hk_layout.addRow(hk_note)
        layout.addWidget(hotkey_group)

        watcher_group = QGroupBox("自动监视设置")
        wg_layout = QFormLayout(watcher_group)

        self._watcher_enabled = QCheckBox("启用自动变化检测")
        wg_layout.addRow(self._watcher_enabled)

        self._watcher_preset = QComboBox()
        self._watcher_preset.addItem("自动适应（推荐）", "auto")
        self._watcher_preset.addItem("快速字幕", "fast")
        self._watcher_preset.addItem("慢速打字", "stable")
        self._watcher_preset.addItem("手动微调", "custom")
        wg_layout.addRow("监视方案:", self._watcher_preset)

        self._watcher_preset_note = QLabel()
        self._watcher_preset_note.setWordWrap(True)
        self._watcher_preset_note.setStyleSheet("color: #94a3b8; font-size: 11px;")
        wg_layout.addRow(self._watcher_preset_note)

        self._watcher_custom_group = QGroupBox("手动参数（切换方案后仍会保留）")
        custom_layout = QFormLayout(self._watcher_custom_group)

        self._poll_interval = QDoubleSpinBox()
        self._poll_interval.setRange(0.1, 5.0)
        self._poll_interval.setSingleStep(0.1)
        self._poll_interval.setDecimals(1)
        self._poll_interval.setSuffix(" 秒")
        self._poll_interval.setToolTip("本地 OCR 的基础检测间隔。间隔越短响应越快，但 CPU 占用可能增加。")
        custom_layout.addRow("基础 OCR 间隔:", self._poll_interval)

        self._stability_count = QSpinBox()
        self._stability_count.setRange(1, 10)
        self._stability_count.setSuffix(" 次")
        self._stability_count.setToolTip("连续识别到稳定文本后才翻译。慢速打字可增加次数；快速字幕可减少。")
        custom_layout.addRow("文本稳定确认次数:", self._stability_count)

        self._hash_threshold = QSpinBox()
        self._hash_threshold.setRange(1, 64)
        custom_layout.addRow("帧变化提示阈值 (1-64):", self._hash_threshold)

        threshold_note = QLabel(
            "帧变化只用于提示加快检测，不会阻止周期性 OCR。"
            "阈值越小越容易加快检测；通常保留 8 即可。背景动画本身不会直接触发翻译。"
        )
        threshold_note.setStyleSheet("color: #6b7280; font-size: 11px;")
        threshold_note.setWordWrap(True)
        custom_layout.addRow(threshold_note)
        wg_layout.addRow(self._watcher_custom_group)

        setup_note = QLabel(
            "先只框选对话或字幕区域，尽量避开角色动画和其他界面文字。"
            "默认使用自动适应；文字逐字出现且翻译过早时选“慢速打字”，"
            "字幕切换很快时选“快速字幕”。只有需要进一步调整时才选“手动微调”。"
        )
        setup_note.setStyleSheet("color: #94a3b8; font-size: 11px;")
        setup_note.setWordWrap(True)
        wg_layout.addRow(setup_note)

        self._watcher_preset.currentIndexChanged.connect(self._on_watcher_preset_changed)
        self._on_watcher_preset_changed()

        layout.addWidget(watcher_group)
        layout.addStretch()
        w.setWidget(inner)
        return w

    def _on_watcher_preset_changed(self, _index: int = -1) -> None:
        preset = self._watcher_preset.currentData()
        descriptions = {
            "auto": "依据本地 OCR 耗时和文字空闲时长自动调整检测频率，在响应速度和性能之间取得平衡。无需调整下面的手动参数。",
            "fast": "更频繁地检查文字并缩短稳定等待，适合快速切换的完整字幕；逐字出现的文本可能会较早翻译。",
            "stable": "延长文本稳定等待，适合慢速打字或逐字显示的对话；完整句子的翻译会稍晚出现。",
            "custom": "使用下方保存的手动参数。建议先调 OCR 间隔和文本稳定次数，再考虑帧变化提示阈值。",
        }
        self._watcher_preset_note.setText(descriptions.get(preset, descriptions["auto"]))
        is_custom = preset == "custom"
        self._watcher_custom_group.setVisible(is_custom)
        self._watcher_custom_group.setEnabled(is_custom)

    # ─── UI 设置 Tab ─────────────────────────────────────────
    def _build_ui_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        panel_group = QGroupBox("结果面板")
        pg_layout = QFormLayout(panel_group)

        self._always_on_top = QCheckBox("始终置顶显示")
        pg_layout.addRow(self._always_on_top)

        self._font_size_en = QSpinBox()
        self._font_size_en.setRange(9, 24)
        self._font_size_en.setSuffix(" px")
        pg_layout.addRow("英文字体大小:", self._font_size_en)

        self._font_size_zh = QSpinBox()
        self._font_size_zh.setRange(9, 28)
        self._font_size_zh.setSuffix(" px")
        pg_layout.addRow("中文字体大小:", self._font_size_zh)

        layout.addWidget(panel_group)
        layout.addStretch()
        return w

    # ─── 读写配置 ────────────────────────────────────────────
    def _load_values(self) -> None:
        c = self._cfg
        self._model_profiles = c.get_model_profiles()
        self._active_model_id = c.get("active_model_id") or "dashscope_default"
        self._active_lookup_model_id = c.get("active_word_lookup_model_id") or "same"

        # OCR
        engine_map = {"tesseract": 0, "paddleocr": 1}
        self._ocr_engine_combo.setCurrentIndex(engine_map.get(c.get("ocr", "engine"), 0))
        self._tess_path.setText(c.get("ocr", "tesseract_path") or "")
        self._tess_lang.setText(c.get("ocr", "tesseract_lang") or "eng")
        self._paddle_lang.setText(c.get("ocr", "paddleocr_lang") or "en")

        # 模式
        mode_map = {"ocr": 0, "vl": 1}
        self._mode_combo.setCurrentIndex(mode_map.get(c.get("recognition_mode"), 0))

        # 游戏适配（停用时仍保留各项设置）
        game_index = self._game_profile.findData(c.get("game", "profile", default="generic"))
        self._game_profile.setCurrentIndex(max(game_index, 0))
        self._genshin_adaptive_dialogue.setChecked(
            c.get("game", "genshin", "adaptive_dialogue", default=True)
        )
        self._genshin_use_glossary.setChecked(c.get("game", "genshin", "use_glossary", default=True))
        custom_terms = c.get("game", "genshin", "custom_terms", default={})
        self._genshin_custom_terms.setPlainText(
            "\n".join(f"{english} = {chinese}" for english, chinese in custom_terms.items())
        )
        self._on_game_profile_changed()

        # Prompts
        self._prompt_text.setPlainText(c.get("prompts", "translate_text") or "")
        self._prompt_vl.setPlainText(c.get("prompts", "translate_vl") or "")
        self._prompt_lookup.setPlainText(c.get("prompts", "word_lookup") or "")

        # 触发
        self._hotkey_edit.setText(c.get("hotkey") or "ctrl+shift+t")
        self._watcher_enabled.setChecked(c.get("watcher", "enabled", default=True))
        preset_index = self._watcher_preset.findData(c.get("watcher", "preset", default="auto"))
        self._watcher_preset.setCurrentIndex(max(preset_index, 0))
        self._on_watcher_preset_changed()
        self._poll_interval.setValue(c.get("watcher", "poll_interval", default=0.3))
        self._stability_count.setValue(c.get("watcher", "stability_count", default=2))
        self._hash_threshold.setValue(c.get("watcher", "hash_threshold", default=8))

        # UI
        self._always_on_top.setChecked(c.get("ui", "always_on_top", default=True))
        self._font_size_en.setValue(c.get("ui", "font_size_en") or 13)
        self._font_size_zh.setValue(c.get("ui", "font_size_zh") or 14)

        # 刷新列表与状态
        self._refresh_profile_list(select_id=self._active_model_id)
        self._on_ocr_engine_changed(self._ocr_engine_combo.currentIndex())

    def _save_values(self) -> None:
        # Validate before save_models(), which persists immediately.
        custom_terms = parse_custom_terms(self._genshin_custom_terms.toPlainText())
        self._on_form_edited()
        c = self._cfg

        lookup_data = self._lookup_provider_combo.currentData() or "same"
        self._active_lookup_model_id = str(lookup_data)

        c.save_models(self._model_profiles, self._active_model_id, self._active_lookup_model_id)

        engines = ["tesseract", "paddleocr"]
        c.set("ocr", "engine", engines[self._ocr_engine_combo.currentIndex()])
        c.set("ocr", "tesseract_path", self._tess_path.text().strip())
        c.set("ocr", "tesseract_lang", self._tess_lang.text().strip())
        c.set("ocr", "paddleocr_lang", self._paddle_lang.text().strip())

        modes = ["ocr", "vl"]
        c.set("recognition_mode", modes[self._mode_combo.currentIndex()])

        c.set("game", "profile", self._game_profile.currentData() or "generic")
        c.set("game", "genshin", "adaptive_dialogue", self._genshin_adaptive_dialogue.isChecked())
        c.set("game", "genshin", "use_glossary", self._genshin_use_glossary.isChecked())
        c.set("game", "genshin", "custom_terms", custom_terms)

        c.set("prompts", "translate_text", self._prompt_text.toPlainText())
        c.set("prompts", "translate_vl", self._prompt_vl.toPlainText())
        c.set("prompts", "word_lookup", self._prompt_lookup.toPlainText())

        c.set("hotkey", self._hotkey_edit.text().strip())
        c.set("watcher", "enabled", self._watcher_enabled.isChecked())
        c.set("watcher", "preset", self._watcher_preset.currentData() or "auto")
        c.set("watcher", "poll_interval", self._poll_interval.value())
        c.set("watcher", "stability_count", self._stability_count.value())
        c.set("watcher", "hash_threshold", self._hash_threshold.value())

        c.set("ui", "always_on_top", self._always_on_top.isChecked())
        c.set("ui", "font_size_en", self._font_size_en.value())
        c.set("ui", "font_size_zh", self._font_size_zh.value())

        c.save()

    def _save_and_close(self) -> None:
        self._on_form_edited()
        modes = ["ocr", "vl"]
        selected_mode = modes[self._mode_combo.currentIndex()]

        active_profile = None
        for p in self._model_profiles:
            if p.get("id") == self._active_model_id:
                active_profile = p
                break

        if active_profile is None and self._model_profiles:
            active_profile = self._model_profiles[0]

        if selected_mode == "vl" and active_profile and not active_profile.get("vl_model", "").strip():
            QMessageBox.warning(
                self,
                "无法保存配置",
                f"当前识别模式选择为【VL大模型直接识别】，但主模型【{active_profile.get('name')}】的 VL 视觉模型名称为空，无法启用此模式。\n\n"
                "请先在模型参数编辑区填写 【VL 视觉模型名称】，或将识别模式更改为【OCR+文本LLM】。"
            )
            return

        try:
            self._save_values()
        except ValueError as exc:
            self._tabs.setCurrentWidget(self._game_tab)
            QMessageBox.warning(self, "自定义术语无法保存", str(exc))
            return
        self.config_changed.emit()
        self.accept()

    def _reset_defaults(self) -> None:
        reply = QMessageBox.question(
            self, "确认", "确定要重置所有设置为默认值吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._cfg.reset_to_defaults()
            self._load_values()

    def _test_connection(self) -> None:
        """测试当前编辑框中的模型配置连接（异步非阻塞版）"""
        self._on_form_edited()
        if self._current_profile_index < 0 or self._current_profile_index >= len(self._model_profiles):
            return

        if self._test_worker and self._test_worker.isRunning():
            return

        profile = self._model_profiles[self._current_profile_index]

        self._test_profile_btn.setEnabled(False)
        self._test_profile_btn.setText("⏳ 测试中，请稍候...")

        self._test_worker = TestConnectionWorker(profile, self)
        self._test_worker.test_finished.connect(self._on_test_finished)
        self._test_worker.start()

    @Slot(bool, str, str)
    def _on_test_finished(self, success: bool, msg: str, profile_name: str) -> None:
        self._test_profile_btn.setEnabled(True)
        self._test_profile_btn.setText("🧪 测试当前模型连接")

        if success:
            QMessageBox.information(
                self,
                "连接成功",
                f"✅ 模型 [{profile_name}] 响应正常\n\n响应: {msg}"
            )
        else:
            QMessageBox.critical(
                self,
                "连接失败",
                f"❌ 模型 [{profile_name}] 连接失败\n\n{msg}"
            )

    def closeEvent(self, event) -> None:
        if self._test_worker and self._test_worker.isRunning():
            self._test_worker.terminate()
        super().closeEvent(event)
