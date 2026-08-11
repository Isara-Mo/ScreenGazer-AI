"""
结果显示面板模块 - 支持合并单窗口与独立拆分双浮窗模式
Result Panel - floating windows for English original + Chinese translation.
Supports word lookup, split mode (drag Chinese translation to screen bottom as long subtitle bar),
font scaling, and geometry persistence.
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
    QGuiApplication,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QFrame, QSizeGrip,
    QScrollArea, QApplication, QToolButton,
)

from src.utils.config_manager import ConfigManager


# ─── 样式表定义 ───────────────────────────────────────────────
COMMON_PANEL_STYLE = """
QWidget.floatingPanel {
    background-color: #0f0f1a;
    border-radius: 12px;
    border: 1px solid #2d2d4a;
}

/* 标题栏 */
QFrame.titleBar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #1a1a3e, stop:1 #0f0f1a);
    border-radius: 12px 12px 0 0;
    border-bottom: 1px solid #2d2d4a;
}
QFrame.titleBarZh {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0f2520, stop:1 #0a1628);
    border-radius: 12px 12px 0 0;
    border-bottom: 1px solid #1e3a2a;
}
QLabel.titleLabel {
    color: #a78bfa; font-size: 12px; font-weight: bold;
}
QLabel.titleLabelZh {
    color: #34d399; font-size: 12px; font-weight: bold;
}
QLabel.statusLabel {
    color: #4b5563; font-size: 11px;
}

/* 英文文本编辑框 */
QTextEdit#englishText {
    background-color: #141428;
    color: #e2e8f0;
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: #4c1d95;
    selection-color: #e2e8f0;
    line-height: 1.6;
}

/* 中文文本框 */
QTextEdit#chineseText {
    background-color: #0a1628;
    color: #a7f3d0;
    border: 1px solid #1e3a2a;
    border-radius: 8px;
    padding: 8px 10px;
    line-height: 1.7;
}

/* 控制按钮 */
QPushButton.controlBtn {
    background-color: #1e1e3a;
    color: #94a3b8;
    border: 1px solid #374151;
    border-radius: 5px;
    padding: 2px 8px;
    font-size: 10px;
}
QPushButton.controlBtn:hover {
    background-color: #2d2d5a; color: #e2e8f0; border-color: #6366f1;
}

/* 加载动画标签 */
QLabel.loadingLabel {
    color: #6366f1; font-size: 12px;
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
            ctrl_held = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if ctrl_held:
                self._ctrl_mode = True
                cursor = self.cursorForPosition(event.position().toPoint())
                pos = cursor.position()
                if self._ctrl_selection_start is None:
                    self._ctrl_selection_start = pos
                    self._ctrl_selection_end = pos
                else:
                    self._ctrl_selection_end = pos
                self._highlight_ctrl_selection()
            else:
                self._ctrl_mode = False
                self._ctrl_selection_start = None
                self._ctrl_selection_end = None
                super().mousePressEvent(event)
                self._select_word_at_cursor()
                self._trigger_lookup()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._ctrl_mode and bool(event.buttons() & Qt.MouseButton.LeftButton):
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
        word = re.sub(r"[^\w'-]", "", selected)
        if word:
            self.word_lookup_requested.emit(word)

    def _highlight_ctrl_selection(self) -> None:
        if self._ctrl_selection_start is None or self._ctrl_selection_end is None:
            return
        cursor = self.textCursor()
        start = min(self._ctrl_selection_start, self._ctrl_selection_end)
        end = max(self._ctrl_selection_start, self._ctrl_selection_end)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _get_ctrl_selection_text(self) -> str:
        if self._ctrl_selection_start is None or self._ctrl_selection_end is None:
            return ""
        doc = self.document()
        start = min(self._ctrl_selection_start, self._ctrl_selection_end)
        end = max(self._ctrl_selection_start, self._ctrl_selection_end)

        cursor_start = QTextCursor(doc)
        cursor_start.setPosition(start)
        cursor_start.movePosition(QTextCursor.MoveOperation.StartOfWord)

        cursor_end = QTextCursor(doc)
        cursor_end.setPosition(end)
        cursor_end.movePosition(QTextCursor.MoveOperation.EndOfWord)

        cursor_start.setPosition(cursor_end.position(), QTextCursor.MoveMode.KeepAnchor)
        return cursor_start.selectedText()


# ─── 独立浮窗基类 ─────────────────────────────────────────────
class FloatingSubPanel(QWidget):
    """
    独立置顶浮窗基类 (英文面板/中文面板)
    支持无边框圆角、顶部拖拽栏、窗口大小手柄、字号调整与坐标记忆
    """
    mode_toggle_requested = Signal()

    def __init__(self, title: str, config_geom_key: str, default_rect: QRect, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setProperty("class", "floatingPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(COMMON_PANEL_STYLE)

        self._title_text = title
        self._config_geom_key = config_geom_key
        self._drag_pos: Optional[QPoint] = None
        self._cfg = ConfigManager()

        # 加载尺寸几何数据
        saved_geom = self._cfg.get("ui", self._config_geom_key)
        if saved_geom and len(saved_geom) == 4:
            self.setGeometry(saved_geom[0], saved_geom[1], saved_geom[2], saved_geom[3])
        else:
            self.setGeometry(default_rect)

    def _setup_size_grip(self) -> None:
        """右下角调整大小控件"""
        grip = QSizeGrip(self)
        grip.setFixedSize(16, 16)
        grip.setStyleSheet("""
            QSizeGrip {
                background: transparent;
                border-right: 2px solid #4b5563;
                border-bottom: 2px solid #4b5563;
                border-radius: 2px;
            }
        """)

    def _make_window_btn(self, text: str, color: str, callback) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(22, 22)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {color}; color: #94a3b8;
                border-radius: 4px; font-size: 11px; border: none;
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
                border: 1px solid #374151; border-radius: 4px;
                padding: 2px 6px; font-size: 10px;
            }
            QPushButton:hover {
                background-color: #2d2d5a; color: #e2e8f0;
            }
        """)
        btn.clicked.connect(callback)
        return btn

    # ── 拖拽移动与几何记录 ──
    def _title_mouse_press(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _title_mouse_move(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def _title_mouse_release(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        self._save_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._save_geometry()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._save_geometry()

    def _save_geometry(self) -> None:
        """持久化当前浮窗位置和尺寸"""
        rect = [self.x(), self.y(), self.width(), self.height()]
        self._cfg.set("ui", self._config_geom_key, rect)
        self._cfg.save()


# ─── 中文翻译独立浮窗 (字幕条风格) ───────────────────────────
class ChinesePanel(FloatingSubPanel):
    """
    中文翻译独立浮窗 (支持拖至屏幕底部拉成长条字幕框)
    """

    def __init__(self, parent=None) -> None:
        # 默认屏幕底部居中长条 geometry
        screen = QGuiApplication.primaryScreen()
        screen_size = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        def_w, def_h = min(850, screen_size.width() - 100), 130
        def_x = (screen_size.width() - def_w) // 2
        def_y = screen_size.height() - def_h - 40
        default_rect = QRect(def_x, def_y, def_w, def_h)

        super().__init__("ZH 中文翻译", "panel_geometry_zh", default_rect, parent)
        self.setObjectName("chinesePanel")
        self.setMinimumSize(300, 80)

        self._font_size_zh: int = self._cfg.get("ui", "font_size_zh", default=14)
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        container = QWidget(self)
        container.setStyleSheet("""
            QWidget {
                background-color: #08101d;
                border-radius: 12px;
                border: 1px solid #1e3a2a;
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        main_layout.addWidget(container)

        # 标题栏
        title_bar = QFrame()
        title_bar.setProperty("class", "titleBarZh")
        title_bar.setFixedHeight(34)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(10, 0, 8, 0)

        icon_label = QLabel("🇨🇳")
        icon_label.setStyleSheet("font-size: 13px;")

        title_label = QLabel("ZH 中文翻译")
        title_label.setProperty("class", "titleLabelZh")

        self._status_label = QLabel("就绪")
        self._status_label.setProperty("class", "statusLabel")

        self._loading_label = QLabel("⟳ 翻译中...")
        self._loading_label.setProperty("class", "loadingLabel")
        self._loading_label.hide()

        tb_layout.addWidget(icon_label)
        tb_layout.addSpacing(4)
        tb_layout.addWidget(title_label)
        tb_layout.addStretch()
        tb_layout.addWidget(self._loading_label)
        tb_layout.addWidget(self._status_label)

        # 复制按钮
        self._copy_btn = self._make_small_btn("复制", self._copy_chinese)
        tb_layout.addSpacing(6)
        tb_layout.addWidget(self._copy_btn)

        # 字体调节
        font_dec_btn = self._make_window_btn("A-", "#1e3a2a", self._decrease_font)
        font_inc_btn = self._make_window_btn("A+", "#1e3a2a", self._increase_font)
        font_dec_btn.setToolTip("缩小字体")
        font_inc_btn.setToolTip("放大字体")
        tb_layout.addSpacing(4)
        tb_layout.addWidget(font_dec_btn)
        tb_layout.addWidget(font_inc_btn)

        # 模式切换按钮
        mode_btn = self._make_window_btn("📦", "#1e3a2a", self.mode_toggle_requested.emit)
        mode_btn.setToolTip("切换为合并单窗口模式")
        tb_layout.addSpacing(4)
        tb_layout.addWidget(mode_btn)

        # 隐藏按钮
        hide_btn = self._make_window_btn("─", "#1e3a2a", self.hide)
        tb_layout.addSpacing(4)
        tb_layout.addWidget(hide_btn)

        container_layout.addWidget(title_bar)

        # 内容区 (长条文本)
        content_frame = QFrame()
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(8, 6, 8, 6)
        content_layout.setSpacing(4)

        self._chinese_edit = QTextEdit()
        self._chinese_edit.setObjectName("chineseText")
        self._chinese_edit.setReadOnly(True)
        self._chinese_edit.setPlaceholderText("中文翻译将显示在这里 (拖拽底部手柄可调整长条宽度)...")

        # OCR 原文备选提示
        self._ocr_label = QLabel()
        self._ocr_label.setStyleSheet(
            "color: #4b5563; font-size: 10px; "
            "padding: 2px 6px; background: #060d17; border-radius: 4px;"
        )
        self._ocr_label.setWordWrap(True)
        self._ocr_label.hide()

        content_layout.addWidget(self._chinese_edit, 1)
        container_layout.addWidget(content_frame)

        self._apply_font_size()

        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move
        title_bar.mouseReleaseEvent = self._title_mouse_release
        self._setup_size_grip()

    def _increase_font(self) -> None:
        self._font_size_zh = min(self._font_size_zh + 1, 32)
        self._apply_font_size()

    def _decrease_font(self) -> None:
        self._font_size_zh = max(self._font_size_zh - 1, 9)
        self._apply_font_size()

    def _apply_font_size(self) -> None:
        zh_font = QFont("Microsoft YaHei", self._font_size_zh)
        self._chinese_edit.setFont(zh_font)
        self._cfg.set("ui", "font_size_zh", self._font_size_zh)
        self._cfg.save()

    def show_loading(self) -> None:
        self._loading_label.show()
        self._status_label.hide()
        self.show()
        self.raise_()

    def show_result(self, translation: str) -> None:
        self._loading_label.hide()
        self._status_label.show()
        self._chinese_edit.setPlainText(translation)
        self._status_label.setText("翻译完成 ✓")
        self.show()
        self.raise_()

    def show_error(self, error: str) -> None:
        self._loading_label.hide()
        self._status_label.show()
        self._status_label.setText(f"⚠ {error}")
        self.show()
        self.raise_()

    def _copy_chinese(self) -> None:
        QApplication.clipboard().setText(self._chinese_edit.toPlainText())
        self._copy_btn.setText("已复制!")
        QTimer.singleShot(1500, lambda: self._copy_btn.setText("复制"))


# ─── 英文矫正独立浮窗 ─────────────────────────────────────────
class EnglishPanel(FloatingSubPanel):
    """
    英文矫正独立浮窗 (支持点击查词与选词)
    """

    word_lookup_requested = Signal(str, str)  # (selected_text, context_english)

    def __init__(self, parent=None) -> None:
        screen = QGuiApplication.primaryScreen()
        screen_size = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        def_w, def_h = min(600, screen_size.width() - 100), 160
        def_x = (screen_size.width() - def_w) // 2
        def_y = max(40, screen_size.height() // 6)
        default_rect = QRect(def_x, def_y, def_w, def_h)

        super().__init__("EN 矫正原文", "panel_geometry_en", default_rect, parent)
        self.setObjectName("englishPanel")
        self.setMinimumSize(300, 80)

        self._english_context: str = ""
        self._font_size_en: int = self._cfg.get("ui", "font_size_en", default=13)
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        container = QWidget(self)
        container.setStyleSheet("""
            QWidget {
                background-color: #0f0f1a;
                border-radius: 12px;
                border: 1px solid #2d2d4a;
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        main_layout.addWidget(container)

        # 标题栏
        title_bar = QFrame()
        title_bar.setProperty("class", "titleBar")
        title_bar.setFixedHeight(34)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(10, 0, 8, 0)

        icon_label = QLabel("🔤")
        icon_label.setStyleSheet("font-size: 13px;")

        title_label = QLabel("EN 矫正原文")
        title_label.setProperty("class", "titleLabel")

        self._status_label = QLabel("就绪")
        self._status_label.setProperty("class", "statusLabel")

        self._loading_label = QLabel("⟳ 翻译中...")
        self._loading_label.setProperty("class", "loadingLabel")
        self._loading_label.hide()

        tb_layout.addWidget(icon_label)
        tb_layout.addSpacing(4)
        tb_layout.addWidget(title_label)
        tb_layout.addStretch()
        tb_layout.addWidget(self._loading_label)
        tb_layout.addWidget(self._status_label)

        # 复制按钮
        self._copy_btn = self._make_small_btn("复制", self._copy_english)
        tb_layout.addSpacing(6)
        tb_layout.addWidget(self._copy_btn)

        # OCR 原文显隐切换按钮 (默认隐藏，存在与矫正词不同时可用)
        self._ocr_btn = self._make_small_btn("📄 OCR原文", self._toggle_ocr_visibility)
        self._ocr_btn.setToolTip("点击展开/收起 OCR 原始未矫正的文本")
        self._ocr_btn.hide()
        tb_layout.addSpacing(4)
        tb_layout.addWidget(self._ocr_btn)

        # 字体调节
        font_dec_btn = self._make_window_btn("A-", "#1e1e3a", self._decrease_font)
        font_inc_btn = self._make_window_btn("A+", "#1e1e3a", self._increase_font)
        font_dec_btn.setToolTip("缩小字体")
        font_inc_btn.setToolTip("放大字体")
        tb_layout.addSpacing(4)
        tb_layout.addWidget(font_dec_btn)
        tb_layout.addWidget(font_inc_btn)

        # 模式切换按钮
        mode_btn = self._make_window_btn("📦", "#1e1e3a", self.mode_toggle_requested.emit)
        mode_btn.setToolTip("切换为合并单窗口模式")
        tb_layout.addSpacing(4)
        tb_layout.addWidget(mode_btn)

        # 隐藏按钮
        hide_btn = self._make_window_btn("─", "#1e1e3a", self.hide)
        tb_layout.addSpacing(4)
        tb_layout.addWidget(hide_btn)

        container_layout.addWidget(title_bar)

        # 内容区
        content_frame = QFrame()
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(8, 6, 8, 6)

        self._english_edit = ClickableTextEdit()
        self._english_edit.setPlaceholderText("矫正后的英文将显示在这里 (单击单词查词，Ctrl+拖拽选多词)...")
        self._english_edit.word_lookup_requested.connect(self._on_word_lookup)

        # OCR 原文展收区域 (初始隐藏)
        self._ocr_label = QLabel()
        self._ocr_label.setStyleSheet(
            "color: #6b7280; font-size: 10px; "
            "padding: 4px 8px; background: #0b0b14; border-radius: 4px; border: 1px dashed #2d2d4a;"
        )
        self._ocr_label.setWordWrap(True)
        self._ocr_label.hide()

        content_layout.addWidget(self._english_edit, 1)
        content_layout.addWidget(self._ocr_label)
        container_layout.addWidget(content_frame)

        self._apply_font_size()

        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move
        title_bar.mouseReleaseEvent = self._title_mouse_release
        self._setup_size_grip()

    def _toggle_ocr_visibility(self) -> None:
        """切换 OCR 原始文本展收状态"""
        if self._ocr_label.isVisible():
            self._ocr_label.hide()
            self._ocr_btn.setText("📄 OCR原文")
        else:
            self._ocr_label.show()
            self._ocr_btn.setText("🙈 隐藏OCR")

    def _increase_font(self) -> None:
        self._font_size_en = min(self._font_size_en + 1, 32)
        self._apply_font_size()

    def _decrease_font(self) -> None:
        self._font_size_en = max(self._font_size_en - 1, 9)
        self._apply_font_size()

    def _apply_font_size(self) -> None:
        en_font = QFont("Segoe UI", self._font_size_en)
        self._english_edit.setFont(en_font)
        self._cfg.set("ui", "font_size_en", self._font_size_en)
        self._cfg.save()

    def show_loading(self) -> None:
        self._loading_label.show()
        self._status_label.hide()
        self.show()
        self.raise_()

    def show_result(self, corrected: str, original_ocr: str = "") -> None:
        self._loading_label.hide()
        self._status_label.show()
        self._english_context = corrected
        self._english_edit.setPlainText(corrected)

        if original_ocr and original_ocr.strip() != corrected.strip():
            self._ocr_label.setText(f"🔍 OCR 原始文本:\n{original_ocr}")
            self._ocr_btn.show()
        else:
            self._ocr_label.hide()
            self._ocr_btn.hide()
            self._ocr_btn.setText("📄 OCR原文")

        self._status_label.setText("就绪")
        self.show()
        self.raise_()

    def show_error(self, error: str) -> None:
        self._loading_label.hide()
        self._status_label.show()
        self._status_label.setText(f"⚠ {error}")
        self.show()
        self.raise_()

    def _on_word_lookup(self, selected_text: str) -> None:
        self.word_lookup_requested.emit(selected_text, self._english_context)

    def _copy_english(self) -> None:
        QApplication.clipboard().setText(self._english_edit.toPlainText())
        self._copy_btn.setText("已复制!")
        QTimer.singleShot(1500, lambda: self._copy_btn.setText("复制"))


# ─── 传统合并单窗口面板 ───────────────────────────────────────
class CombinedPanel(FloatingSubPanel):
    """
    合并型单窗口浮窗面板 (包含 EN 原文与 ZH 翻译上下排列)
    """

    word_lookup_requested = Signal(str, str)

    def __init__(self, parent=None) -> None:
        default_rect = QRect(200, 200, 500, 450)
        super().__init__("VN 翻译助手", "panel_geometry", default_rect, parent)
        self.setObjectName("combinedPanel")
        self.setMinimumSize(380, 260)

        self._english_context: str = ""
        self._font_size_en: int = self._cfg.get("ui", "font_size_en", default=13)
        self._font_size_zh: int = self._cfg.get("ui", "font_size_zh", default=14)
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        container = QWidget(self)
        container.setStyleSheet("""
            QWidget {
                background-color: #0f0f1a;
                border-radius: 14px;
                border: 1px solid #2d2d4a;
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        main_layout.addWidget(container)

        # 标题栏
        title_bar = QFrame()
        title_bar.setProperty("class", "titleBar")
        title_bar.setFixedHeight(42)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(14, 0, 10, 0)

        icon_label = QLabel("🎮")
        icon_label.setStyleSheet("font-size: 16px;")

        title_label = QLabel("VN 翻译助手 (合并面板)")
        title_label.setProperty("class", "titleLabel")

        self._status_label = QLabel("就绪")
        self._status_label.setProperty("class", "statusLabel")

        self._loading_label = QLabel("⟳ 翻译中...")
        self._loading_label.setProperty("class", "loadingLabel")
        self._loading_label.hide()

        tb_layout.addWidget(icon_label)
        tb_layout.addSpacing(6)
        tb_layout.addWidget(title_label)
        tb_layout.addStretch()
        tb_layout.addWidget(self._loading_label)
        tb_layout.addWidget(self._status_label)

        # 字体调节
        font_dec_btn = self._make_window_btn("A-", "#1e1e3a", self._decrease_font)
        font_inc_btn = self._make_window_btn("A+", "#1e1e3a", self._increase_font)
        font_dec_btn.setToolTip("缩小字体")
        font_inc_btn.setToolTip("放大字体")
        tb_layout.addSpacing(4)
        tb_layout.addWidget(font_dec_btn)
        tb_layout.addWidget(font_inc_btn)

        # 模式切换按钮 (拆分为独立双浮窗)
        split_btn = self._make_window_btn("🧱", "#1e1e3a", self.mode_toggle_requested.emit)
        split_btn.setToolTip("拆分为中英文独立双浮窗 (长条字幕模式)")
        tb_layout.addSpacing(4)
        tb_layout.addWidget(split_btn)

        # 隐藏按钮
        hide_btn = self._make_window_btn("─", "#1e1e3a", self.hide)
        tb_layout.addSpacing(4)
        tb_layout.addWidget(hide_btn)

        container_layout.addWidget(title_bar)

        # 内容区
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 10, 12, 10)
        content_layout.setSpacing(8)

        # 英文区域
        en_header = QHBoxLayout()
        en_label = QLabel("EN  矫正原文")
        en_label.setStyleSheet("color: #60a5fa; font-size: 11px; font-weight: bold;")
        self._copy_en_btn = self._make_small_btn("复制", self._copy_english)
        self._ocr_btn = self._make_small_btn("📄 OCR原文", self._toggle_ocr_visibility)
        self._ocr_btn.hide()
        en_header.addWidget(en_label)
        en_header.addStretch()
        en_header.addWidget(self._ocr_btn)
        en_header.addSpacing(4)
        en_header.addWidget(self._copy_en_btn)

        self._english_edit = ClickableTextEdit()
        self._english_edit.setMinimumHeight(70)
        self._english_edit.setPlaceholderText("矫正后的英文将显示在这里...")
        self._english_edit.word_lookup_requested.connect(self._on_word_lookup)

        # OCR 原文 (初始折叠隐藏)
        self._ocr_label = QLabel()
        self._ocr_label.setStyleSheet(
            "color: #6b7280; font-size: 10px; "
            "padding: 4px 8px; background: #0b0b14; border-radius: 4px; border: 1px dashed #2d2d4a;"
        )
        self._ocr_label.setWordWrap(True)
        self._ocr_label.hide()

        # 中文区域
        zh_header = QHBoxLayout()
        zh_label = QLabel("ZH  中文翻译")
        zh_label.setStyleSheet("color: #34d399; font-size: 11px; font-weight: bold;")
        self._copy_zh_btn = self._make_small_btn("复制", self._copy_chinese)
        zh_header.addWidget(zh_label)
        zh_header.addStretch()
        zh_header.addWidget(self._copy_zh_btn)

        self._chinese_edit = QTextEdit()
        self._chinese_edit.setObjectName("chineseText")
        self._chinese_edit.setReadOnly(True)
        self._chinese_edit.setMinimumHeight(70)
        self._chinese_edit.setPlaceholderText("中文翻译将显示在这里...")

        content_layout.addLayout(en_header)
        content_layout.addWidget(self._english_edit, 1)
        content_layout.addWidget(self._ocr_label)
        content_layout.addLayout(zh_header)
        content_layout.addWidget(self._chinese_edit, 1)

        self._apply_font_sizes()
        container_layout.addWidget(content)

        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move
        title_bar.mouseReleaseEvent = self._title_mouse_release
        self._setup_size_grip()

    def _toggle_ocr_visibility(self) -> None:
        """切换 CombinedPanel 中 OCR 原始文本展收状态"""
        if self._ocr_label.isVisible():
            self._ocr_label.hide()
            self._ocr_btn.setText("📄 OCR原文")
        else:
            self._ocr_label.show()
            self._ocr_btn.setText("🙈 隐藏OCR")

    def _increase_font(self) -> None:
        self._font_size_en = min(self._font_size_en + 1, 28)
        self._font_size_zh = min(self._font_size_zh + 1, 28)
        self._apply_font_sizes()

    def _decrease_font(self) -> None:
        self._font_size_en = max(self._font_size_en - 1, 9)
        self._font_size_zh = max(self._font_size_zh - 1, 9)
        self._apply_font_sizes()

    def _apply_font_sizes(self) -> None:
        en_font = QFont("Segoe UI", self._font_size_en)
        self._english_edit.setFont(en_font)
        zh_font = QFont("Microsoft YaHei", self._font_size_zh)
        self._chinese_edit.setFont(zh_font)
        self._cfg.set("ui", "font_size_en", self._font_size_en)
        self._cfg.set("ui", "font_size_zh", self._font_size_zh)
        self._cfg.save()

    def show_loading(self) -> None:
        self._loading_label.show()
        self._status_label.hide()
        self.show()
        self.raise_()

    def show_result(self, corrected: str, translation: str, original_ocr: str = "") -> None:
        self._loading_label.hide()
        self._status_label.show()
        self._english_context = corrected
        self._english_edit.setPlainText(corrected)
        self._chinese_edit.setPlainText(translation)

        if original_ocr and original_ocr.strip() != corrected.strip():
            self._ocr_label.setText(f"🔍 OCR 原始文本:\n{original_ocr}")
            self._ocr_btn.show()
        else:
            self._ocr_label.hide()
            self._ocr_btn.hide()
            self._ocr_btn.setText("📄 OCR原文")

        self._status_label.setText("翻译完成 ✓")
        self.show()
        self.raise_()

    def show_error(self, error: str) -> None:
        self._loading_label.hide()
        self._status_label.show()
        self._status_label.setText(f"⚠ {error}")
        self.show()
        self.raise_()

    def _on_word_lookup(self, selected_text: str) -> None:
        self.word_lookup_requested.emit(selected_text, self._english_context)

    def _copy_english(self) -> None:
        QApplication.clipboard().setText(self._english_edit.toPlainText())
        self._copy_en_btn.setText("已复制!")
        QTimer.singleShot(1500, lambda: self._copy_en_btn.setText("复制"))

    def _copy_chinese(self) -> None:
        QApplication.clipboard().setText(self._chinese_edit.toPlainText())
        self._copy_zh_btn.setText("已复制!")
        QTimer.singleShot(1500, lambda: self._copy_zh_btn.setText("复制"))


# ─── 主浮窗管理器控制器 ───────────────────────────────────────
class ResultPanel:
    """
    结果显示面板管理器
    统筹管理合并面板（CombinedPanel）与拆分面板（EnglishPanel / ChinesePanel）
    外部与 MainWindow 保持完全兼容接口
    """

    # 查词信号定义（由于继承 object，这里通过内部包装转发 signal）
    word_lookup_requested = Signal(str, str)  # (selected_text, context_english)

    def __init__(self, parent=None) -> None:
        self._cfg = ConfigManager()
        self._split_mode: bool = self._cfg.get("ui", "split_mode", default=True)

        # 实例化三个独立面板组件
        self._chinese_panel = ChinesePanel(parent)
        self._english_panel = EnglishPanel(parent)
        self._combined_panel = CombinedPanel(parent)

        # 映射查词信号到外部绑定的 callback / signal 代理
        self._lookup_callbacks = []

        self._english_panel.word_lookup_requested.connect(self._on_word_lookup_forward)
        self._combined_panel.word_lookup_requested.connect(self._on_word_lookup_forward)

        # 模式切换连接
        self._chinese_panel.mode_toggle_requested.connect(self.toggle_split_mode)
        self._english_panel.mode_toggle_requested.connect(self.toggle_split_mode)
        self._combined_panel.mode_toggle_requested.connect(self.toggle_split_mode)

    class _SignalProxy:
        def __init__(self, outer: ResultPanel):
            self._outer = outer

        def connect(self, slot):
            self._outer._lookup_callbacks.append(slot)

    @property
    def word_lookup_requested(self):
        return self._SignalProxy(self)

    def _on_word_lookup_forward(self, selected_text: str, context: str) -> None:
        for cb in self._lookup_callbacks:
            try:
                cb(selected_text, context)
            except Exception as e:
                print(f"[ResultPanel] Signal dispatch error: {e}")

    @property
    def is_split_mode(self) -> bool:
        return self._split_mode

    def toggle_split_mode(self) -> None:
        """在拆分双面板与合并单面板模式间切换"""
        self.set_split_mode(not self._split_mode)

    def set_split_mode(self, split: bool) -> None:
        self._split_mode = split
        self._cfg.set("ui", "split_mode", split)
        self._cfg.save()

        if split:
            self._combined_panel.hide()
            self._chinese_panel.show()
            self._english_panel.show()
            self._chinese_panel.raise_()
            self._english_panel.raise_()
        else:
            self._chinese_panel.hide()
            self._english_panel.hide()
            self._combined_panel.show()
            self._combined_panel.raise_()

    # ── 接口兼容方法 ──
    def isVisible(self) -> bool:
        if self._split_mode:
            return self._chinese_panel.isVisible() or self._english_panel.isVisible()
        return self._combined_panel.isVisible()

    def show(self) -> None:
        if self._split_mode:
            self._chinese_panel.show()
            self._english_panel.show()
            self._chinese_panel.raise_()
            self._english_panel.raise_()
        else:
            self._combined_panel.show()
            self._combined_panel.raise_()

    def hide(self) -> None:
        self._chinese_panel.hide()
        self._english_panel.hide()
        self._combined_panel.hide()

    def show_chinese_only(self) -> None:
        """只显示中文翻译长条框"""
        self.set_split_mode(True)
        self._english_panel.hide()
        self._chinese_panel.show()
        self._chinese_panel.raise_()

    def show_english_only(self) -> None:
        """只显示英文原文框"""
        self.set_split_mode(True)
        self._chinese_panel.hide()
        self._english_panel.show()
        self._english_panel.raise_()

    def show_loading(self) -> None:
        if self._split_mode:
            self._chinese_panel.show_loading()
            self._english_panel.show_loading()
        else:
            self._combined_panel.show_loading()

    def show_result(self, corrected: str, translation: str, original_ocr: str = "") -> None:
        if self._split_mode:
            self._chinese_panel.show_result(translation)
            self._english_panel.show_result(corrected, original_ocr)
        else:
            self._combined_panel.show_result(corrected, translation, original_ocr)

    def close(self) -> None:
        self._chinese_panel.close()
        self._english_panel.close()
        self._combined_panel.close()

    def raise_(self) -> None:
        if self._split_mode:
            self._chinese_panel.raise_()
            self._english_panel.raise_()
        else:
            self._combined_panel.raise_()

    def show_error(self, error: str) -> None:
        if self._split_mode:
            self._chinese_panel.show_error(error)
            self._english_panel.show_error(error)
        else:
            self._combined_panel.show_error(error)
