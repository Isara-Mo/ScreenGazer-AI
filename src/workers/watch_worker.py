"""Background local-OCR monitoring with interruptible, thread-safe requests."""

from __future__ import annotations

import threading
from typing import Callable, Optional

from PIL import Image
from PySide6.QtCore import QThread, Signal

from src.core.watcher import ChangeWatcher


class WatchWorker(QThread):
    """Own all watcher operations on the worker thread, including manual OCR."""

    translation_needed = Signal(object, str)
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(
        self,
        capture_fn: Callable[[], Optional[Image.Image]],
        quick_ocr_fn: Callable[[Image.Image], str],
        poll_interval: float = 0.3,
        stability_count: int = 2,
        hash_threshold: int = 5,
        cooldown_seconds: float = 0.5,
        parent=None,
        preset: str = "auto",
    ) -> None:
        super().__init__(parent)
        self._capture_fn = capture_fn
        self._quick_ocr_fn = quick_ocr_fn
        self._settings = {
            "poll_interval": poll_interval, "stability_count": stability_count,
            "hash_threshold": hash_threshold, "preset": preset,
        }
        self._cooldown_seconds = cooldown_seconds
        self._watcher: Optional[ChangeWatcher] = None
        self._stop_event = threading.Event()
        self._force_event = threading.Event()
        self._wake_event = threading.Event()
        self._settings_lock = threading.Lock()
        self._pending_settings: dict = {}

    def start(self, priority=QThread.Priority.InheritPriority) -> None:
        if self.isRunning():
            return
        # Clear before scheduling run(): a stop immediately after start is kept.
        self._stop_event.clear()
        self._force_event.clear()
        self._wake_event.clear()
        super().start(priority)

    def run(self) -> None:
        def on_stable(image: Image.Image, text: str) -> None:
            if not self._stop_event.is_set():
                self.translation_needed.emit(image, text)

        self._watcher = ChangeWatcher(
            capture_fn=self._capture_fn,
            quick_ocr_fn=self._quick_ocr_fn,
            on_stable=on_stable,
            cooldown_seconds=self._cooldown_seconds,
            **self._settings,
        )
        self._watcher.start()
        try:
            while not self._stop_event.is_set():
                self._wake_event.clear()
                with self._settings_lock:
                    pending = self._pending_settings
                    self._pending_settings = {}
                try:
                    if pending:
                        self._settings.update(pending)
                        self._watcher.update_settings(**self._settings)
                    if self._stop_event.is_set():
                        break
                    if self._force_event.is_set():
                        self._force_event.clear()
                        status = self._watcher.force_trigger()
                    else:
                        status = self._watcher.tick()
                    if not self._stop_event.is_set():
                        self.status_changed.emit(status)
                except Exception as exc:
                    if not self._stop_event.is_set():
                        self.error_occurred.emit(str(exc))
                self._wake_event.wait(self._watcher.next_poll_interval)
        finally:
            self._watcher.stop()

    def stop(self) -> None:
        """Return immediately; in-flight OCR finishes without emitting a result."""
        self._stop_event.set()
        self._wake_event.set()

    def force_trigger(self) -> None:
        """Coalesce manual requests and wake the background thread."""
        self._force_event.set()
        self._wake_event.set()

    def update_settings(
        self,
        poll_interval: float | None = None,
        stability_count: int | None = None,
        hash_threshold: int | None = None,
        preset: str | None = None,
    ) -> None:
        settings = {"poll_interval": poll_interval, "stability_count": stability_count,
                    "hash_threshold": hash_threshold, "preset": preset}
        with self._settings_lock:
            self._pending_settings.update({k: v for k, v in settings.items() if v is not None})
        self._wake_event.set()
