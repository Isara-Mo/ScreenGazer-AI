"""
单词释义悬浮弹窗
Word Tooltip - floating popup showing word meaning in context
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QFont, QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame,
)

# ─── 样式常量 ───────────────────────────────────────────────
TOOLTIP_BG = "#1e1e2e"
TOOLTIP_BORDER = "#7c3aed"
WORD_COLOR = "#c084fc"
POS_COLOR = "#94a3b8"
MEANING_COLOR = "#e2e8f0"
NOTE_COLOR = "#64748b"
CLOSE_BG = "#374151"
CLOSE_HOVER = "#4b5563"


class WordTooltipWidget(QWidget):
    """
    自定义圆角浮窗，显示单词释义
    点击外部区域自动关闭
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._setup_ui()
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self.hide)

    def _setup_ui(self) -> None:
        # 外层容器（带内边距，留出阴影空间）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        # 主容器
        self._container = QFrame(self)
        self._container.setObjectName("tooltipContainer")
        self._container.setStyleSheet(f"""
            QFrame#tooltipContainer {{
                background-color: {TOOLTIP_BG};
                border: 1.5px solid {TOOLTIP_BORDER};
                border-radius: 12px;
            }}
        """)

        inner = QVBoxLayout(self._container)
        inner.setContentsMargins(16, 12, 16, 14)
        inner.setSpacing(6)

        # ── 顶部行: 单词 + 词性 + 关闭按钮 ──
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._word_label = QLabel()
        self._word_label.setStyleSheet(f"color: {WORD_COLOR}; font-size: 15px; font-weight: bold;")

        self._pos_label = QLabel()
        self._pos_label.setStyleSheet(
            f"color: {POS_COLOR}; font-size: 11px; "
            f"background: #312e81; border-radius: 4px; padding: 1px 6px;"
        )
        self._pos_label.hide()

        top_row.addWidget(self._word_label)
        top_row.addWidget(self._pos_label)
        top_row.addStretch()

        # 关闭按钮
        close_btn = QPushButton("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {CLOSE_BG}; color: #94a3b8;
                border-radius: 4px; font-size: 14px; border: none;
            }}
            QPushButton:hover {{
                background: {CLOSE_HOVER}; color: #e2e8f0;
            }}
        """)
        close_btn.clicked.connect(self.hide)
        top_row.addWidget(close_btn)

        # ── 分隔线 ──
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: #374151; border: none; border-top: 1px solid #374151;")

        # ── 含义 ──
        self._meaning_label = QLabel()
        self._meaning_label.setStyleSheet(f"color: {MEANING_COLOR}; font-size: 13px; line-height: 1.6;")
        self._meaning_label.setWordWrap(True)

        # ── 补充说明 ──
        self._note_label = QLabel()
        self._note_label.setStyleSheet(
            f"color: {NOTE_COLOR}; font-size: 11px; font-style: italic;"
        )
        self._note_label.setWordWrap(True)
        self._note_label.hide()

        inner.addLayout(top_row)
        inner.addWidget(line)
        inner.addWidget(self._meaning_label)
        inner.addWidget(self._note_label)

        outer.addWidget(self._container)
        self.setMinimumWidth(320)
        self.setMaximumWidth(500)

    def show_result(self, data: dict, pos: QPoint | None = None) -> None:
        """
        显示查词结果
        :param data: word, meaning, part_of_speech, note
        :param pos: 显示位置（若 None 则在当前位置显示）
        """
        word = data.get("word", "")
        meaning = data.get("meaning", "")
        pos_str = data.get("part_of_speech", "")
        note = data.get("note", "")

        self._word_label.setText(word)
        self._meaning_label.setText(meaning)

        if pos_str:
            self._pos_label.setText(pos_str)
            self._pos_label.show()
        else:
            self._pos_label.hide()

        if note:
            self._note_label.setText(note)
            self._note_label.show()
        else:
            self._note_label.hide()

        self.adjustSize()

        if pos:
            # 确保弹窗不超出屏幕
            from PySide6.QtGui import QGuiApplication
            screen = QGuiApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                x = min(pos.x(), geo.right() - self.width() - 10)
                y = min(pos.y(), geo.bottom() - self.height() - 10)
                self.move(max(0, x), max(0, y))

        self.show()
        self.raise_()

    def show_loading(self, word: str) -> None:
        """显示加载状态"""
        self._word_label.setText(word)
        self._meaning_label.setText("查询中...")
        self._pos_label.hide()
        self._note_label.hide()
        self.adjustSize()
        self.show()
        self.raise_()

    def show_error(self, error: str) -> None:
        """显示错误信息"""
        self._meaning_label.setText(f"⚠ {error}")
        self._meaning_label.setStyleSheet("color: #f87171; font-size: 12px;")
        self.adjustSize()

    def paintEvent(self, event) -> None:
        """透明背景支持（用于圆角阴影效果）"""
        super().paintEvent(event)
