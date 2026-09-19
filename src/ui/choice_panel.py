"""Read-only bilingual reply choices, separate from the NPC subtitle panels."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QHBoxLayout, QWidget, QSizeGrip

from src.ui.result_panel import FloatingSubPanel


class ReplyChoicesPanel(FloatingSubPanel):
    def __init__(self, parent=None):
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        default = QRect(area.left() + 24, area.top() + area.height() // 4,
                        min(460, area.width() - 48), min(360, area.height() - 80))
        super().__init__("回复选项", "panel_geometry_choices", default, parent)
        self.setWindowTitle("VN 翻译助手 · 回复选项")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMinimumSize(320, 180)
        self._signature = ()
        self._dismissed_signature = None
        self._font_size = max(10, min(24, self._cfg.get("ui", "choice_font_size", default=14)))
        self._cards = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("choiceContainer")
        frame.setStyleSheet(
            "QFrame#choiceContainer {background:#101524; border:1px solid #394360; border-radius:12px;}"
            "QLabel {border:none; background:transparent;}"
        )
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 14)
        title_bar = QFrame()
        row = QHBoxLayout(title_bar)
        row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("回复选项")
        title.setStyleSheet("color:#c4b5fd; font-size:15px; font-weight:bold;")
        row.addWidget(title)
        row.addStretch()
        for caption, tooltip, callback in (
            ("A-", "缩小选项字号", lambda: self._change_font(-1)),
            ("A+", "放大选项字号", lambda: self._change_font(1)),
            ("─", "隐藏这一组选项；可用“显示全部浮窗”恢复", self.dismiss),
        ):
            button = self._make_window_btn(caption, "#242d44", callback)
            button.setToolTip(tooltip)
            row.addWidget(button)
        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move
        title_bar.mouseReleaseEvent = self._title_mouse_release
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title_bar)
        hint = QLabel("编号按游戏中从上到下对应，请在游戏内选择")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#94a3b8; font-size:11px;")
        layout.addWidget(hint)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea {border:none; background:transparent;}")
        self._body = QWidget()
        self._body.setStyleSheet("background:transparent;")
        self._rows = QVBoxLayout(self._body)
        self._rows.setContentsMargins(0, 4, 0, 0)
        self._rows.setSpacing(10)
        self._rows.addStretch()
        self._scroll.setWidget(self._body)
        layout.addWidget(self._scroll)
        self._setup_size_grip()
        self._grip = self.findChild(QSizeGrip)
        self._position_grip()

    def _position_grip(self):
        grip = getattr(self, "_grip", None)
        if grip:
            grip.move(self.width() - grip.width() - 3, self.height() - grip.height() - 3)
            grip.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_grip()

    @property
    def has_choices(self):
        return bool(self._signature)

    def _remove_cards(self):
        for card, _, _ in self._cards:
            self._rows.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

    def show_choices(self, choices):
        if not choices:
            self.clear_choices()
            return
        signature = tuple((c.index, c.original_ocr, c.corrected, c.translation) for c in choices)
        if signature != self._signature:
            self._signature = signature
            self._dismissed_signature = None
            self._remove_cards()
            for choice in choices:
                card = QFrame()
                card.setStyleSheet("QFrame {background:#192238; border:1px solid #303e59; border-radius:8px;}")
                content = QVBoxLayout(card)
                content.setContentsMargins(12, 10, 12, 10)
                content.setSpacing(7)
                chinese = QLabel(f"{choice.index}.  {choice.translation or '暂未取得译文'}")
                english = QLabel(choice.corrected or choice.original_ocr)
                for label in (chinese, english):
                    label.setTextFormat(Qt.TextFormat.PlainText)
                    label.setWordWrap(True)
                    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                    content.addWidget(label)
                self._rows.insertWidget(len(self._cards), card)
                self._cards.append((card, chinese, english))
            self._apply_fonts()
            self._scroll.verticalScrollBar().setValue(0)
        if self._signature != self._dismissed_signature and not self.isVisible():
            self.show()
            self.raise_()

    def dismiss(self):
        self._dismissed_signature = self._signature
        self.hide()

    def suspend(self):
        """Hide a stale scene without treating it as the user's dismissal."""
        self.hide()

    def reveal(self):
        if self.has_choices:
            self._dismissed_signature = None
            self.show()
            self.raise_()

    def clear_choices(self):
        self.hide()
        self._remove_cards()
        self._signature = ()
        self._dismissed_signature = None

    def _change_font(self, delta):
        self._font_size = max(10, min(24, self._font_size + delta))
        self._apply_fonts()
        self._cfg.set("ui", "choice_font_size", self._font_size)
        self._cfg.save()

    def _apply_fonts(self):
        for _, chinese, english in self._cards:
            chinese.setStyleSheet(f"color:#d1fae5; font-size:{self._font_size}pt; font-weight:600; border:none;")
            english.setStyleSheet(f"color:#bac7db; font-size:{max(9, self._font_size - 2)}pt; border:none;")
