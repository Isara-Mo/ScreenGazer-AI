"""
配置对话框
Config Dialog - tabbed settings for models, OCR, prompts, and hotkeys
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QLabel, QLineEdit, QTextEdit, QPushButton,
    QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QFormLayout, QFileDialog, QFrame,
    QScrollArea, QMessageBox, QSlider,
)

from src.utils.config_manager import ConfigManager


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
QPushButton {
    background-color: #1e1e3a;
    color: #94a3b8;
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 6px 16px;
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


class ConfigDialog(QDialog):
    """配置对话框，应用更改时发出信号通知主窗口重新初始化"""

    config_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("⚙ 翻译助手设置")
        self.setMinimumSize(640, 560)
        self.resize(680, 620)
        self.setStyleSheet(DIALOG_STYLE)
        self._cfg = ConfigManager()
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

        self._tabs.addTab(self._build_model_tab(), "🤖 模型")
        self._tabs.addTab(self._build_ocr_tab(), "🔍 OCR")
        self._tabs.addTab(self._build_mode_tab(), "⚡ 识别模式")
        self._tabs.addTab(self._build_prompt_tab(), "📝 提示词")
        self._tabs.addTab(self._build_trigger_tab(), "⌨ 触发设置")
        self._tabs.addTab(self._build_ui_tab(), "🎨 界面")

        # 底部按钮
        btn_row = QHBoxLayout()
        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._reset_defaults)

        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(self._test_connection)

        save_btn = QPushButton("保存并应用")
        save_btn.setObjectName("saveBtn")
        save_btn.clicked.connect(self._save_and_close)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)

        btn_row.addWidget(reset_btn)
        btn_row.addWidget(test_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        main_layout.addLayout(btn_row)

    # ─── 模型配置 Tab ────────────────────────────────────────
    def _build_model_tab(self) -> QWidget:
        w = QScrollArea()
        w.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        # 提供商选择
        provider_group = QGroupBox("主模型提供商")
        pg_layout = QFormLayout(provider_group)
        self._provider_combo = QComboBox()
        self._provider_combo.addItems(["dashscope (阿里云通义)", "openai (OpenAI兼容)", "ollama (本地)"])
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        pg_layout.addRow("提供商:", self._provider_combo)
        layout.addWidget(provider_group)

        # DashScope
        self._ds_group = QGroupBox("DashScope (阿里云)")
        ds_layout = QFormLayout(self._ds_group)
        self._ds_base_url = QLineEdit()
        self._ds_base_url.setPlaceholderText("https://dashscope.aliyuncs.com/api/v1 (或自定义 workspace URL)")
        self._ds_api_key = QLineEdit()
        self._ds_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._ds_api_key.setPlaceholderText("sk-xxxxxxxxxxxxxxxx")
        self._ds_text_model = QLineEdit()
        self._ds_text_model.setPlaceholderText("qwen-turbo")
        self._ds_vl_model = QLineEdit()
        self._ds_vl_model.setPlaceholderText("qwen3.6-flash")
        ds_layout.addRow("Base URL:", self._ds_base_url)
        ds_layout.addRow("API Key:", self._ds_api_key)
        ds_layout.addRow("文本模型:", self._ds_text_model)
        ds_layout.addRow("VL 模型:", self._ds_vl_model)
        layout.addWidget(self._ds_group)

        # OpenAI 兼容
        self._oa_group = QGroupBox("OpenAI 兼容 API")
        oa_layout = QFormLayout(self._oa_group)
        self._oa_base_url = QLineEdit()
        self._oa_base_url.setPlaceholderText("https://api.openai.com/v1")
        self._oa_api_key = QLineEdit()
        self._oa_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._oa_text_model = QLineEdit()
        self._oa_text_model.setPlaceholderText("gpt-4o-mini")
        self._oa_vl_model = QLineEdit()
        self._oa_vl_model.setPlaceholderText("gpt-4o")
        oa_layout.addRow("Base URL:", self._oa_base_url)
        oa_layout.addRow("API Key:", self._oa_api_key)
        oa_layout.addRow("文本模型:", self._oa_text_model)
        oa_layout.addRow("VL 模型:", self._oa_vl_model)
        layout.addWidget(self._oa_group)

        # Ollama
        self._ollama_group = QGroupBox("Ollama 本地模型")
        ol_layout = QFormLayout(self._ollama_group)
        self._ol_base_url = QLineEdit()
        self._ol_base_url.setPlaceholderText("http://localhost:11434")
        self._ol_text_model = QLineEdit()
        self._ol_text_model.setPlaceholderText("llama3.2")
        self._ol_vl_model = QLineEdit()
        self._ol_vl_model.setPlaceholderText("llava")
        ol_layout.addRow("Base URL:", self._ol_base_url)
        ol_layout.addRow("文本模型:", self._ol_text_model)
        ol_layout.addRow("VL 模型:", self._ol_vl_model)
        layout.addWidget(self._ollama_group)

        layout.addStretch()
        w.setWidget(inner)
        return w

    def _on_provider_changed(self, idx: int) -> None:
        providers = ["dashscope", "openai", "ollama"]
        groups = [self._ds_group, self._oa_group, self._ollama_group]
        for i, g in enumerate(groups):
            g.setEnabled(i == idx)

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
        self._lookup_provider_combo.addItems([
            "与翻译模型相同",
            "dashscope (阿里云通义)",
            "openai (OpenAI兼容)",
            "ollama (本地)",
        ])
        lk_layout.addRow("查词模型:", self._lookup_provider_combo)
        layout.addWidget(lookup_group)
        layout.addStretch()
        return w

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
        w = QWidget()
        layout = QVBoxLayout(w)
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

        self._poll_interval = QDoubleSpinBox()
        self._poll_interval.setRange(0.1, 5.0)
        self._poll_interval.setSingleStep(0.1)
        self._poll_interval.setDecimals(1)
        self._poll_interval.setSuffix(" 秒")
        wg_layout.addRow("轮询间隔:", self._poll_interval)

        self._stability_count = QSpinBox()
        self._stability_count.setRange(1, 10)
        self._stability_count.setSuffix(" 次")
        wg_layout.addRow("稳定确认次数:", self._stability_count)

        self._hash_threshold = QSpinBox()
        self._hash_threshold.setRange(1, 64)
        wg_layout.addRow("图像变化阈值 (1-64):", self._hash_threshold)

        threshold_note = QLabel("阈值越小越灵敏，推荐 5-10。对快速切换场景适当调大")
        threshold_note.setStyleSheet("color: #6b7280; font-size: 11px;")
        threshold_note.setWordWrap(True)
        wg_layout.addRow(threshold_note)

        layout.addWidget(watcher_group)
        layout.addStretch()
        return w

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

        # 提供商
        provider_map = {"dashscope": 0, "openai": 1, "ollama": 2}
        self._provider_combo.setCurrentIndex(provider_map.get(c.get("provider"), 0))

        # DashScope
        self._ds_base_url.setText(c.get("dashscope", "base_url") or "")
        self._ds_api_key.setText(c.get("dashscope", "api_key") or "")
        self._ds_text_model.setText(c.get("dashscope", "text_model") or "")
        self._ds_vl_model.setText(c.get("dashscope", "vl_model") or "")

        # OpenAI
        self._oa_base_url.setText(c.get("openai", "base_url") or "")
        self._oa_api_key.setText(c.get("openai", "api_key") or "")
        self._oa_text_model.setText(c.get("openai", "text_model") or "")
        self._oa_vl_model.setText(c.get("openai", "vl_model") or "")

        # Ollama
        self._ol_base_url.setText(c.get("ollama", "base_url") or "")
        self._ol_text_model.setText(c.get("ollama", "text_model") or "")
        self._ol_vl_model.setText(c.get("ollama", "vl_model") or "")

        # OCR
        engine_map = {"tesseract": 0, "paddleocr": 1}
        self._ocr_engine_combo.setCurrentIndex(engine_map.get(c.get("ocr", "engine"), 0))
        self._tess_path.setText(c.get("ocr", "tesseract_path") or "")
        self._tess_lang.setText(c.get("ocr", "tesseract_lang") or "eng")
        self._paddle_lang.setText(c.get("ocr", "paddleocr_lang") or "en")

        # 模式
        mode_map = {"ocr": 0, "vl": 1}
        self._mode_combo.setCurrentIndex(mode_map.get(c.get("recognition_mode"), 0))

        lookup_map = {"same": 0, "dashscope": 1, "openai": 2, "ollama": 3}
        self._lookup_provider_combo.setCurrentIndex(
            lookup_map.get(c.get("word_lookup_provider"), 0)
        )

        # Prompts
        self._prompt_text.setPlainText(c.get("prompts", "translate_text") or "")
        self._prompt_vl.setPlainText(c.get("prompts", "translate_vl") or "")
        self._prompt_lookup.setPlainText(c.get("prompts", "word_lookup") or "")

        # 触发
        self._hotkey_edit.setText(c.get("hotkey") or "ctrl+shift+t")
        self._watcher_enabled.setChecked(c.get("watcher", "enabled") or True)
        self._poll_interval.setValue(c.get("watcher", "poll_interval") or 0.5)
        self._stability_count.setValue(c.get("watcher", "stability_count") or 3)
        self._hash_threshold.setValue(c.get("watcher", "hash_threshold") or 8)

        # UI
        self._always_on_top.setChecked(c.get("ui", "always_on_top") or True)
        self._font_size_en.setValue(c.get("ui", "font_size_en") or 13)
        self._font_size_zh.setValue(c.get("ui", "font_size_zh") or 14)

        # 触发初始 UI 状态更新
        self._on_provider_changed(self._provider_combo.currentIndex())
        self._on_ocr_engine_changed(self._ocr_engine_combo.currentIndex())

    def _save_values(self) -> None:
        c = self._cfg

        providers = ["dashscope", "openai", "ollama"]
        c.set("provider", providers[self._provider_combo.currentIndex()])

        c.set("dashscope", "base_url", self._ds_base_url.text().strip())
        c.set("dashscope", "api_key", self._ds_api_key.text().strip())
        c.set("dashscope", "text_model", self._ds_text_model.text().strip())
        c.set("dashscope", "vl_model", self._ds_vl_model.text().strip())

        c.set("openai", "base_url", self._oa_base_url.text().strip())
        c.set("openai", "api_key", self._oa_api_key.text().strip())
        c.set("openai", "text_model", self._oa_text_model.text().strip())
        c.set("openai", "vl_model", self._oa_vl_model.text().strip())

        c.set("ollama", "base_url", self._ol_base_url.text().strip())
        c.set("ollama", "text_model", self._ol_text_model.text().strip())
        c.set("ollama", "vl_model", self._ol_vl_model.text().strip())

        engines = ["tesseract", "paddleocr"]
        c.set("ocr", "engine", engines[self._ocr_engine_combo.currentIndex()])
        c.set("ocr", "tesseract_path", self._tess_path.text().strip())
        c.set("ocr", "tesseract_lang", self._tess_lang.text().strip())
        c.set("ocr", "paddleocr_lang", self._paddle_lang.text().strip())

        modes = ["ocr", "vl"]
        c.set("recognition_mode", modes[self._mode_combo.currentIndex()])

        lookup_providers = ["same", "dashscope", "openai", "ollama"]
        c.set("word_lookup_provider", lookup_providers[self._lookup_provider_combo.currentIndex()])

        c.set("prompts", "translate_text", self._prompt_text.toPlainText())
        c.set("prompts", "translate_vl", self._prompt_vl.toPlainText())
        c.set("prompts", "word_lookup", self._prompt_lookup.toPlainText())

        c.set("hotkey", self._hotkey_edit.text().strip())
        c.set("watcher", "enabled", self._watcher_enabled.isChecked())
        c.set("watcher", "poll_interval", self._poll_interval.value())
        c.set("watcher", "stability_count", self._stability_count.value())
        c.set("watcher", "hash_threshold", self._hash_threshold.value())

        c.set("ui", "always_on_top", self._always_on_top.isChecked())
        c.set("ui", "font_size_en", self._font_size_en.value())
        c.set("ui", "font_size_zh", self._font_size_zh.value())

        c.save()

    def _save_and_close(self) -> None:
        self._save_values()
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
        """测试当前配置的模型连接"""
        from PySide6.QtWidgets import QProgressDialog
        provider = ["dashscope", "openai", "ollama"][self._provider_combo.currentIndex()]

        cfg_map = {
            "dashscope": {
                "api_key": self._ds_api_key.text().strip(),
                "base_url": self._ds_base_url.text().strip(),
                "text_model": self._ds_text_model.text().strip(),
                "vl_model": self._ds_vl_model.text().strip(),
            },
            "openai": {
                "base_url": self._oa_base_url.text().strip(),
                "api_key": self._oa_api_key.text().strip(),
                "text_model": self._oa_text_model.text().strip(),
            },
            "ollama": {
                "base_url": self._ol_base_url.text().strip(),
                "text_model": self._ol_text_model.text().strip(),
            },
        }

        try:
            from src.core.llm_client import create_client
            client = create_client(provider, cfg_map[provider])
            response = client.chat([{"role": "user", "content": "Say 'OK' in one word."}])
            QMessageBox.information(self, "连接成功", f"✅ 模型响应正常\n响应: {response[:100]}")
        except Exception as e:
            QMessageBox.critical(self, "连接失败", f"❌ 连接失败\n\n{e}")
