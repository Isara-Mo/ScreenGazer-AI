"""
变化监视 Worker (QThread)
Watch Worker - runs the ChangeWatcher in a background thread
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from PIL import Image
from PySide6.QtCore import QThread, Signal

from src.core.watcher import ChangeWatcher


class WatchWorker(QThread):
    """
    在后台线程中运行 ChangeWatcher
    
    Signals:
        translation_needed(Image.Image): 需要翻译时发出，携带最终截图
        status_changed(str): 监视状态文字更新
        error_occurred(str): 发生错误时发出
    """

    translation_needed = Signal(object)   # PIL Image
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(
        self,
        capture_fn: Callable[[], Optional[Image.Image]],
        quick_ocr_fn: Callable[[Image.Image], str],
        poll_interval: float = 0.5,
        stability_count: int = 3,
        hash_threshold: int = 8,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._capture_fn = capture_fn
        self._quick_ocr_fn = quick_ocr_fn
        self._poll_interval = poll_interval
        self._stability_count = stability_count
        self._hash_threshold = hash_threshold
        self._watcher: Optional[ChangeWatcher] = None
        self._stop_flag = False

    def run(self) -> None:
        """QThread 主循环"""
        self._stop_flag = False

        def on_stable(img: Image.Image) -> None:
            self.translation_needed.emit(img)

        self._watcher = ChangeWatcher(
            capture_fn=self._capture_fn,
            quick_ocr_fn=self._quick_ocr_fn,
            on_stable=on_stable,
            poll_interval=self._poll_interval,
            stability_count=self._stability_count,
            hash_threshold=self._hash_threshold,
        )
        self._watcher.start()

        while not self._stop_flag:
            try:
                status = self._watcher.tick()
                self.status_changed.emit(status)
            except Exception as e:
                self.error_occurred.emit(str(e))
            time.sleep(self._poll_interval)

        self._watcher.stop()

    def stop(self) -> None:
        """停止监视线程"""
        self._stop_flag = True
        if self._watcher:
            self._watcher.stop()

    def force_trigger(self) -> None:
        """强制触发翻译（快捷键调用，线程安全）"""
        if self._watcher and self._watcher.is_running:
            self._watcher.force_trigger()

    def update_settings(
        self,
        poll_interval: float | None = None,
        stability_count: int | None = None,
        hash_threshold: int | None = None,
    ) -> None:
        """动态更新监视参数"""
        if self._watcher:
            if poll_interval is not None:
                self._watcher.poll_interval = poll_interval
                self._poll_interval = poll_interval
            if stability_count is not None:
                self._watcher.stability_count = stability_count
            if hash_threshold is not None:
                self._watcher.hash_threshold = hash_threshold
