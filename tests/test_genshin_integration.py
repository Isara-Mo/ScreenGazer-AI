"""Genshin capture integration with fake windows, local OCR, API and config."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_main_window as fixture
from tests.test_game_capture import dialogue, exploration_hud
from PIL import Image
from PySide6.QtWidgets import QApplication

from src.core.capture import WindowInfo
from src.core.game_capture import GENSHIN_DIALOGUE_REGION
from src.ui.main_window import MainWindow


class GenshinIntegrationTests(unittest.TestCase):
    # Reuse the offline fixture without inheriting/rerunning its test methods.
    setUp = fixture.MainWindowIntegrationTests.setUp
    tearDown = fixture.MainWindowIntegrationTests.tearDown
    wait_until = fixture.MainWindowIntegrationTests.wait_until
    capture_image = staticmethod(fixture.MainWindowIntegrationTests.capture_image)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def select_game_window(self):
        target = WindowInfo("Genshin Impact", 12345, 120, 60, 1920, 1080)
        self.window._window_combo.addItem(target.title)
        self.window._window_combo.setCurrentText(target.title)
        return target

    def enable_adaptive(self):
        self.cfg.set("game", "profile", "genshin")
        self.cfg.set("game", "genshin", "use_glossary", False)
        self.window._on_config_changed()

    def test_one_click_sets_wide_region_and_saves_window_ratios(self):
        target = self.select_game_window()
        self.cfg.set("game", "genshin", "use_glossary", False)
        with patch("src.ui.main_window.find_window_by_title", return_value=target):
            self.window._use_genshin_region()
        region = self.window._capture_region
        rx, ry, rw, rh = GENSHIN_DIALOGUE_REGION
        expected = [
            target.left + int(target.width * rx), target.top + int(target.height * ry),
            int(target.width * rw), int(target.height * rh),
        ]
        self.assertEqual(self.cfg.get("capture", "region"), expected)
        self.assertEqual(self.cfg.get("capture", "relative_region"), [rx, ry, rw, rh])
        self.assertEqual(self.cfg.get("capture", "window_title"), target.title)
        self.assertEqual(self.cfg.get("game", "profile"), "genshin")
        self.assertTrue(self.cfg.get("game", "genshin", "adaptive_dialogue"))
        self.assertEqual(region.hwnd, target.hwnd)
        self.assertGreater(region.width, target.width * 0.8)
        self.cfg.save.assert_called()

        resized = WindowInfo(target.title, target.hwnd, 240, 130, 1280, 720)
        with patch("src.core.capture.get_window_info", return_value=resized):
            monitor = region.to_mss_monitor()
        self.assertEqual(monitor, {
            "left": int(resized.left + rx * resized.width),
            "top": int(resized.top + ry * resized.height),
            "width": int(rw * resized.width), "height": int(rh * resized.height),
        })

    def test_missing_window_does_not_change_previous_region_or_profile(self):
        original = self.window._capture_region
        saved = self.cfg.get_all()
        with patch("src.ui.main_window.QMessageBox.information") as information:
            self.window._use_genshin_region()
        information.assert_called_once()
        self.assertIs(self.window._capture_region, original)
        self.assertEqual(self.cfg.get_all(), saved)
        self.cfg.save.assert_not_called()

    def test_closed_selected_window_keeps_previous_region(self):
        self.select_game_window()
        original = self.window._capture_region
        with patch("src.ui.main_window.find_window_by_title", return_value=None), patch(
            "src.ui.main_window.QMessageBox.information"
        ) as information:
            self.window._use_genshin_region()
        information.assert_called_once()
        self.assertIs(self.window._capture_region, original)
        self.cfg.save.assert_not_called()

    def test_generic_manual_and_monitor_leave_capture_unchanged(self):
        self.assertEqual(self.cfg.get("game", "profile"), "generic")
        with patch("src.ui.main_window.prepare_genshin_dialogue") as prepare:
            self.window._manual_translate()
            self.wait_until(lambda: self.panel.show_result.called)
            self.window._rebuild_watch_worker()
            image = self.window._watch_worker._capture_fn()
        prepare.assert_not_called()
        self.assertEqual(self.ocr.images[0].info["text"], "region 1")
        self.assertEqual(image.info["text"], "region 1")
        self.assertEqual(self.client.messages, [[{"role": "user", "content": "region 1"}]])

    def test_manual_and_running_watcher_share_preprocessing_without_second_ocr(self):
        self.enable_adaptive()
        prepared = Image.new("RGB", (16, 8))
        prepared.info["text"] = "A complete dialogue."
        with patch(
            "src.ui.main_window.prepare_genshin_dialogue",
            return_value=SimpleNamespace(image=prepared, detected=True),
        ) as prepare:
            self.window._manual_translate()
            self.wait_until(lambda: self.panel.show_result.called)
            self.assertEqual(len(self.ocr.images), 1)
            self.assertIs(self.ocr.images[0], prepared)
            prepare.assert_called_once()

            self.ocr.images.clear()
            self.ocr.threads.clear()
            self.panel.show_result.reset_mock()
            self.window._start_watching()
            watcher = self.window._watch_worker
            watcher.force_trigger()
            self.wait_until(lambda: self.panel.show_result.called)
            self.window._stop_watching()
            self.wait_until(lambda: not self.window._retired_watch_workers)

        self.assertTrue(self.ocr.images)
        self.assertTrue(all(image is prepared for image in self.ocr.images))
        self.assertTrue(all(thread is watcher for thread in self.ocr.threads))
        self.assertEqual(self.panel.show_result.call_args.kwargs["original_ocr"], "A complete dialogue.")
        self.assertEqual(len(self.client.messages), 2)

    def check_automatic_dialogue_gate(self, mode):
        self.cfg.set("recognition_mode", mode)
        self.enable_adaptive()
        hud = exploration_hud()
        initial, _, _ = dialogue(title=True, lines=2)
        initial.info["text"] = "We shall meet again in Liyue."
        following = initial.copy()
        following.info["text"] = "I have 19091 / 20706 coins at Lv. 90."
        frame = {"image": hud}
        self.capture.side_effect = lambda region: frame["image"]
        self.window._start_watching()
        self.wait_until(lambda: self.capture.call_count >= 3)
        self.assertEqual(self.window._watch_observation.kind, "unavailable")
        self.assertEqual(self.ocr.images, [])
        self.assertEqual(self.client.messages, [])
        self.assertEqual(self.client.vision_images, [])

        frame["image"] = initial
        self.wait_until(lambda: self.panel.show_result.call_count == 1)
        frame["image"] = hud
        self.wait_until(lambda: self.window._watch_observation.kind == "unavailable")
        samples = len(self.ocr.images)
        captures = self.capture.call_count
        self.wait_until(lambda: self.capture.call_count >= captures + 3)
        self.assertEqual(len(self.ocr.images), samples)
        self.assertEqual(self.panel.show_result.call_count, 1)

        frame["image"] = following
        self.wait_until(lambda: self.panel.show_result.call_count == 2)
        self.window._stop_watching()
        self.wait_until(lambda: not self.window._retired_watch_workers)
        # Legitimate dialogue mentioning levels or health-like fractions survives.
        self.assertEqual(self.ocr.images[-1].info["text"], following.info["text"])
        if mode == "ocr":
            self.assertEqual(self.panel.show_result.call_args.kwargs["original_ocr"],
                             following.info["text"])
        self.assertTrue(all(image.size != hud.size for image in self.ocr.images))
        self.assertEqual(len(self.client.messages), 2 if mode == "ocr" else 0)
        self.assertEqual(len(self.client.vision_images), 2 if mode == "vl" else 0)
        self.cfg.save.assert_not_called()

    def test_ocr_monitor_waits_on_hud_and_resumes_after_dialogue_returns(self):
        self.check_automatic_dialogue_gate("ocr")

    def test_vision_monitor_waits_on_hud_and_resumes_after_dialogue_returns(self):
        self.check_automatic_dialogue_gate("vl")

    def test_manual_translation_during_monitoring_can_read_unconfirmed_frame(self):
        self.enable_adaptive()
        hud = exploration_hud()
        self.capture.side_effect = lambda region: hud
        self.window._start_watching()
        watcher = self.window._watch_worker
        self.wait_until(lambda: "等待原神对白" in self.window._status_bar.currentMessage())
        self.window._manual_translate()
        self.wait_until(lambda: self.panel.show_result.called)
        self.window._stop_watching()
        self.wait_until(lambda: not self.window._retired_watch_workers)
        self.assertEqual(len(self.ocr.images), 1)
        self.assertEqual(self.ocr.images[0].tobytes(), hud.tobytes())
        self.assertIs(self.ocr.threads[0], watcher)
        self.assertEqual(len(self.client.messages), 1)
        self.assertEqual(self.panel.show_result.call_args.kwargs["original_ocr"], hud.info["text"])

    def test_disabling_adaptation_bypasses_crop_in_both_paths(self):
        self.enable_adaptive()
        self.cfg.set("game", "genshin", "adaptive_dialogue", False)
        with patch("src.ui.main_window.prepare_genshin_dialogue") as prepare:
            self.window._manual_translate()
            self.wait_until(lambda: self.panel.show_result.called)
            self.window._rebuild_watch_worker()
            self.window._watch_worker._capture_fn()
        prepare.assert_not_called()
        self.assertEqual(self.ocr.images[0].info["text"], "region 1")

    def test_one_click_replacement_discards_old_manual_translation(self):
        target = self.select_game_window()
        self.cfg.set("game", "genshin", "use_glossary", False)
        self.client.block = True
        self.window._manual_translate()
        self.wait_until(self.client.entered.is_set)
        with patch("src.ui.main_window.find_window_by_title", return_value=target):
            self.window._use_genshin_region()
        self.client.release.set()
        self.wait_until(lambda: not self.window._translate_worker._busy)
        self.panel.show_result.assert_not_called()

    def test_startup_restores_saved_window_binding(self):
        target = WindowInfo("Genshin Impact", 23456, 240, 180, 1280, 720)
        relative = [0.05, 0.65, 0.90, 0.30]
        self.cfg.set("capture", "window_title", target.title)
        self.cfg.set("capture", "relative_region", relative)
        with patch("src.ui.main_window.find_window_by_title", return_value=target) as find, patch.object(
            MainWindow, "_rebuild_components"
        ), patch.object(MainWindow, "_register_hotkey"):
            restored = MainWindow()
        self.addCleanup(restored.deleteLater)
        find.assert_called_once_with(target.title)
        self.assertIs(restored._target_window, target)
        self.assertEqual(restored._capture_region.hwnd, target.hwnd)
        self.assertEqual([
            restored._capture_region.rel_x, restored._capture_region.rel_y,
            restored._capture_region.rel_w, restored._capture_region.rel_h,
        ], relative)


if __name__ == "__main__":
    unittest.main()
