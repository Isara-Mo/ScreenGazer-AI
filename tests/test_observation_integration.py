"""Observed dialogue gates asynchronous results; OCR/model calls stay offline."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_main_window as fixture
from PIL import Image
from PySide6.QtWidgets import QApplication

from src.core.watcher import WatchObservation, normalize_ocr_text
from src.ui.overlay import SelectedRegion
from src.ui.result_panel import ResultPanel


class ObservationIntegrationTests(unittest.TestCase):
    setUp = fixture.MainWindowIntegrationTests.setUp
    tearDown = fixture.MainWindowIntegrationTests.tearDown
    wait_until = fixture.MainWindowIntegrationTests.wait_until
    capture_image = staticmethod(fixture.MainWindowIntegrationTests.capture_image)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def attach_monitor(self):
        """Use real Qt signals with controlled observations, without polling."""
        self.window._rebuild_watch_worker()
        self.window._is_watching = True
        return self.window._watch_worker

    def observe(self, kind, text="", manual=False):
        self.window._watch_worker.observation_changed.emit(
            WatchObservation(kind, normalize_ocr_text(text), manual)
        )

    def submit(self, text, *, manual=False):
        image = Image.new("RGB", (16, 8))
        image.info["text"] = text
        self.observe("submitted", text, manual)
        self.window._watch_worker.translation_needed.emit(image, text)
        return image

    def defer_first_result(self):
        self.attach_monitor()
        self.client.block = True
        self.submit("Original dialogue A.")
        self.wait_until(self.client.entered.is_set)
        self.observe("candidate", "Next dialogue B.")
        self.window._update_translation_progress()
        self.assertIn("新句待确认", self.window._status_bar.currentMessage())
        self.assertIn("上条请求处理中", self.window._status_bar.currentMessage())
        self.client.release.set()
        self.wait_until(lambda: not self.window._translate_worker._busy)
        self.panel.show_result.assert_not_called()
        self.assertIsNotNone(self.window._deferred_translation)

    def test_stable_a_b_a_restores_display_without_repeating_model_call(self):
        self.attach_monitor()
        for count, text in enumerate(("Dialogue A.", "Dialogue B.", "Dialogue A.",
                                       "Dialogue B.", "Dialogue A."), 1):
            self.submit(text)
            self.wait_until(lambda: self.panel.show_result.call_count == count)
            self.assertEqual(self.panel.show_result.call_args.kwargs["corrected"], text)
        self.assertEqual(len(self.client.messages), 2)
        self.assertIn("本次模型请求 0 次", self.window._last_timing_label.text())

    def test_cached_current_line_does_not_wait_for_obsolete_model_result(self):
        self.attach_monitor()
        self.submit("Dialogue A.")
        self.wait_until(lambda: self.panel.show_result.called)
        self.client.entered.clear()
        self.client.block = True
        self.submit("Dialogue B.")
        self.wait_until(self.client.entered.is_set)
        self.submit("Dialogue A.")
        self.assertEqual(self.panel.show_result.call_count, 2)
        self.assertEqual(self.panel.show_result.call_args.kwargs["corrected"], "Dialogue A.")
        self.assertTrue(self.window._translate_worker._busy)
        self.client.release.set()
        self.wait_until(lambda: not self.window._translate_worker._busy)
        self.assertEqual(self.panel.show_result.call_count, 2)
        self.assertEqual(len(self.client.messages), 2)

    def test_manual_watch_request_bypasses_cached_answer(self):
        self.attach_monitor()
        self.submit("Dialogue A.")
        self.wait_until(lambda: self.panel.show_result.called)
        self.submit("Dialogue A.", manual=True)
        self.wait_until(lambda: self.panel.show_result.call_count == 2)
        self.assertEqual(len(self.client.messages), 2)
        self.assertNotIn("本次模型请求 0 次", self.window._last_timing_label.text())

    def test_old_result_is_deferred_while_new_text_is_only_a_candidate(self):
        self.defer_first_result()
        self.assertEqual(len(self.client.messages), 1)
        self.assertEqual(self.ocr.images, [])
        self.assertIn("上次结果", self.window._status_bar.currentMessage())
        self.assertFalse(self.window._translation_progress_timer.isActive())

    def test_ocr_noise_returning_to_original_displays_deferred_result_without_api(self):
        self.defer_first_result()
        self.observe("current", "Original\ndialogue A.")
        self.panel.show_result.assert_called_once_with(
            corrected="Original dialogue A.", translation="翻译",
            original_ocr="Original dialogue A.",
        )
        self.assertIsNone(self.window._deferred_translation)
        self.assertEqual(len(self.client.messages), 1)
        self.assertEqual(self.ocr.images, [])

    def test_new_stable_submission_replaces_active_result(self):
        self.attach_monitor()
        self.client.block = True
        self.submit("A")
        self.wait_until(self.client.entered.is_set)
        self.observe("candidate", "B")
        self.submit("B")
        self.client.release.set()
        self.wait_until(lambda: not self.window._translate_worker._busy)
        self.assertEqual([messages[0]["content"] for messages in self.client.messages], ["A", "B"])
        self.panel.show_result.assert_called_once_with(
            corrected="B", translation="翻译", original_ocr="B",
        )
        self.assertIsNone(self.window._deferred_translation)

    def test_stable_submission_then_another_candidate_cannot_display_queued_result(self):
        self.attach_monitor()
        self.client.block = True
        self.submit("A")
        self.wait_until(self.client.entered.is_set)
        self.submit("B")
        self.observe("candidate", "C")
        self.client.release.set()
        self.wait_until(lambda: not self.window._translate_worker._busy)
        self.panel.show_result.assert_not_called()
        self.assertEqual(self.window._deferred_translation[0], "B")
        self.observe("current", "B")
        self.assertEqual(self.panel.show_result.call_args.kwargs["corrected"], "B")
        self.assertEqual(len(self.client.messages), 2)

    def test_vl_result_is_compared_to_observed_ocr_not_model_corrected_text(self):
        self.cfg.set("recognition_mode", "vl")
        self.attach_monitor()

        def blocked_vision(prompt, image):
            self.client.vision_images.append(image)
            self.client.entered.set()
            if not self.client.release.wait(4):
                raise RuntimeError("Test did not release fake vision")
            return '{"corrected":"Model corrected English","translation":"视觉译文"}'

        with patch.object(self.client, "chat_vision", side_effect=blocked_vision):
            image = self.submit("OCR source A")
            self.wait_until(self.client.entered.is_set)
            self.observe("candidate", "OCR source B")
            self.client.release.set()
            self.wait_until(lambda: not self.window._translate_worker._busy)
            self.panel.show_result.assert_not_called()
            self.observe("current", "OCR source A")
        self.panel.show_result.assert_called_once_with(
            corrected="Model corrected English", translation="视觉译文", original_ocr="",
        )
        self.assertEqual(self.client.vision_images, [image])
        self.assertEqual(self.client.messages, [])
        self.assertEqual(self.ocr.images, [])

    def test_manual_vl_is_not_filtered_by_unavailable_monitor_observation(self):
        self.cfg.set("recognition_mode", "vl")
        self.attach_monitor()
        self.window._manual_translate()
        self.observe("unavailable")
        self.wait_until(lambda: self.panel.show_result.called)
        self.assertEqual(self.panel.show_result.call_args.kwargs["translation"], "图像翻译")
        self.assertIsNone(self.window._deferred_translation)
        self.assertEqual(len(self.client.vision_images), 1)
        self.assertEqual(self.ocr.images, [])

    def test_missing_dialogue_defers_active_result_until_same_dialogue_returns(self):
        self.attach_monitor()
        self.client.block = True
        self.submit("Dialogue before exploration")
        self.wait_until(self.client.entered.is_set)
        self.observe("unavailable")
        self.window._update_translation_progress()
        self.assertIn("等待对白", self.window._status_bar.currentMessage())
        self.assertIn("上条请求处理中", self.window._status_bar.currentMessage())
        self.client.release.set()
        self.wait_until(lambda: not self.window._translate_worker._busy)
        self.panel.show_result.assert_not_called()
        self.assertIn("未确认对白", self.window._status_bar.currentMessage())
        self.observe("current", "Dialogue before exploration")
        self.assertEqual(self.panel.show_result.call_count, 1)
        self.assertEqual(len(self.client.messages), 1)

    def test_previous_vl_error_is_not_presented_as_failure_of_the_new_candidate(self):
        self.cfg.set("recognition_mode", "vl")
        self.attach_monitor()

        def failed_vision(prompt, image):
            self.client.entered.set()
            if not self.client.release.wait(4):
                raise RuntimeError("Test did not release fake vision")
            raise RuntimeError("old request failed")

        with patch.object(self.client, "chat_vision", side_effect=failed_vision):
            self.submit("A")
            self.wait_until(self.client.entered.is_set)
            self.observe("candidate", "B")
            self.client.release.set()
            self.wait_until(lambda: not self.window._translate_worker._busy)
        self.panel.show_error.assert_not_called()
        self.observe("current", "A")
        self.assertIn("old request failed", self.panel.show_error.call_args.args[0])
        self.assertIsNone(self.window._deferred_translation)

    def test_explicit_manual_worker_request_survives_subsequent_filtered_frames(self):
        self.cfg.set("game", "profile", "genshin")
        self.cfg.set("game", "genshin", "use_glossary", False)
        self.window._on_config_changed()
        hud = Image.new("RGB", (32, 16))
        hud.info["text"] = "Lv. 90 19091 / 20706 Enter"
        self.client.block = True
        with patch("src.ui.main_window.prepare_genshin_dialogue",
                   return_value=SimpleNamespace(image=hud, detected=False)):
            self.window._start_watching()
            self.wait_until(lambda: self.window._watch_observation is not None)
            self.assertEqual(self.window._watch_observation.kind, "unavailable")
            self.window._manual_translate()
            self.wait_until(self.client.entered.is_set)
            captures = self.capture.call_count
            self.wait_until(lambda: self.capture.call_count >= captures + 2)
            self.assertEqual(self.window._watch_observation.kind, "unavailable")
            self.client.release.set()
            self.wait_until(lambda: self.panel.show_result.called)
        self.assertIsNone(self.window._deferred_translation)
        self.assertEqual(self.panel.show_result.call_args.kwargs["original_ocr"], hud.info["text"])
        self.assertEqual(len(self.ocr.images), 1)
        self.assertEqual(len(self.client.messages), 1)

    def test_retired_worker_observations_cannot_replace_current_session_state(self):
        self.ocr.block = True
        self.window._start_watching()
        old = self.window._watch_worker
        self.wait_until(self.ocr.entered.is_set)
        self.window._on_region_selected(SelectedRegion(40, 50, 60, 70))
        self.assertIn(old, self.window._retired_watch_workers)
        self.observe("candidate", "Current region")
        latest = self.window._watch_observation
        notice = self.window._status_bar.currentMessage()
        old.observation_changed.emit(WatchObservation("unavailable"))
        old.observation_changed.emit(WatchObservation("submitted", "Old region", manual=True))
        self.assertIs(self.window._watch_observation, latest)
        self.assertIsNone(self.window._watch_submission)
        self.assertEqual(self.window._status_bar.currentMessage(), notice)
        self.assertEqual(self.client.messages, [])

    def test_stopping_discards_deferred_result_before_a_new_session(self):
        self.defer_first_result()
        self.window._stop_watching()
        self.assertIsNone(self.window._deferred_translation)
        self.assertIsNone(self.window._watch_observation)
        self.attach_monitor()
        self.observe("current", "Original dialogue A.")
        self.panel.show_result.assert_not_called()
        self.assertEqual(len(self.client.messages), 1)

    def test_ocr_fluctuations_and_progress_leave_floating_subtitles_still(self):
        self.attach_monitor()
        with patch("src.ui.result_panel.ConfigManager", return_value=self.cfg):
            panel = ResultPanel()
        self.addCleanup(panel.close)
        self.window._result_panel = panel
        panels = (panel._chinese_panel, panel._english_panel, panel._combined_panel)

        def snapshot():
            return [(
                item._status_label.text(), item._status_label.isHidden(),
                item._loading_label.text(), item._loading_label.isHidden(), item.isHidden(),
                getattr(item, "_chinese_edit", None).toPlainText()
                if hasattr(item, "_chinese_edit") else "",
                getattr(item, "_english_edit", None).toPlainText()
                if hasattr(item, "_english_edit") else "",
            ) for item in panels]

        for split in (True, False):
            with self.subTest(split=split):
                panel.set_split_mode(split)
                panel.show_result("The previous dialogue.", "上一句译文。")
                before = snapshot()
                for _ in range(3):
                    for kind, text in (("candidate", "New line"), ("current", "New line."),
                                       ("unavailable", ""), ("empty", "")):
                        self.observe(kind, text)
                        self.app.processEvents()
                        self.assertEqual(snapshot(), before)
                panel.hide()
                self.observe("candidate", "Another line")
                self.assertFalse(panel.isVisible())
        self.assertEqual(self.client.messages, [])

        self.client.block = True
        self.submit("New line.")
        self.wait_until(lambda: "等待模型翻译" in self.window._status_bar.currentMessage())
        pending = snapshot()
        for kind, text in (("candidate", "New line"), ("unavailable", ""),
                           ("current", "New line.")):
            self.observe(kind, text)
            self.window._update_translation_progress()
            self.app.processEvents()
            self.assertEqual(snapshot(), pending)
        self.client.release.set()
        self.wait_until(lambda: not self.window._translate_worker._busy)
        self.assertEqual(panel._combined_panel._english_edit.toPlainText(), "New line.")
        self.assertEqual(panel._combined_panel._chinese_edit.toPlainText(), "翻译")
        self.assertEqual(len(self.client.messages), 1)

    def test_rebuilding_configuration_discards_deferred_result(self):
        self.defer_first_result()
        with patch("src.ui.main_window.WatchWorker.start"):
            self.window._on_config_changed()
        self.assertIsNone(self.window._deferred_translation)
        self.assertIsNone(self.window._watch_observation)
        self.observe("current", "Original dialogue A.")
        self.panel.show_result.assert_not_called()
        self.assertEqual(len(self.client.messages), 1)


if __name__ == "__main__":
    unittest.main()
