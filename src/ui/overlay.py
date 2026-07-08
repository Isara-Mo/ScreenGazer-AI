"""
屏幕区域选择浮层
Region Selector Overlay - fullscreen transparent widget for selecting capture region
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QCursor,
    QKeyEvent, QMouseEvent,
)
from PySide6.QtWidgets import QWidget, QApplication


@dataclass
class SelectedRegion:
    """用户选定的区域（屏幕绝对坐标）"""
    left: int
    top: int
    width: int
    height: int

    def to_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)


class RegionSelectorOverlay(QWidget):
    """
    全屏半透明遮罩，允许用户鼠标拖拽选定截图区域
    
    Signals:
        region_selected(SelectedRegion): 用户完成选取，携带屏幕坐标区域
        cancelled(): 用户按 Esc 取消选取
    """

    region_selected = Signal(object)  # SelectedRegion
    cancelled = Signal()

    # 视觉常量
    _OVERLAY_ALPHA = 160
    _BORDER_COLOR = QColor(124, 58, 237)        # 紫色边框
    _FILL_COLOR = QColor(124, 58, 237, 30)      # 半透明填充
    _CROSSHAIR_COLOR = QColor(200, 200, 200, 100)
    _HINT_COLOR = QColor(255, 255, 255, 220)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

        self._start: Optional[QPoint] = None
        self._end: Optional[QPoint] = None
        self._dragging = False

        # 铺满所有屏幕
        screen_geo = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(screen_geo)

    def start_selection(self) -> None:
        """显示选择浮层并开始等待用户操作"""
        self._start = None
        self._end = None
        self._dragging = False
        self.showFullScreen()
        self.activateWindow()
        self.raise_()

    # ─── 鼠标事件 ────────────────────────────────────────────
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._end = self._start
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self._end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._end = event.position().toPoint()
            self._dragging = False
            self.update()
            self._confirm_selection()

    # ─── 键盘事件 ────────────────────────────────────────────
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.cancelled.emit()

    # ─── 绘制 ────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 半透明遮罩
        painter.fillRect(self.rect(), QColor(0, 0, 0, self._OVERLAY_ALPHA))

        if self._start and self._end:
            rect = self._get_rect()

            # 清除选区内的遮罩（显示原始内容）
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            # 选区填充
            painter.fillRect(rect, self._FILL_COLOR)

            # 选区边框
            pen = QPen(self._BORDER_COLOR, 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(rect)

            # 尺寸标注
            w = abs(rect.width())
            h = abs(rect.height())
            size_text = f"{w} × {h}"
            painter.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
            painter.setPen(self._HINT_COLOR)
            label_x = rect.x() + 6
            label_y = rect.y() - 6 if rect.y() > 24 else rect.y() + rect.height() + 18
            painter.drawText(label_x, label_y, size_text)

        # 提示文字（未开始拖拽时）
        if not self._start:
            painter.setFont(QFont("Microsoft YaHei", 14))
            painter.setPen(self._HINT_COLOR)
            hint = "拖拽鼠标选择捕获区域   |   按 Esc 取消"
            rect = self.rect()
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, hint)

    # ─── 内部方法 ────────────────────────────────────────────
    def _get_rect(self) -> QRect:
        """返回规范化矩形（start 和 end 任意顺序）"""
        if not self._start or not self._end:
            return QRect()
        x1 = min(self._start.x(), self._end.x())
        y1 = min(self._start.y(), self._end.y())
        x2 = max(self._start.x(), self._end.x())
        y2 = max(self._start.y(), self._end.y())
        return QRect(x1, y1, x2 - x1, y2 - y1)

    def _confirm_selection(self) -> None:
        """确认选取区域并发出信号"""
        rect = self._get_rect()
        if rect.width() < 10 or rect.height() < 10:
            # 区域太小，忽略
            self._start = None
            self._end = None
            self.update()
            return

        # 转换为全局屏幕物理坐标（乘以 devicePixelRatio，修复高 DPI 下截图错位问题）
        ratio = self.devicePixelRatio()
        region = SelectedRegion(
            left=int(rect.x() * ratio),
            top=int(rect.y() * ratio),
            width=int(rect.width() * ratio),
            height=int(rect.height() * ratio),
        )
        self.hide()
        self.region_selected.emit(region)
