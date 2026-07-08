"""
屏幕捕获模块
Screen/Window Capture Module using mss
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Optional

import mss
import mss.tools
from PIL import Image


@dataclass
class WindowInfo:
    """窗口信息"""
    title: str
    hwnd: int
    left: int
    top: int
    width: int
    height: int

    def __str__(self) -> str:
        return f"{self.title} ({self.width}x{self.height})"


@dataclass
class CaptureRegion:
    """捕获区域"""
    left: int
    top: int
    width: int
    height: int

    # 绑定的窗口信息（可选）
    hwnd: Optional[int] = None
    rel_x: float = 0.0
    rel_y: float = 0.0
    rel_w: float = 0.0
    rel_h: float = 0.0

    def to_mss_monitor(self) -> dict:
        if self.hwnd:
            win = get_window_info(self.hwnd)
            if win:
                # 动态计算当前窗口位置的绝对坐标
                abs_left = int(win.left + self.rel_x * win.width)
                abs_top = int(win.top + self.rel_y * win.height)
                abs_width = max(1, int(self.rel_w * win.width))
                abs_height = max(1, int(self.rel_h * win.height))
                return {
                    "left": abs_left,
                    "top": abs_top,
                    "width": abs_width,
                    "height": abs_height,
                }

        # 降级为绝对屏幕坐标
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


def list_windows() -> list[WindowInfo]:
    """
    枚举所有可见、有标题的顶层窗口
    Returns list of WindowInfo
    """
    import win32gui
    import win32con

    windows: list[WindowInfo] = []

    def enum_callback(hwnd: int, _: None) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title or title.strip() == "":
            return True
        # 过滤掉一些常见的系统窗口
        skip = {"Program Manager", "Windows Input Experience", "Microsoft Text Input Application"}
        if title in skip:
            return True
        try:
            rect = win32gui.GetWindowRect(hwnd)
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            if w > 0 and h > 0:
                windows.append(WindowInfo(
                    title=title,
                    hwnd=hwnd,
                    left=rect[0],
                    top=rect[1],
                    width=w,
                    height=h,
                ))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(enum_callback, None)
    return windows


def get_window_info(hwnd: int) -> Optional[WindowInfo]:
    """获取指定 hwnd 窗口的信息"""
    try:
        import win32gui
        title = win32gui.GetWindowText(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        return WindowInfo(
            title=title,
            hwnd=hwnd,
            left=rect[0],
            top=rect[1],
            width=rect[2] - rect[0],
            height=rect[3] - rect[1],
        )
    except Exception:
        return None


def find_window_by_title(title: str) -> Optional[WindowInfo]:
    """通过标题查找窗口（精确匹配）"""
    for win in list_windows():
        if win.title == title:
            return win
    return None


def bring_window_to_front(hwnd: int) -> None:
    """将窗口置于前台"""
    try:
        import win32gui
        import win32con
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass


def capture_region(region: CaptureRegion) -> Image.Image:
    """
    截取屏幕指定区域
    :param region: 绝对坐标区域
    :return: PIL Image (RGB)
    """
    with mss.mss() as sct:
        monitor = region.to_mss_monitor()
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
    return img


def capture_window_relative(window: WindowInfo, rel_region: tuple[float, float, float, float]) -> Image.Image:
    """
    截取窗口内的相对区域
    :param window: 目标窗口信息
    :param rel_region: 相对坐标 (x_ratio, y_ratio, w_ratio, h_ratio)，0.0-1.0
    :return: PIL Image (RGB)
    """
    rx, ry, rw, rh = rel_region
    abs_left = int(window.left + rx * window.width)
    abs_top = int(window.top + ry * window.height)
    abs_width = max(1, int(rw * window.width))
    abs_height = max(1, int(rh * window.height))

    region = CaptureRegion(
        left=abs_left,
        top=abs_top,
        width=abs_width,
        height=abs_height,
    )
    return capture_region(region)


def capture_absolute(left: int, top: int, width: int, height: int) -> Image.Image:
    """截取绝对坐标区域"""
    return capture_region(CaptureRegion(left, top, width, height))
