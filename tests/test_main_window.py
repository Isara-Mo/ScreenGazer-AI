"""Qt integration with in-memory configuration and controlled local fakes."""

import copy
import json
import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_path_exists = Path.exists
with patch.object(
    Path, "exists",
    lambda path: False if path.name == "config.json" else _path_exists(path),
):
    from src.utils.config_manager import ConfigManager, DEFAULT_CONFIG
    from src.ui.main_window import MainWindow
    from src.ui.overlay import SelectedRegion
    from src.core.capture import CaptureRegion

from PIL import Image
from PySide6.QtCore import QObject, QPoint, QEventLoop, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication


class PanelSignals(QObject):
    word_lookup_requested = Signal(str, str)


class FakeOCR:
    def __init__(self, block=False):
        self.block = block
        self.entered = threading.Event()
        self.release = threading.Event()
        self.images = []
        self.threads = []

    def recognize(self, image):
        self.images.append(image)
        self.threads.append(QThread.currentThread())
        self.entered.set()
        if self.block and not self.release.wait(4):
            raise RuntimeError("Test did not release OCR")
        return image.info.get("text", "local text")


class FakeClient:
    def __init__(self):
        self.block = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.messages = []
        self.vision_images = []

    def chat(self, messages):
        self.messages.append(messages)
        self.entered.set()
        if self.block and not self.release.wait(4):
            raise RuntimeError("Test did not release the API fake")
        return json.dumps({
            "corrected": messages[0]["content"], "translation": "翻译",
            "word": "example", "meaning": "例子", "part_of_speech": "noun", "note": "",
        })

    def chat_vision(self, prompt, image):
        self.vision_images.append(image)
        return '{"corrected":"vision text","translation":"图像翻译"}'


class MainWindowIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.cfg = object.__new__(ConfigManager)
        self.cfg._config = copy.deepcopy(DEFAULT_CONFIG)
        self.cfg.save = Mock()
        self.cfg.set("capture", "region", [1, 2, 30, 20])
        self.cfg.set("prompts", "translate_text", "{text}")
        self.cfg.set("prompts", "word_lookup", "{selected}: {context}")
        self.cfg.set("watcher", "preset", "custom")
        self.cfg.set("watcher", "poll_interval", 0.1)
        self.cfg.set("watcher", "stability_count", 1)
        self.client = FakeClient()
        self.ocr = FakeOCR()
        self.engines = [self.ocr]
        self.panel_signals = PanelSignals()
        self.panel = Mock()
        self.choice_panel = Mock()
        self.panel.word_lookup_requested = self.panel_signals.word_lookup_requested
        self.panel.isVisible.return_value = True
        self.tooltip = Mock()
        self.tray = Mock()
        self.hotkeys = Mock()
        self.quit_mock = Mock()
        self.capture = Mock(side_effect=self.capture_image)
        self.engine_factory = Mock(return_value=self.ocr)

        patches = [
            patch("src.ui.main_window.ConfigManager", return_value=self.cfg),
            patch("src.ui.main_window.HotkeyManager", return_value=self.hotkeys),
            patch("src.ui.main_window.create_engine", self.engine_factory),
            patch("src.ui.main_window.create_client", return_value=self.client),
            patch("src.ui.main_window.capture_region", self.capture),
            patch("src.ui.main_window.list_windows", return_value=[]),
            patch("src.ui.main_window.ResultPanel", return_value=self.panel),
            patch("src.ui.main_window.ReplyChoicesPanel", return_value=self.choice_panel),
            patch("src.ui.main_window.WordTooltipWidget", return_value=self.tooltip),
            patch.object(MainWindow, "_setup_tray", lambda window: setattr(window, "_tray", self.tray)),
            patch.object(QApplication, "quit", self.quit_mock),
            patch("builtins.print"),
        ]
        for replacement in patches:
            replacement.start()
            self.addCleanup(replacement.stop)
        self.window = MainWindow()
        self.assertIsNotNone(self.window._translate_worker)
        self.assertIsNotNone(self.window._lookup_worker)

    def tearDown(self):
        for engine in self.engines:
            engine.release.set()
        self.client.release.set()
        self.window.quit_app()
        workers = [
            self.window._translate_worker, self.window._lookup_worker,
            *self.window._retired_watch_workers,
        ]
        for worker in workers:
            if worker:
                self.assertTrue(worker.wait(5000))
        self.wait_until(lambda: self.quit_mock.called)
        self.app.processEvents()
        self.window.hide()
        self.window.deleteLater()

    @staticmethod
    def capture_image(region):
        image = Image.new("RGB", (8, 8))
        image.info["text"] = f"region {region.left}"
        return image

    def wait_until(self, predicate, timeout_ms=2500):
        if predicate():
            return
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(2)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(timeout_ms)
        loop.exec()
        poll.stop()
        deadline.stop()
        self.assertTrue(predicate(), "Qt integration did not complete before timeout")

    def assert_nonblocking(self, action):
        # Failing implementations unblock eventually instead of hanging pytest.
        rescue = threading.Timer(1, lambda: [engine.release.set() for engine in self.engines])
        rescue.start()
        started = time.monotonic()
        try:
            action()
            self.assertLess(time.monotonic() - started, 0.2)
        finally:
            rescue.cancel()

    def test_watch_signal_passes_cached_text_to_translation_without_ocr(self):
        self.window._rebuild_watch_worker()
        self.window._is_watching = True
        worker = self.window._watch_worker
        image = self.capture_image(CaptureRegion(9, 9, 8, 8))
        with patch.object(
            self.window._translate_worker, "translate",
            wraps=self.window._translate_worker.translate,
        ) as translate:
            worker.translation_needed.emit(image, "exact cached text")
            self.wait_until(lambda: self.panel.show_result.called)
            translate.assert_called_once_with(image, "ocr", ocr_text="exact cached text", automatic=True)

        self.assertEqual(self.ocr.images, [])
        self.assertEqual(self.client.messages, [[{"role": "user", "content": "exact cached text"}]])
        self.panel.show_result.assert_called_once_with(
            corrected="exact cached text", translation="翻译", original_ocr="exact cached text",
        )

    def test_running_watcher_reuses_ocr_result_in_translation_thread(self):
        self.window._start_watching()
        watcher = self.window._watch_worker
        watcher.force_trigger()
        self.wait_until(lambda: self.panel.show_result.called)
        self.window._stop_watching()
        self.wait_until(lambda: not self.window._retired_watch_workers)

        self.assertTrue(self.ocr.images)
        self.assertTrue(all(thread is watcher for thread in self.ocr.threads))
        self.assertEqual(self.client.messages[0][0]["content"], "region 1")

    def test_stop_during_ocr_returns_immediately_and_ignores_old_signals(self):
        self.ocr.block = True
        self.window._start_watching()
        old = self.window._watch_worker
        self.wait_until(self.ocr.entered.is_set)
        self.assert_nonblocking(self.window._stop_watching)

        self.assertTrue(old.isRunning())
        self.assertIn(old, self.window._retired_watch_workers)
        old.translation_needed.emit(Image.new("RGB", (4, 4)), "stale text")
        old.error_occurred.emit("stale error")
        self.assertEqual(self.client.messages, [])
        self.assertEqual(self.window._status_bar.currentMessage(), "已停止监视")
        self.ocr.release.set()
        self.wait_until(lambda: not self.window._retired_watch_workers)
        self.assertEqual(self.client.messages, [])

    def test_region_replacement_retires_old_worker_and_rejects_its_signals(self):
        self.ocr.block = True
        self.window._start_watching()
        old = self.window._watch_worker
        self.wait_until(self.ocr.entered.is_set)
        self.assert_nonblocking(lambda: self.window._on_region_selected(SelectedRegion(50, 60, 70, 80)))
        new = self.window._watch_worker
        self.assertIsNot(new, old)
        self.assertIn(old, self.window._retired_watch_workers)
        self.assertEqual(old._capture_fn().info["text"], "region 1")
        self.assertEqual(new._capture_fn().info["text"], "region 50")

        old.translation_needed.emit(Image.new("RGB", (4, 4)), "old region")
        self.assertEqual(self.client.messages, [])
        new.force_trigger()
        self.ocr.release.set()
        self.wait_until(lambda: self.panel.show_result.called)
        self.assertEqual(self.client.messages[0][0]["content"], "region 50")
        self.cfg.save.assert_called()

    def test_config_replacement_keeps_old_engine_alive_until_ocr_finishes(self):
        self.ocr.block = True
        self.window._start_watching()
        old = self.window._watch_worker
        old_translator = self.window._translator
        self.wait_until(self.ocr.entered.is_set)
        replacement = FakeOCR()
        self.engines.append(replacement)
        self.engine_factory.return_value = replacement
        self.cfg.set("ocr", "paddleocr_lang", "ch")
        self.cfg.set("prompts", "translate_text", "new prompt: {text}")
        self.assert_nonblocking(self.window._on_config_changed)
        new = self.window._watch_worker
        self.assertIsNot(self.window._translator, old_translator)
        self.assertIn(old, self.window._retired_watch_workers)
        old.translation_needed.emit(Image.new("RGB", (4, 4)), "old engine text")
        self.assertEqual(self.client.messages, [])

        new.force_trigger()
        self.ocr.release.set()
        self.wait_until(lambda: self.panel.show_result.called)
        self.assertEqual(len(self.ocr.images), 1)
        self.assertTrue(replacement.images)
        self.assertEqual(self.client.messages[0][0]["content"], "new prompt: region 1")

    def test_monitor_and_prompt_changes_reuse_loaded_ocr_engine(self):
        self.window._manual_translate()
        self.wait_until(lambda: self.panel.show_result.called)
        self.cfg.set("watcher", "preset", "fast")
        self.cfg.set("prompts", "translate_text", "updated: {text}")
        self.window._on_config_changed()
        self.assertIs(self.window._ocr_engine, self.ocr)
        self.engine_factory.assert_called_once()
        self.panel.show_result.reset_mock()
        self.window._manual_translate()
        self.wait_until(lambda: self.panel.show_result.called)
        self.assertEqual(self.client.messages[-1][0]["content"], "updated: region 1")

    def test_model_wait_progress_and_completion_timings_are_visible(self):
        self.client.block = True
        self.window._manual_translate()
        self.wait_until(lambda: "等待模型翻译" in self.window._status_bar.currentMessage())
        self.assertTrue(self.window._translation_progress_timer.isActive())
        self.panel.show_loading.assert_called_once()
        self.client.release.set()
        self.wait_until(lambda: self.panel.show_result.called)
        self.assertFalse(self.window._translation_progress_timer.isActive())
        self.assertIn("模型", self.window._last_timing_label.text())
        self.assertIn("请求合计", self.window._last_timing_label.text())

    def test_queued_request_shows_wait_and_stop_clears_progress_timer(self):
        self.client.block = True
        self.window._manual_translate()
        self.wait_until(self.client.entered.is_set)
        self.window._manual_translate()
        self.assertIn("等待上一条请求结束", self.window._status_bar.currentMessage())
        self.window._stop_watching()
        self.assertFalse(self.window._translation_progress_timer.isActive())
        self.client.release.set()
        self.wait_until(lambda: not self.window._translate_worker._busy)
        self.panel.show_result.assert_not_called()
        self.assertEqual(self.window._status_bar.currentMessage(), "已停止监视")

    def test_manual_translation_progress_cannot_return_after_region_or_config_change(self):
        for change in (lambda: self.window._on_region_selected(SelectedRegion(90, 20, 30, 40)),
                       self.window._on_config_changed):
            with self.subTest(change=change):
                self.client.block = True
                self.client.release.clear()
                self.panel.show_result.reset_mock()
                self.window._manual_translate()
                self.wait_until(lambda: "等待模型翻译" in self.window._status_bar.currentMessage())
                change()
                status = self.window._status_bar.currentMessage()
                self.assertFalse(self.window._translation_progress_timer.isActive())
                self.window._update_translation_progress()
                self.assertEqual(self.window._status_bar.currentMessage(), status)
                self.panel.clear_progress.assert_called()
                self.client.release.set()
                self.wait_until(lambda: not self.window._translate_worker._busy)
                self.panel.show_result.assert_not_called()

    def test_lookup_signal_shows_loading_at_cursor_and_result_without_repositioning(self):
        self.client.block = True
        with patch("PySide6.QtGui.QCursor.pos", return_value=QPoint(30, 40)):
            self.panel_signals.word_lookup_requested.emit("example", "the context")
        self.wait_until(self.client.entered.is_set)
        self.tooltip.show_loading.assert_called_once_with("example", pos=QPoint(45, 55))
        self.assertFalse(self.tooltip.show_result.called)
        self.client.release.set()
        self.wait_until(lambda: self.tooltip.show_result.called)
        self.tooltip.show_result.assert_called_once_with({
            "word": "example", "meaning": "例子", "part_of_speech": "noun", "note": "",
        })
        self.tooltip.move.assert_not_called()
        self.tooltip.show_at.assert_not_called()

    def test_shutdown_waits_for_blocked_ocr_without_destroying_thread(self):
        self.ocr.block = True
        self.window._start_watching()
        old = self.window._watch_worker
        destroyed = []
        old.destroyed.connect(lambda: destroyed.append(True))
        self.wait_until(self.ocr.entered.is_set)
        self.assert_nonblocking(self.window.quit_app)
        self.assertTrue(old.isRunning())
        self.assertIn(old, self.window._retired_watch_workers)
        self.assertEqual(destroyed, [])
        self.quit_mock.assert_not_called()

        # Exercise an actual asynchronous shutdown poll while OCR stays busy.
        timer_done = []
        QTimer.singleShot(120, lambda: timer_done.append(True))
        self.wait_until(lambda: bool(timer_done))
        self.quit_mock.assert_not_called()
        self.assertEqual(destroyed, [])
        self.ocr.release.set()
        self.wait_until(lambda: self.quit_mock.called)
        self.panel.show_result.assert_not_called()

    def test_shutdown_waits_for_active_translation_and_lookup(self):
        self.client.block = True
        self.window._manual_translate()
        self.panel_signals.word_lookup_requested.emit("example", "context")
        self.wait_until(lambda: len(self.client.messages) == 2)
        self.assert_nonblocking(self.window.quit_app)
        self.assertTrue(self.window._translate_worker.isRunning())
        self.assertTrue(self.window._lookup_worker.isRunning())
        self.quit_mock.assert_not_called()
        self.client.release.set()
        self.wait_until(lambda: self.quit_mock.called)
        self.panel.show_result.assert_not_called()
        self.tooltip.show_result.assert_not_called()
        self.tray.hide.assert_called_once()

    def test_new_region_discards_inflight_manual_translation(self):
        self.client.block = True
        self.window._manual_translate()
        self.wait_until(self.client.entered.is_set)
        self.window._on_region_selected(SelectedRegion(90, 20, 30, 40))
        self.client.release.set()
        self.wait_until(lambda: not self.window._translate_worker._busy)
        self.panel.show_result.assert_not_called()

    def test_manual_vl_bypasses_busy_monitor_ocr(self):
        self.cfg.set("recognition_mode", "vl")
        self.ocr.block = True
        self.window._start_watching()
        self.wait_until(self.ocr.entered.is_set)
        self.assert_nonblocking(self.window._manual_translate)
        self.wait_until(lambda: self.panel.show_result.called)

        self.assertFalse(self.ocr.release.is_set())
        self.assertEqual(len(self.ocr.images), 1)
        self.assertEqual(len(self.client.vision_images), 1)
        self.assertEqual(self.client.vision_images[0].info["text"], "region 1")
        self.assertEqual(self.client.messages, [])
        self.assertEqual(self.panel.show_result.call_args.kwargs["corrected"], "vision text")


if __name__ == "__main__":
    unittest.main()
