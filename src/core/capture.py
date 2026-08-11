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


def _get_true_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """获取真正的窗口矩形（去除 Windows 10/11 DWM 阴影透明边框）"""
    import win32gui
    try:
        rect = ctypes.wintypes.RECT()
        # DWMWA_EXTENDED_FRAME_BOUNDS = 9
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)
        )
        if hr == 0:
            return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        pass
    
    r = win32gui.GetWindowRect(hwnd)
    return (r[0], r[1], r[2] - r[0], r[3] - r[1])


def list_windows() -> list[WindowInfo]:
    """
    枚举所有可见、真正属于应用程序的顶层窗口
    自动过滤掉 Cloaked 隐藏窗口、工具小窗口及系统底层无用窗口（如 dummyLayeredWnd、Windows 输入体验等）
    """
    import win32gui
    import win32con

    windows: list[WindowInfo] = []
    seen_hwnds = set()

    def enum_callback(hwnd: int, _: None) -> bool:
        if hwnd in seen_hwnds:
            return True

        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return True

        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return True

        # 1. 过滤常见的非目标系统/杂项窗口
        lower_title = title.lower()
        junk_keywords = [
            "dummy", "layeredwnd", "input experience", "text input",
            "program manager", "systemsettings", "nvidia georce",
            "msctfime", "default ime", "search", "cortana"
        ]
        if any(k in lower_title for k in junk_keywords):
            return True

        # 2. 过滤本程序自身窗口
        if "vn 翻译" in lower_title or "vn translator" in lower_title or lower_title == "设置":
            return True

        # 3. DWM Cloaked 检查 (过滤 Win10/11 挂起/隐藏的 UWP 后台应用，如假的设置窗口)
        try:
            cloaked = ctypes.c_int(0)
            # DWMWA_CLOAKED = 14
            hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
            )
            if hr == 0 and cloaked.value != 0:
                return True
        except Exception:
            pass

        # 4. 扩展样式检查 (过滤 WS_EX_TOOLWINDOW 工具窗口)
        try:
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if (ex_style & win32con.WS_EX_TOOLWINDOW) and not (ex_style & win32con.WS_EX_APPWINDOW):
                return True
        except Exception:
            pass

        # 5. 尺寸校验 (过滤尺寸过小或无面积的窗口)
        x, y, w, h = _get_true_window_rect(hwnd)
        if w <= 30 or h <= 30:
            return True

        seen_hwnds.add(hwnd)
        windows.append(WindowInfo(
            title=title,
            hwnd=hwnd,
            left=x,
            top=y,
            width=w,
            height=h,
        ))
        return True

    win32gui.EnumWindows(enum_callback, None)
    return windows


def get_window_info(hwnd: int) -> Optional[WindowInfo]:
    """获取指定 hwnd 窗口的信息"""
    try:
        import win32gui
        if not win32gui.IsWindow(hwnd):
            return None
        title = win32gui.GetWindowText(hwnd)
        x, y, w, h = _get_true_window_rect(hwnd)
        return WindowInfo(
            title=title,
            hwnd=hwnd,
            left=x,
            top=y,
            width=w,
            height=h,
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


def _capture_hwnd_direct(
    hwnd: int,
    rel_x: float = 0.0,
    rel_y: float = 0.0,
    rel_w: float = 1.0,
    rel_h: float = 1.0,
) -> Optional[Image.Image]:
    """
    通过 Windows API PrintWindow 直接截取指定 hwnd 窗口的内部画幅，
    完全无视遮挡在目标窗口之上的其他应用（如浏览器、微信、甚至翻译器浮窗）
    """
    import win32gui
    import win32ui

    if not win32gui.IsWindow(hwnd):
        return None

    x, y, w, h = _get_true_window_rect(hwnd)
    if w <= 0 or h <= 0:
        return None

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()

    save_bit_map = win32ui.CreateBitmap()
    save_bit_map.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(save_bit_map)

    # PW_RENDERFULLCONTENT = 2
    result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)

    bmpinfo = save_bit_map.GetInfo()
    bmpstr = save_bit_map.GetBitmapBits(True)

    img = Image.frombuffer(
        "RGB",
        (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
        bmpstr, "raw", "BGRX", 0, 1
    )

    win32gui.DeleteObject(save_bit_map.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    # 检查是否截图失败或返回全黑图像（如某些独占 3D 游戏）
    if result != 1 or img is None:
        return None

    extrema = img.getextrema()
    if extrema and all(e == (0, 0) for e in extrema):
        return None

    # 按相对比例裁切子区域
    crop_l = int(rel_x * w)
    crop_t = int(rel_y * h)
    crop_w = int(rel_w * w)
    crop_h = int(rel_h * h)

    crop_l = max(0, min(crop_l, w - 1))
    crop_t = max(0, min(crop_t, h - 1))
    crop_r = max(crop_l + 1, min(crop_l + crop_w, w))
    crop_b = max(crop_t + 1, min(crop_t + crop_h, h))

    return img.crop((crop_l, crop_t, crop_r, crop_b))


def capture_region(region: CaptureRegion) -> Image.Image:
    """
    截取屏幕指定区域
    若绑定了 hwnd，优先通过 PrintWindow 独立截取该窗口，避免被覆盖在上面的其他窗口遮挡；
    若 PrintWindow 失败（如独占 3D 游戏），自动降级为 mss 抓取屏幕物理区域。
    """
    if region.hwnd:
        img = _capture_hwnd_direct(
            region.hwnd,
            rel_x=region.rel_x,
            rel_y=region.rel_y,
            rel_w=region.rel_w,
            rel_h=region.rel_h,
        )
        if img is not None:
            return img

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
        hwnd=window.hwnd,
        rel_x=rx,
        rel_y=ry,
        rel_w=rw,
        rel_h=rh,
    )
    return capture_region(region)


def capture_absolute(left: int, top: int, width: int, height: int) -> Image.Image:
    """截取绝对坐标区域"""
    return capture_region(CaptureRegion(left, top, width, height))
