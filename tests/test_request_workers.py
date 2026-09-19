"""Real Qt-thread regressions with controlled fakes and no OCR/API access."""

import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Keep module-level configuration singletons away from the user's credentials.
_path_exists = Path.exists
with patch.object(
    Path, "exists",
    lambda path: False if path.name == "config.json" else _path_exists(path),
):
    from src.core.translator import Translator, TranslationResult
    from src.workers.translate_worker import TranslateWorker
    from src.workers.word_lookup_worker import WordLookupWorker

from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication


class ControlledTranslator:
    """Hold request A in a background thread until the test permits completion."""

    def __init__(self, block_first=True, fail_first=False):
        self.block_first = block_first
        self.fail_first = fail_first
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.ocr_inputs = []
        self.vision_inputs = []

    def _execute(self, name):
        self.calls.append(name)
        if name == "A":
            self.entered.set()
            if self.block_first and not self.release.wait(4):
                raise RuntimeError("Test did not release request A")
            if self.fail_first:
                raise RuntimeError("superseded request failed")

    def translate_ocr(self, image, ocr_text=None):
        name = image.info["request"]
        self.ocr_inputs.append(ocr_text)
        self._execute(name)
        return TranslationResult(corrected=name, translation=f"translated {name}")

    def translate_vl(self, image, ocr_text=None):
        name = image.info["request"]
        self.vision_inputs.append(image)
        self._execute(name)
        return TranslationResult(corrected=name, translation=f"vision {name}")

    def lookup_word(self, selected_text, context, lookup_client=None, prompt_template=""):
        self._execute(selected_text)
        return {"word": selected_text, "meaning": context}


class RequestWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.resources = []

    def tearDown(self):
        for worker, translator in self.resources:
            worker.cancel_pending()
            translator.release.set()
            self.assertTrue(worker.wait(5000), "background worker did not stop")
        # Deliver finished while workers and their connected callbacks live.
        self.app.processEvents()
        for worker, _ in self.resources:
            worker.deleteLater()

    def wait_until(self, predicate, timeout_ms=2000):
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
        self.assertTrue(predicate(), "Qt operation did not complete before timeout")

    def make_worker(self, worker_type, translator):
        worker = worker_type(translator)
        self.resources.append((worker, translator))
        results, errors = [], []
        worker.result_ready.connect(results.append)
        worker.error_occurred.connect(errors.append)
        return worker, results, errors

    @staticmethod
    def submit(worker, name):
        if isinstance(worker, TranslateWorker):
            image = Image.new("RGB", (4, 4))
            image.info["request"] = name
            worker.translate(image, ocr_text=f"observed {name}")
        else:
            worker.lookup(name, f"context {name}")

    @staticmethod
    def result_names(results):
        return [r.corrected if isinstance(r, TranslationResult) else r["word"] for r in results]

    def test_rapid_requests_are_nonblocking_and_only_latest_is_executed(self):
        for worker_type in (TranslateWorker, WordLookupWorker):
            with self.subTest(worker=worker_type.__name__):
                fake = ControlledTranslator()
                worker, results, errors = self.make_worker(worker_type, fake)
                self.submit(worker, "A")
                self.wait_until(fake.entered.is_set)

                # Also releases a mistakenly blocking implementation so failure
                # is an assertion instead of a hung test process.
                rescue = threading.Timer(1, fake.release.set)
                rescue.start()
                try:
                    started = time.monotonic()
                    self.submit(worker, "B")
                    self.submit(worker, "C")
                    elapsed = time.monotonic() - started
                    self.assertLess(elapsed, 0.2)
                    self.assertEqual(fake.calls, ["A"])
                finally:
                    rescue.cancel()
                    fake.release.set()

                self.wait_until(lambda: not worker._busy)
                self.assertEqual(fake.calls, ["A", "C"])
                self.assertEqual(self.result_names(results), ["C"])
                self.assertEqual(errors, [])
                if worker_type is TranslateWorker:
                    self.assertEqual(fake.ocr_inputs, ["observed A", "observed C"])

    def test_new_request_after_run_before_finished_delivery_is_retained(self):
        for worker_type in (TranslateWorker, WordLookupWorker):
            with self.subTest(worker=worker_type.__name__):
                fake = ControlledTranslator(block_first=False)
                worker, results, errors = self.make_worker(worker_type, fake)
                self.submit(worker, "A")
                # wait() joins run without pumping the GUI's queued finished.
                self.assertTrue(worker.wait(2000))
                self.assertFalse(worker.isRunning())
                self.assertTrue(worker._busy)
                self.assertEqual(results, [])

                self.submit(worker, "B")
                self.wait_until(lambda: not worker._busy)
                self.assertEqual(fake.calls, ["A", "B"])
                self.assertEqual(self.result_names(results), ["B"])
                self.assertEqual(errors, [])

    def test_cancel_pending_discards_active_and_queued_results(self):
        for worker_type in (TranslateWorker, WordLookupWorker):
            with self.subTest(worker=worker_type.__name__):
                fake = ControlledTranslator()
                worker, results, errors = self.make_worker(worker_type, fake)
                self.submit(worker, "A")
                self.wait_until(fake.entered.is_set)
                self.submit(worker, "B")
                worker.cancel_pending()
                fake.release.set()
                self.wait_until(lambda: not worker._busy)

                self.assertEqual(fake.calls, ["A"])
                self.assertEqual(results, [])
                self.assertEqual(errors, [])
                self.submit(worker, "C")
                self.wait_until(lambda: not worker._busy)
                self.assertEqual(self.result_names(results), ["C"])

    def test_translator_change_discards_old_work_and_uses_new_client(self):
        for worker_type in (TranslateWorker, WordLookupWorker):
            with self.subTest(worker=worker_type.__name__):
                old = ControlledTranslator()
                new = ControlledTranslator(block_first=False)
                worker, results, errors = self.make_worker(worker_type, old)
                self.submit(worker, "A")
                self.wait_until(old.entered.is_set)
                self.submit(worker, "B")
                worker.update_translator(new)
                self.submit(worker, "C")
                old.release.set()
                self.wait_until(lambda: not worker._busy)

                self.assertEqual(old.calls, ["A"])
                self.assertEqual(new.calls, ["C"])
                self.assertEqual(self.result_names(results), ["C"])
                self.assertEqual(errors, [])

    def test_superseded_failure_does_not_overwrite_new_request(self):
        for worker_type in (TranslateWorker, WordLookupWorker):
            with self.subTest(worker=worker_type.__name__):
                fake = ControlledTranslator(fail_first=True)
                worker, results, errors = self.make_worker(worker_type, fake)
                self.submit(worker, "A")
                self.wait_until(fake.entered.is_set)
                self.submit(worker, "C")
                fake.release.set()
                self.wait_until(lambda: not worker._busy)

                self.assertEqual(self.result_names(results), ["C"])
                self.assertEqual(errors, [])

    def test_vl_request_keeps_image_even_when_observed_text_is_available(self):
        fake = ControlledTranslator(block_first=False)
        worker, results, errors = self.make_worker(TranslateWorker, fake)
        image = Image.new("RGB", (4, 4))
        image.info["request"] = "A"
        worker.translate(image, mode="vl", ocr_text="text used only for change detection")
        self.wait_until(lambda: not worker._busy)

        self.assertEqual(fake.ocr_inputs, [])
        self.assertEqual(len(fake.vision_inputs), 1)
        self.assertIs(fake.vision_inputs[0], image)
        self.assertEqual(self.result_names(results), ["A"])
        self.assertEqual(errors, [])


class TranslatorInputTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGB", (4, 4))
        self.client = Mock()
        self.client.chat.return_value = '{"corrected":"Hello","translation":"你好"}'
        self.client.chat_vision.return_value = self.client.chat.return_value
        self.ocr = Mock()
        self.ocr.recognize.return_value = "manual text"
        self.translator = Translator(
            self.client, self.ocr,
            translate_text_prompt="Translate: {text}",
            translate_vl_prompt="Read the screenshot",
        )
        quiet = patch("builtins.print")
        quiet.start()
        self.addCleanup(quiet.stop)

    def test_observed_text_goes_directly_to_llm_without_another_ocr(self):
        result = self.translator.translate_ocr(self.image, ocr_text="watched text")
        self.assertTrue(result.success)
        self.assertEqual(result.original_ocr, "watched text")
        self.ocr.recognize.assert_not_called()
        self.client.chat.assert_called_once_with(
            [{"role": "user", "content": "Translate: watched text"}]
        )
        self.client.chat_vision.assert_not_called()

    def test_observed_text_does_not_require_an_ocr_engine(self):
        translator = Translator(self.client, translate_text_prompt="{text}")
        result = translator.translate_ocr(self.image, ocr_text="already read")
        self.assertTrue(result.success)
        self.assertEqual(result.original_ocr, "already read")

    def test_manual_translation_still_runs_local_ocr(self):
        result = self.translator.translate_ocr(self.image)
        self.assertTrue(result.success)
        self.ocr.recognize.assert_called_once_with(self.image)
        self.client.chat.assert_called_once_with(
            [{"role": "user", "content": "Translate: manual text"}]
        )

    def test_empty_observed_text_does_not_repeat_ocr_or_call_llm(self):
        result = self.translator.translate_ocr(self.image, ocr_text="   ")
        self.assertFalse(result.success)
        self.assertTrue(result.error)
        self.ocr.recognize.assert_not_called()
        self.client.chat.assert_not_called()

    def test_vl_uses_original_image_without_local_ocr(self):
        result = self.translator.translate_vl(self.image)
        self.assertTrue(result.success)
        self.client.chat_vision.assert_called_once_with("Read the screenshot", self.image)
        self.client.chat.assert_not_called()
        self.ocr.recognize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
