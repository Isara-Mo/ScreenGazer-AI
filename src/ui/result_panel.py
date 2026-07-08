"""
结果显示面板
Result Panel - floating always-on-top window showing corrected English + Chinese translation
Supports word/phrase clicking with Ctrl-modifier for multi-word selection
"""

from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import (
    Qt, Signal, QPoint, QRect, QTimer, QSize,
)
from PySide6.QtGui import (
    QFont, QColor, QTextCursor, QMouseEvent,
    QKeyEvent, QPalette, QTextCharFormat, QCursor,
    QIcon, QFontMetrics, QPainter, QLinearGradient,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QFrame, QSizeGrip,
    QScrollArea, QApplication, QToolButton,
)

# ─── 全局样式 ───────────────────────────────────────────────
PANEL_STYLE = """
QWidget#resultPanel {
    background-color: #0f0f1a;
    border-radius: 14px;
    border: 1px solid #2d2d4a;
}

/* 标题栏 */
QFrame#titleBar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #1a1a3e, stop:1 #0f0f1a);
    border-radius: 14px 14px 0 0;
    border-bottom: 1px solid #2d2d4a;
}
QLabel#titleLabel {
    color: #a78bfa; font-size: 13px; font-weight: bold;
}
QLabel#statusLabel {
    color: #4b5563; font-size: 11px;
}

/* 英文区域标题 */
QLabel#sectionLabelEn {
    color: #60a5fa; font-size: 11px; font-weight: bold;
    letter-spacing: 1px;
}
QLabel#sectionLabelZh {
    color: #34d399; font-size: 11px; font-weight: bold;
    letter-spacing: 1px;
}

/* 英文文本编辑框 */
QTextEdit#englishText {
    background-color: #141428;
    color: #e2e8f0;
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    padding: 10px;
    selection-background-color: #4c1d95;
    selection-color: #e2e8f0;
    font-size: 13px;
    line-height: 1.6;
}

/* 中文文本框 */
QTextEdit#chineseText {
    background-color: #0a1628;
    color: #a7f3d0;
    border: 1px solid #1e3a2a;
    border-radius: 8px;
    padding: 10px;
    font-size: 14px;
    line-height: 1.8;
}

/* 控制按钮 */
QPushButton.controlBtn {
    background-color: #1e1e3a;
    color: #94a3b8;
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11px;
}
QPushButton.controlBtn:hover {
    background-color: #2d2d5a; color: #e2e8f0; border-color: #6366f1;
}
QPushButton.controlBtn:pressed {
    background-color: #1e1e5a;
}

/* 加载动画标签 */
QLabel#loadingLabel {
    color: #6366f1; font-size: 12px;
}

/* 分隔线 */
QFrame.divider {
    border: none; border-top: 1px solid #1e1e3a;
}
"""


class ClickableTextEdit(QTextEdit):
    """
    支持单词点击查询的英文文本框
    
    交互规则:
    - 单击: 选中光标处单词，立即触发查词
    - Ctrl + 拖拽/多次单击: 积累选词范围，Ctrl 松开时触发查词
    """

    word_lookup_requested = Signal(str)   # 触发查词，携带选中文本

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("englishText")
        self.setReadOnly(True)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.setCursor(QCursor(Qt.CursorShape.IBeamCursor))

        self._ctrl_mode = False          # 是否在 Ctrl 多选模式
        self._ctrl_selection_start: Optional[int] = None
        self._ctrl_selection_end: Optional[int] = None

        font = QFont("Georgia", 13)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 102)
        self.setFont(font)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            ctrl_held = event.modifiers() & Qt.KeyboardModifier.ControlModifier
            if ctrl_held:
                # Ctrl 按下：进入多选模式，记录位置
                self._ctrl_mode = True
                cursor = self.cursorForPosition(event.position().toPoint())
                pos = cursor.position()
                if self._ctrl_selection_start is None:
                    self._ctrl_selection_start = pos
                    self._ctrl_selection_end = pos
                else:
                    self._ctrl_selection_end = pos
                # 高亮显示当前累积选择范围
                self._highlight_ctrl_selection()
            else:
                # 普通点击：选中单词并立即查词
                self._ctrl_mode = False
                self._ctrl_selection_start = None
                self._ctrl_selection_end = None
                super().mousePressEvent(event)
                self._select_word_at_cursor()
                self._trigger_lookup()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._ctrl_mode and event.buttons() & Qt.MouseButton.LeftButton:
            cursor = self.cursorForPosition(event.position().toPoint())
            self._ctrl_selection_end = cursor.position()
            self._highlight_ctrl_selection()
        else:
            super().mouseMoveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Control:
            self._ctrl_mode = True
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Control and self._ctrl_mode:
            # Ctrl 松开：触发累积的多选查词
            self._ctrl_mode = False
            if self._ctrl_selection_start is not None:
                selected = self._get_ctrl_selection_text()
                if selected.strip():
                    self.word_lookup_requested.emit(selected.strip())
            self._ctrl_selection_start = None
            self._ctrl_selection_end = None
        super().keyReleaseEvent(event)

    def _select_word_at_cursor(self) -> None:
        """选中光标所在位置的单词"""
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        self.setTextCursor(cursor)

    def _trigger_lookup(self) -> None:
        """触发查词请求"""
        cursor = self.textCursor()
        selected = cursor.selectedText().strip()
        # 过滤掉标点符号
        word = re.sub(r"[^\w'-]", "", selected)
        if word:
            self.word_lookup_requested.emit(word)

    def _highlight_ctrl_selection(self) -> None:
        """高亮显示 Ctrl 多选范围"""
        if self._ctrl_selection_start is None or self._ctrl_selection_end is None:
            return
        cursor = self.textCursor()
        start = min(self._ctrl_selection_start, self._ctrl_selection_end)
        end = max(self._ctrl_selection_start, self._ctrl_selection_end)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _get_ctrl_selection_text(self) -> str:
        """获取 Ctrl 多选范围内的文本（扩展到完整单词边界）"""
        if self._ctrl_selection_start is None or self._ctrl_selection_end is None:
            return ""
        doc = self.document()
        start = min(self._ctrl_selection_start, self._ctrl_selection_end)
        end = max(self._ctrl_selection_start, self._ctrl_selection_end)

        # 扩展到单词边界
        cursor_start = QTextCursor(doc)
        cursor_start.setPosition(start)
        cursor_start.movePosition(QTextCursor.MoveOperation.StartOfWord)

        cursor_end = QTextCursor(doc)
        cursor_end.setPosition(end)
        cursor_end.movePosition(QTextCursor.MoveOperation.EndOfWord)

        cursor_start.setPosition(cursor_end.position(), QTextCursor.MoveMode.KeepAnchor)
        return cursor_start.selectedText()


class ResultPanel(QWidget):
    """
    可拖动的置顶浮窗结果面板
    显示矫正英文 + 中文翻译
    """

    word_lookup_requested = Signal(str, str)  # (selected_text, context_english)

    def __init__(self, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setObjectName("resultPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(380, 300)
        self.resize(500, 450)

        self._english_context: str = ""   # 保存矫正英文（供查词用）
        self._drag_pos: Optional[QPoint] = None

        self.setStyleSheet(PANEL_STYLE)
        self._setup_ui()
        self._setup_size_grip()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 主容器（用于圆角）
        container = QWidget(self)
        container.setObjectName("resultPanel")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        main_layout.addWidget(container)

        # ── 标题栏 ──
        title_bar = QFrame()
        title_bar.setObjectName("titleBar")
        title_bar.setFixedHeight(42)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(14, 0, 10, 0)

        icon_label = QLabel("🎮")
        icon_label.setStyleSheet("font-size: 16px;")

        title_label = QLabel("VN 翻译助手")
        title_label.setObjectName("titleLabel")

        self._status_label = QLabel("就绪")
        self._status_label.setObjectName("statusLabel")

        self._loading_label = QLabel("⟳ 翻译中...")
        self._loading_label.setObjectName("loadingLabel")
        self._loading_label.hide()

        tb_layout.addWidget(icon_label)
        tb_layout.addSpacing(6)
        tb_layout.addWidget(title_label)
        tb_layout.addStretch()
        tb_layout.addWidget(self._loading_label)
        tb_layout.addWidget(self._status_label)

        # 关闭/隐藏按钮
        hide_btn = self._make_window_btn("─", "#374151", self.hide)
        tb_layout.addSpacing(6)
        tb_layout.addWidget(hide_btn)

        container_layout.addWidget(title_bar)

        # ── 内容区 ──
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 10, 12, 10)
        content_layout.setSpacing(8)

        # 英文区域
        en_header = QHBoxLayout()
        en_label = QLabel("EN  矫正原文")
        en_label.setObjectName("sectionLabelEn")
        self._copy_en_btn = self._make_small_btn("复制", self._copy_english)
        en_header.addWidget(en_label)
        en_header.addStretch()
        en_header.addWidget(self._copy_en_btn)

        self._english_edit = ClickableTextEdit()
        self._english_edit.setFixedHeight(140)
        self._english_edit.setPlaceholderText("矫正后的英文将显示在这里...\n单击单词查询含义，Ctrl+拖拽选多词")
        self._english_edit.word_lookup_requested.connect(self._on_word_lookup)

        # 中文区域
        zh_header = QHBoxLayout()
        zh_label = QLabel("ZH  中文翻译")
        zh_label.setObjectName("sectionLabelZh")
        self._copy_zh_btn = self._make_small_btn("复制", self._copy_chinese)
        zh_header.addWidget(zh_label)
        zh_header.addStretch()
        zh_header.addWidget(self._copy_zh_btn)

        self._chinese_edit = QTextEdit()
        self._chinese_edit.setObjectName("chineseText")
        self._chinese_edit.setReadOnly(True)
        self._chinese_edit.setPlaceholderText("中文翻译将显示在这里...")
        zh_font = QFont("Microsoft YaHei", 14)
        self._chinese_edit.setFont(zh_font)

        # OCR 原文提示（可展开）
        self._ocr_label = QLabel()
        self._ocr_label.setStyleSheet(
            "color: #4b5563; font-size: 10px; "
            "padding: 2px 6px; background: #111827; border-radius: 4px;"
        )
        self._ocr_label.setWordWrap(True)
        self._ocr_label.hide()

        content_layout.addLayout(en_header)
        content_layout.addWidget(self._english_edit)
        content_layout.addLayout(zh_header)
        content_layout.addWidget(self._chinese_edit)
        content_layout.addWidget(self._ocr_label)

        container_layout.addWidget(content)

        # 使标题栏可拖动
        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move
        title_bar.mouseReleaseEvent = self._title_mouse_release

    def _setup_size_grip(self) -> None:
        """右下角调整大小控件"""
        grip = QSizeGrip(self)
        grip.setFixedSize(16, 16)
        grip.setStyleSheet("background: transparent;")

    def _make_window_btn(self, text: str, color: str, callback) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(24, 24)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {color}; color: #94a3b8;
                border-radius: 5px; font-size: 13px; border: none;
            }}
            QPushButton:hover {{ background: #4b5563; color: #e2e8f0; }}
        """)
        btn.clicked.connect(callback)
        return btn

    def _make_small_btn(self, text: str, callback) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("class", "controlBtn")
        btn.setStyleSheet("""
            QPushButton {
                background-color: #1e1e3a; color: #94a3b8;
                border: 1px solid #374151; border-radius: 5px;
                padding: 2px 8px; font-size: 10px;
            }
            QPushButton:hover {
                background-color: #2d2d5a; color: #e2e8f0;
            }
        """)
        btn.clicked.connect(callback)
        return btn

    # ─── 拖动逻辑 ────────────────────────────────────────────
    def _title_mouse_press(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _title_mouse_move(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def _title_mouse_release(self, event: QMouseEvent) -> None:
        self._drag_pos = None

    # ─── 数据更新 ────────────────────────────────────────────
    def show_loading(self) -> None:
        """显示翻译中状态"""
        self._loading_label.show()
        self._status_label.hide()
        self.show()
        self.raise_()

    def show_result(self, corrected: str, translation: str, original_ocr: str = "") -> None:
        """更新显示翻译结果"""
        self._loading_label.hide()
        self._status_label.show()

        self._english_context = corrected
        self._english_edit.setPlainText(corrected)
        self._chinese_edit.setPlainText(translation)

        if original_ocr and original_ocr != corrected:
            self._ocr_label.setText(f"OCR 原文: {original_ocr[:120]}{'...' if len(original_ocr) > 120 else ''}")
            self._ocr_label.show()
        else:
            self._ocr_label.hide()

        self._status_label.setText("翻译完成 ✓")
        self.show()
        self.raise_()

    def show_error(self, error: str) -> None:
        """显示错误信息"""
        self._loading_label.hide()
        self._status_label.show()
        self._status_label.setText(f"⚠ {error}")
        self._status_label.setStyleSheet("color: #f87171; font-size: 11px;")
        self.show()
        self.raise_()

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)
        self._status_label.setStyleSheet("color: #4b5563; font-size: 11px;")

    # ─── 查词 ────────────────────────────────────────────────
    def _on_word_lookup(self, selected_text: str) -> None:
        self.word_lookup_requested.emit(selected_text, self._english_context)

    # ─── 复制 ────────────────────────────────────────────────
    def _copy_english(self) -> None:
        QApplication.clipboard().setText(self._english_edit.toPlainText())
        self._copy_en_btn.setText("已复制!")
        QTimer.singleShot(1500, lambda: self._copy_en_btn.setText("复制"))

    def _copy_chinese(self) -> None:
        QApplication.clipboard().setText(self._chinese_edit.toPlainText())
        self._copy_zh_btn.setText("已复制!")
        QTimer.singleShot(1500, lambda: self._copy_zh_btn.setText("复制"))
