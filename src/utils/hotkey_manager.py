"""
全局快捷键管理模块
Global Hotkey Manager using the `keyboard` library

注意: keyboard.add_hotkey 在 Windows 上需要在 Qt 事件循环启动后调用。
     因此注册操作通过 QTimer.singleShot 延迟到事件循环启动后执行。
"""

import threading
from typing import Any, Callable, Optional

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False


class HotkeyManager:
    """
    管理全局快捷键的注册与注销
    使用 `keyboard` 库监听全局按键

    重要: register() 应在 Qt 事件循环启动后调用（例如通过 QTimer.singleShot 延迟）
    """

    def __init__(self) -> None:
        self._hotkeys: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._enabled = KEYBOARD_AVAILABLE

        if not self._enabled:
            print("[HotkeyManager] 警告: `keyboard` 库未安装，全局快捷键不可用")

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        """
        注册全局快捷键
        :param hotkey: 快捷键字符串，例如 "ctrl+shift+t"
        :param callback: 触发时的回调函数
        :return: 是否注册成功
        """
        if not self._enabled:
            print("[HotkeyManager] keyboard 库不可用，跳过注册")
            return False

        with self._lock:
            # 先取消同名旧注册
            if hotkey in self._hotkeys:
                try:
                    keyboard.remove_hotkey(self._hotkeys[hotkey])
                except Exception:
                    pass
                del self._hotkeys[hotkey]

            try:
                hook = keyboard.add_hotkey(hotkey, callback, suppress=False)
                self._hotkeys[hotkey] = hook
                print(f"[HotkeyManager] 已注册快捷键: {hotkey}")
                return True
            except Exception as e:
                print(f"[HotkeyManager] 注册快捷键失败 '{hotkey}': {e}")
                return False

    def register_delayed(self, hotkey: str, callback: Callable[[], None], delay_ms: int = 1000) -> None:
        """
        延迟注册快捷键（在 Qt 事件循环启动后执行，避免 Windows hook 问题）
        :param delay_ms: 延迟毫秒数，默认 1000ms
        """
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(delay_ms, lambda: self.register(hotkey, callback))
        except Exception:
            # Qt 不可用时直接注册
            self.register(hotkey, callback)

    def unregister(self, hotkey: str) -> None:
        """注销指定快捷键"""
        if not self._enabled:
            return

        with self._lock:
            if hotkey in self._hotkeys:
                try:
                    keyboard.remove_hotkey(self._hotkeys[hotkey])
                except Exception:
                    pass
                del self._hotkeys[hotkey]
                print(f"[HotkeyManager] 已注销快捷键: {hotkey}")

    def unregister_all(self) -> None:
        """注销所有快捷键"""
        if not self._enabled or not self._hotkeys:
            return

        with self._lock:
            for hotkey, hook in list(self._hotkeys.items()):
                try:
                    keyboard.remove_hotkey(hook)
                except Exception:
                    pass
            self._hotkeys.clear()
            print("[HotkeyManager] 已注销所有快捷键")

    @property
    def available(self) -> bool:
        return self._enabled
