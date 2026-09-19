"""Per-request telemetry follows the latest dialogue and UI throttling stays cosmetic."""

import time
import unittest
from unittest.mock import patch

from PIL import Image
from PySide6.QtWidgets import QApplication

from tests import test_main_window as fixture
from src.core.timing_summary import format_timing_summary
from src.core.watcher import WatchObservation, WatchTiming


class TimingIntegrationTests(unittest.TestCase):
    setUp = fixture.MainWindowIntegrationTests.setUp
    tearDown = fixture.MainWindowIntegrationTests.tearDown
    wait_until = fixture.MainWindowIntegrationTests.wait_until
    capture_image = staticmethod(fixture.MainWindowIntegrationTests.capture_image)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def attach_monitor(self):
        self.window._rebuild_watch_worker()
        self.window._is_watching = True
        return self.window._watch_worker

    def submit(self, text, timing, *, manual=False):
        worker = self.window._watch_worker
        worker.observation_changed.emit(WatchObservation("submitted", text, manual, timing))
        worker.translation_needed.emit(Image.new("RGB", (16, 8)), text)

    def test_replacement_request_uses_its_own_monitor_metrics(self):
        self.attach_monitor()
        self.client.block = True
        now = time.monotonic()
        old = WatchTiming(now - 10, now - 8, 0.5, 0.7, 5, 0.8)
        new = WatchTiming(now - 1, now - 0.2, 0.06, 0.15, 3, 0.65)
        with patch("src.ui.main_window.format_timing_summary", wraps=format_timing_summary) as summary:
            self.submit("Old line", old)
            self.wait_until(self.client.entered.is_set)
            self.submit("Current line", new)
            self.client.release.set()
            self.wait_until(lambda: self.panel.show_result.called)
        summary.assert_called_once()
        self.assertIs(summary.call_args.kwargs["monitor"], new)
        self.assertEqual(summary.call_args.args[0]["ocr_mode"], "reused")
        self.assertIn("OCR 累计 0.15s/3轮", self.window._last_timing_label.text())
        self.assertNotIn("0.70s/5轮", self.window._last_timing_label.text())
        self.assertEqual(self.panel.show_result.call_args.kwargs["corrected"], "Current line")
        snapshot = self.window._last_timing_label.text()
        self.window._watch_worker.observation_changed.emit(WatchObservation("candidate", "Next line"))
        self.assertEqual(self.window._last_timing_label.text(), snapshot)

    def test_deferred_result_separates_time_waiting_for_dialogue_to_return(self):
        worker = self.attach_monitor()
        self.client.block = True
        now = time.monotonic()
        timing = WatchTiming(now - 1, now - 0.2, 0.06, 0.15, 3, 0.65)
        with patch("src.ui.main_window.format_timing_summary", wraps=format_timing_summary) as summary:
            self.submit("A", timing)
            self.wait_until(self.client.entered.is_set)
            worker.observation_changed.emit(WatchObservation("candidate", "B"))
            self.client.release.set()
            self.wait_until(lambda: not self.window._translate_worker._busy)
            summary.assert_not_called()
            received = self.window._translation_received_at
            with patch("src.ui.main_window.time.monotonic", return_value=received + 2):
                worker.observation_changed.emit(WatchObservation("current", "A"))
        summary.assert_called_once()
        self.assertAlmostEqual(summary.call_args.kwargs["held_seconds"], 2)
        self.assertAlmostEqual(summary.call_args.kwargs["total_seconds"], received + 2 - timing.started_at)
        self.assertIn("等待对白恢复 2.00s", self.window._last_timing_label.text())
        self.assertEqual(len(self.client.messages), 1)

    def test_manual_request_captures_its_own_timing_and_stop_discards_context(self):
        with patch("src.ui.main_window.format_timing_summary", wraps=format_timing_summary) as summary:
            self.window._manual_translate()
            self.wait_until(lambda: self.panel.show_result.called)
        values = summary.call_args.kwargs
        self.assertTrue(values["manual"])
        self.assertIsNotNone(values["monitor"])
        self.assertEqual(values["monitor"].ocr_samples, 0)
        self.assertEqual(summary.call_args.args[0]["ocr_mode"], "request")
        self.assertEqual(len(self.ocr.images), 1)
        snapshot = self.window._last_timing_label.text()
        self.window._stop_watching()
        self.assertIsNone(self.window._translation_timing)
        self.assertIsNone(self.window._translation_received_at)
        self.assertEqual(self.window._last_timing_label.text(), snapshot)

    def test_status_coalescing_does_not_delay_observations_or_requests(self):
        worker = self.attach_monitor()
        with patch("src.ui.main_window.time.monotonic", return_value=10):
            worker.status_changed.emit("First state")
        self.assertEqual(self.window._status_bar.currentMessage(), "First state")
        with patch("src.ui.main_window.time.monotonic", return_value=10.1):
            worker.status_changed.emit("OCR in progress")
            worker.observation_changed.emit(WatchObservation("candidate", "A"))
            worker.status_changed.emit("Latest state")
        self.assertEqual(self.window._watch_observation.text, "A")
        self.assertEqual(self.window._status_bar.currentMessage(), "First state")
        self.assertTrue(self.window._watch_status_timer.isActive())
        with patch("src.ui.main_window.time.monotonic", return_value=12):
            self.window._flush_watch_status()
        self.assertEqual(self.window._status_bar.currentMessage(), "Latest state")
        with patch("src.ui.main_window.time.monotonic", return_value=12.1):
            worker.status_changed.emit("Superseded diagnostic")
            self.submit("A", None)
        self.wait_until(lambda: self.panel.show_result.called)
        self.assertFalse(self.window._watch_status_timer.isActive())
        self.assertIsNone(self.window._pending_watch_status)
        self.assertIn("翻译完成", self.window._status_bar.currentMessage())
        self.assertEqual(len(self.client.messages), 1)
        worker.status_changed.emit("Pending after result")
        self.window._stop_watching()
        self.window._flush_watch_status()
        self.assertEqual(self.window._status_bar.currentMessage(), "已停止监视")


if __name__ == "__main__":
    unittest.main()
