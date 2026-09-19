"""A movable, resizable word lookup window with persistent presentation settings."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizeGrip,
    QSizePolicy, QVBoxLayout, QWidget,
)

from src.utils.config_manager import ConfigManager
from src.utils import vocabulary


class WordTooltipWidget(QWidget):
    """Persistent lookup panel. Pinning keeps its location across new lookups."""

    def __init__(self, parent=None, *, config=None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("单词释义")
        self._cfg = config if config is not None else ConfigManager()
        self._pinned = bool(self._cfg.get("ui", "word_tooltip_pinned", default=False))
        self._always_on_top = bool(self._cfg.get("ui", "word_tooltip_always_on_top", default=True))
        try:
            self._font_size = max(10, min(28, int(self._cfg.get("ui", "word_tooltip_font_size", default=14))))
        except (TypeError, ValueError):
            self._font_size = 14
        self._drag_offset = None
        self._restoring = True
        self._is_error = False
        self._word = ""
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self._save_preferences)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._always_on_top)
        self._setup_ui()
        self._restore_geometry()
        self._restoring = False

    def _button(self, text: str, tooltip: str, *, checkable: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setCheckable(checkable)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(28)
        return button

    def _setup_ui(self) -> None:
        self.setStyleSheet("""
            QFrame#tooltipContainer {
                background: #1e1e2e; border: 1px solid #7c3aed; border-radius: 12px;
            }
            QLabel { background: transparent; border: none; }
            QPushButton {
                background: #303048; color: #cbd5e1; border: 1px solid #44445e;
                border-radius: 5px; padding: 2px 8px; font-size: 12px;
            }
            QPushButton:hover { background: #434363; color: #ffffff; }
            QPushButton:checked { background: #55319a; color: #ffffff; border-color: #a78bfa; }
            QPushButton:disabled { color: #66667d; }
            QScrollArea { background: transparent; border: none; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 5, 5, 5)
        self._container = QFrame(self)
        self._container.setObjectName("tooltipContainer")
        inner = QVBoxLayout(self._container)
        inner.setContentsMargins(14, 10, 14, 8)
        inner.setSpacing(9)
        outer.addWidget(self._container)

        # A dedicated drag handle keeps dragging separate from selectable text.
        self._title_bar = QWidget()
        self._title_bar.setCursor(Qt.CursorShape.SizeAllCursor)
        self._title_bar.setToolTip("拖动标题栏移动窗口；右下角拖动调整大小")
        self._title_bar.installEventFilter(self)
        top_row = QHBoxLayout(self._title_bar)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)
        title = QLabel("单词释义  ·  拖动移动")
        title.setStyleSheet("color: #a78bfa; font-size: 11px;")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        top_row.addWidget(title)
        top_row.addStretch()
        self._pin_btn = self._button("固定", "固定位置：下一次查词仍在这里显示", checkable=True)
        self._pin_btn.setChecked(self._pinned)
        self._pin_btn.toggled.connect(self._set_pinned)
        top_row.addWidget(self._pin_btn)
        self._top_btn = self._button("置顶", "保持在其他窗口上方", checkable=True)
        self._top_btn.setChecked(self._always_on_top)
        self._top_btn.toggled.connect(self._set_always_on_top)
        top_row.addWidget(self._top_btn)
        close_btn = self._button("×", "关闭查词窗口")
        close_btn.setFixedWidth(28)
        close_btn.clicked.connect(self.hide)
        top_row.addWidget(close_btn)
        inner.addWidget(self._title_bar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 6, 0)
        body_layout.setSpacing(9)
        self._word_label = QLabel()
        self._pos_label = QLabel()
        self._meaning_label = QLabel()
        self._note_label = QLabel()
        for label in (self._word_label, self._pos_label, self._meaning_label, self._note_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            body_layout.addWidget(label)
        body_layout.addStretch()
        self._pos_label.hide()
        self._note_label.hide()
        self._scroll.setWidget(body)
        inner.addWidget(self._scroll, 1)

        controls = QHBoxLayout()
        controls.setSpacing(5)
        self._fav_btn = self._button("☆ 收藏", "收藏单词", checkable=True)
        self._fav_btn.clicked.connect(self._on_favorite_clicked)
        self._fav_btn.setEnabled(False)
        controls.addWidget(self._fav_btn)
        controls.addStretch()
        self._font_down_btn = self._button("A−", "减小字体")
        self._font_down_btn.clicked.connect(lambda: self._change_font_size(-1))
        self._font_up_btn = self._button("A+", "增大字体")
        self._font_up_btn.clicked.connect(lambda: self._change_font_size(1))
        self._font_size_label = QLabel()
        self._font_size_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        controls.addWidget(self._font_down_btn)
        controls.addWidget(self._font_size_label)
        controls.addWidget(self._font_up_btn)
        self._size_grip = QSizeGrip(self)
        self._size_grip.setToolTip("拖动调整窗口大小")
        controls.addWidget(self._size_grip)
        inner.addLayout(controls)
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        self._status_label.setStyleSheet("color: #fbbf24; font-size: 11px;")
        self._status_label.hide()
        inner.addWidget(self._status_label)
        self.setMinimumSize(360, 220)
        self._apply_fonts()

    def _restore_geometry(self) -> None:
        saved = self._cfg.get("ui", "word_tooltip_geometry")
        if (isinstance(saved, (list, tuple)) and len(saved) == 4
                and all(isinstance(value, int) for value in saved)
                and saved[2] > 0 and saved[3] > 0):
            self.setGeometry(*saved)
        else:
            self.resize(440, 300)
        self._keep_on_screen(self.pos())

    def _keep_on_screen(self, pos: QPoint) -> None:
        screen = QGuiApplication.screenAt(pos) or self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        # Clamp both axes to the chosen monitor, including monitors left of x=0.
        width = min(self.width(), available.width())
        height = min(self.height(), available.height())
        self.resize(width, height)
        x = max(available.left(), min(pos.x(), available.right() - self.width() + 1))
        y = max(available.top(), min(pos.y(), available.bottom() - self.height() + 1))
        self.move(x, y)

    def _show_at(self, pos: QPoint | None) -> None:
        if pos is not None and not self._pinned:
            self._keep_on_screen(pos)
        else:
            self._keep_on_screen(self.pos())
        self.show()
        self.raise_()

    def show_result(self, data: dict, pos: QPoint | None = None) -> None:
        self._word = str(data.get("word") or "").strip()
        self._word_label.setText(self._word)
        self._meaning_label.setText(str(data.get("meaning") or ""))
        for label, key in ((self._pos_label, "part_of_speech"), (self._note_label, "note")):
            text = str(data.get(key) or "")
            label.setText(text)
            label.setVisible(bool(text))
        self._is_error = False
        self._status_label.hide()
        self._apply_fonts()
        self._refresh_favorite()
        self._scroll.verticalScrollBar().setValue(0)
        self._show_at(pos)

    def show_loading(self, word: str, pos: QPoint | None = None) -> None:
        self._word = word.strip()
        self._word_label.setText(self._word)
        self._meaning_label.setText("查询中…")
        self._pos_label.hide()
        self._note_label.hide()
        self._status_label.hide()
        self._is_error = False
        self._apply_fonts()
        self._fav_btn.setEnabled(False)
        self._fav_btn.setChecked(False)
        self._fav_btn.setText("☆ 收藏")
        self._scroll.verticalScrollBar().setValue(0)
        self._show_at(pos)

    def show_error(self, error: str) -> None:
        self._meaning_label.setText(f"⚠ {error}")
        self._is_error = True
        self._pos_label.hide()
        self._note_label.hide()
        self._fav_btn.setEnabled(False)
        self._apply_fonts()

    def _set_favorite_state(self, saved: bool) -> None:
        self._fav_btn.setChecked(saved)
        self._fav_btn.setText("★ 已收藏" if saved else "☆ 收藏")
        self._fav_btn.setToolTip("取消收藏" if saved else "收藏单词")
        self._fav_btn.setAccessibleName(self._fav_btn.toolTip())

    def _refresh_favorite(self) -> None:
        try:
            saved = vocabulary.is_favorite(self._word)
        except (OSError, UnicodeError) as exc:
            self._status_label.setText(f"无法读取单词本：{exc}")
            self._status_label.show()
            self._fav_btn.setEnabled(False)
            return
        self._set_favorite_state(saved)
        self._fav_btn.setEnabled(bool(self._word))

    def _on_favorite_clicked(self) -> None:
        if not self._word:
            return
        try:
            self._set_favorite_state(vocabulary.toggle_word(self._word))
            self._status_label.hide()
        except (OSError, UnicodeError) as exc:
            self._refresh_favorite()
            self._status_label.setText(f"保存单词本失败：{exc}")
            self._status_label.show()

    def _set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned
        self._schedule_save()

    def _set_always_on_top(self, enabled: bool) -> None:
        self._always_on_top = enabled
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if visible:
            self.show()
        self._schedule_save()

    def _apply_fonts(self) -> None:
        size = self._font_size
        self._word_label.setStyleSheet(f"color: #c084fc; font-size: {size + 3}px; font-weight: bold;")
        self._pos_label.setStyleSheet(f"color: #a5b4fc; font-size: {max(10, size - 2)}px;")
        color = "#f87171" if self._is_error else "#e2e8f0"
        self._meaning_label.setStyleSheet(f"color: {color}; font-size: {size}px;")
        self._note_label.setStyleSheet(f"color: #94a3b8; font-size: {max(10, size - 2)}px;")
        self._font_size_label.setText(str(size))
        self._font_down_btn.setEnabled(size > 10)
        self._font_up_btn.setEnabled(size < 28)

    def _change_font_size(self, delta: int) -> None:
        self._font_size = max(10, min(28, self._font_size + delta))
        self._apply_fonts()
        self._schedule_save()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._title_bar:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._drag_offset is not None:
                self._drag_offset = None
                self._keep_on_screen(self.pos())
                self._schedule_save()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def _schedule_save(self) -> None:
        if not self._restoring:
            self._save_timer.start()

    def _save_preferences(self) -> None:
        geometry = self.geometry()
        for key, value in (
            ("word_tooltip_geometry", [geometry.x(), geometry.y(), geometry.width(), geometry.height()]),
            ("word_tooltip_font_size", self._font_size),
            ("word_tooltip_pinned", self._pinned),
            ("word_tooltip_always_on_top", self._always_on_top),
        ):
            self._cfg.set("ui", key, value)
        self._cfg.save()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._schedule_save()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_save()

    def hideEvent(self, event) -> None:
        if not self._restoring:
            self._save_timer.stop()
            self._save_preferences()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._save_timer.stop()
        self._save_preferences()
        super().closeEvent(event)
