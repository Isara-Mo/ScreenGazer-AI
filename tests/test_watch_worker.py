"""Exercise actual QThread requests with local stubs; no OCR or network."""

import os
import threading
import unittest
from unittest.mock import patch

from PIL import Image
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QApplication

from src.workers.watch_worker import WatchWorker
from src.core.watcher import WatchObservation


class WatchWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.workers = []
        self.hash_mock = patch("src.core.watcher.imagehash.phash", return_value=0)
        self.hash_mock.start()
        self.addCleanup(self.hash_mock.stop)

    def tearDown(self):
        for worker in self.workers:
            worker.stop()
            self.assertTrue(worker.wait(3000), "worker failed to stop")

    def make_worker(self, ocr):
        worker = WatchWorker(
            lambda: Image.new("RGB", (16, 16)), ocr,
            poll_interval=5, preset="custom",
        )
        self.workers.append(worker)
        return worker

    def test_manual_trigger_runs_ocr_in_worker_and_wakes_long_wait(self):
        sampled = threading.Event()
        translated = threading.Event()
        threads = []
        results = []
        observations = []
        sequence = []

        def ocr(image):
            threads.append(QThread.currentThread())
            sampled.set()
            return "Worker text"

        worker = self.make_worker(ocr)
        worker.observation_changed.connect(
            lambda event: (observations.append(event), sequence.append(event)),
            Qt.ConnectionType.DirectConnection,
        )
        worker.translation_needed.connect(
            lambda image, text: (results.append(text), sequence.append("translate"), translated.set()),
            Qt.ConnectionType.DirectConnection,
        )
        worker.start()
        self.assertTrue(sampled.wait(2))
        worker.force_trigger()
        self.assertTrue(translated.wait(2), "manual request did not interrupt the 5-second wait")
        self.assertEqual(results, ["Worker text"])
        self.assertEqual(observations, [
            WatchObservation("candidate", "Worker text"),
            WatchObservation("submitted", "Worker text", manual=True),
        ])
        self.assertEqual(sequence[-2:], [
            WatchObservation("submitted", "Worker text", manual=True), "translate",
        ])
        self.assertGreaterEqual(len(threads), 2)
        self.assertTrue(all(thread == worker for thread in threads))
        worker.stop()
        self.assertTrue(worker.wait(1000), "stop did not interrupt the wait")

    def test_filtered_capture_status_and_manual_request_use_separate_paths(self):
        waiting = threading.Event()
        translated = threading.Event()
        manual_image = Image.new("RGB", (32, 24), "blue")
        statuses = []
        images = []
        threads = []
        results = []

        def ocr(image):
            images.append(image)
            threads.append(QThread.currentThread())
            return "Manually requested text"

        def record_status(status):
            statuses.append(status)
            waiting.set()

        worker = WatchWorker(
            lambda: None, ocr, poll_interval=5, preset="custom",
            manual_capture_fn=lambda: manual_image,
            empty_capture_status="等待原神对白",
        )
        self.workers.append(worker)
        worker.status_changed.connect(record_status, Qt.ConnectionType.DirectConnection)
        worker.translation_needed.connect(
            lambda image, text: (results.append((image, text)), translated.set()),
            Qt.ConnectionType.DirectConnection,
        )
        worker.start()
        self.assertTrue(waiting.wait(2), "filtered capture did not report its waiting state")
        self.assertIn("等待原神对白", statuses[0])
        self.assertEqual(images, [])
        self.assertEqual(results, [])
        worker.force_trigger()
        self.assertTrue(translated.wait(2), "manual request did not interrupt the 5-second wait")
        self.assertEqual(images, [manual_image])
        self.assertEqual(results, [(manual_image, "Manually requested text")])
        self.assertEqual(threads, [worker])

    def test_stop_during_ocr_returns_immediately_and_suppresses_translation(self):
        sampled = threading.Event()
        entered = threading.Event()
        release = threading.Event()
        results = []
        calls = []
        observations = []

        def ocr(image):
            calls.append(image)
            if len(calls) == 1:
                sampled.set()
                return "Initial candidate"
            entered.set()
            release.wait(3)
            return "Unwanted late result"

        worker = self.make_worker(ocr)
        worker.observation_changed.connect(observations.append, Qt.ConnectionType.DirectConnection)
        worker.translation_needed.connect(
            lambda image, text: results.append(text), Qt.ConnectionType.DirectConnection,
        )
        worker.start()
        self.assertTrue(sampled.wait(2))
        worker.force_trigger()
        self.assertTrue(entered.wait(2))
        worker.stop()
        self.assertFalse(worker.wait(10))
        release.set()
        self.assertTrue(worker.wait(1000))
        self.assertEqual(results, [])
        self.assertEqual(observations, [WatchObservation("candidate", "Initial candidate")])

    def test_settings_request_is_applied_on_worker_thread(self):
        sampled = threading.Event()
        applied = threading.Event()
        updates = []

        def ocr(image):
            sampled.set()
            return "Text"

        worker = self.make_worker(ocr)
        worker.start()
        self.assertTrue(sampled.wait(2))
        original = worker._watcher.update_settings

        def track_update(**settings):
            updates.append((QThread.currentThread(), settings))
            original(**settings)
            applied.set()

        with patch.object(worker._watcher, "update_settings", side_effect=track_update):
            worker.update_settings(preset="fast")
            self.assertTrue(applied.wait(2))
        self.assertEqual(updates[0][0], worker)
        self.assertEqual(worker._watcher.preset, "fast")

    def test_cold_ocr_progress_is_visible_before_ocr_finishes(self):
        progress = threading.Event()
        entered = threading.Event()
        release = threading.Event()
        statuses = []

        def ocr(image):
            entered.set()
            release.wait(3)
            return "Loaded text"

        def record_status(status):
            statuses.append(status)
            if "首次加载" in status:
                progress.set()

        worker = self.make_worker(ocr)
        worker.status_changed.connect(record_status, Qt.ConnectionType.DirectConnection)
        worker.start()
        self.assertTrue(entered.wait(2))
        self.assertTrue(progress.is_set(), "OCR began without reporting its loading state")
        self.assertEqual(len(statuses), 1)
        worker.stop()
        release.set()
        self.assertTrue(worker.wait(1000))
        self.assertEqual(len(statuses), 1, "stopped OCR emitted a late progress message")

    def test_stop_before_run_is_not_reset_inside_run(self):
        worker = self.make_worker(lambda image: self.fail("OCR ran after stop"))
        worker.stop()
        worker.run()
        self.assertFalse(worker._watcher.is_running)


if __name__ == "__main__":
    unittest.main()

