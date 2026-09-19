"""Deterministic regressions: no screen capture, local OCR binary or API calls."""

import unittest
from unittest.mock import patch

from PIL import Image

from src.core.watcher import ChangeWatcher, normalize_ocr_text, resolve_watch_settings


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.image = Image.new("RGB", (32, 32), "white")
        self.text = "Hello world."
        self.frame_hash = 0
        self.available = True
        self.ocr_cost = 0.0
        self.events = []
        self.hash_mock = patch("src.core.watcher.imagehash.phash", side_effect=lambda *a, **k: self.frame_hash)
        self.hash_mock.start()
        self.addCleanup(self.hash_mock.stop)
        self.watcher = self.make_watcher()

    def make_watcher(self, **settings):
        def ocr(image):
            self.clock.now += self.ocr_cost
            return self.text

        watcher = ChangeWatcher(
            lambda: self.image if self.available else None,
            ocr,
            lambda image, text: self.events.append((image, text)),
            clock=self.clock,
            **settings,
        )
        watcher.start()
        return watcher

    def tick(self, at, text=None, background=None):
        self.clock.now = at
        if text is not None:
            self.text = text
        if background is not None:
            self.frame_hash = background
        return self.watcher.tick()

    def settle_initial(self, text="Hello world."):
        self.tick(0, text)
        self.tick(0.4)
        self.tick(0.8)
        self.assertEqual(len(self.events), 1)

    def test_first_static_frame_is_translated_and_keeps_raw_ocr(self):
        self.settle_initial("Hello\nworld.")
        self.assertIs(self.events[0][0], self.image)
        self.assertEqual(self.events[0][1], "Hello\nworld.")

    def test_continuously_animated_background_only_translates_once(self):
        for index in range(60):
            self.tick(index * 0.25, background=index * 16)
        self.assertEqual([text for _, text in self.events], ["Hello world."])
        self.assertGreater(self.watcher.stats["ocr_samples"], 20)

    def test_identical_image_hash_does_not_hide_real_text_change(self):
        self.settle_initial("Take 10 coins.")
        self.tick(1.5, "Take 11 coins.")
        self.tick(1.9)
        self.tick(2.3)
        self.assertEqual([text for _, text in self.events], ["Take 10 coins.", "Take 11 coins."])

    def test_short_words_and_negation_are_not_fuzzy_deduplicated(self):
        self.settle_initial("Go")
        self.tick(1.5, "No")
        self.tick(1.9)
        self.tick(2.3)
        self.tick(3.0, "Do not go")
        self.tick(3.4)
        self.tick(3.8)
        self.assertEqual([text for _, text in self.events], ["Go", "No", "Do not go"])

    def test_layout_and_width_variation_does_not_retranslate(self):
        self.settle_initial("Ｈｅｌｌｏ，\nworld！")
        for index in range(1, 10):
            self.tick(0.8 + index * 0.3, "Hello, world !", background=index * 16)
        self.assertEqual(len(self.events), 1)

    def test_brief_ocr_noise_does_not_retranslate(self):
        self.settle_initial("Take 10 coins.")
        self.tick(1.5, "Take 1O coins.")
        self.tick(1.8, "Take 10 coins.")
        self.tick(2.3)
        self.tick(3.0)
        self.assertEqual(len(self.events), 1)

    def test_typewriter_only_emits_after_text_stops_growing(self):
        for index, text in enumerate(["H", "He", "Hel", "Hell", "Hello", "Hello w", "Hello wo", "Hello world."]):
            self.tick(index * 0.25, text, background=index * 16)
            self.assertEqual(self.events, [])
        self.tick(2.0)
        self.tick(2.25)
        self.assertEqual(self.events, [])
        self.tick(2.5)
        self.assertEqual([text for _, text in self.events], ["Hello world."])

    def test_stable_preset_waits_through_slower_typewriter_pauses(self):
        self.watcher = self.make_watcher(preset="stable")
        for index, text in enumerate(["H", "He", "Hel"]):
            self.tick(index * 0.8, text, background=index * 16)
            self.tick(index * 0.8 + 0.5)
            self.assertEqual(self.events, [])
        self.tick(2.6)
        self.assertEqual([text for _, text in self.events], ["Hel"])

    def test_cooldown_retains_pending_text_until_it_can_emit(self):
        self.watcher = self.make_watcher(cooldown_seconds=2.5)
        self.settle_initial("First line")
        self.tick(1.5, "Second line")
        self.tick(1.9)
        status = self.tick(2.3)
        self.assertIn("冷却", status)
        self.assertEqual(len(self.events), 1)
        self.tick(3.4)
        self.assertEqual([text for _, text in self.events], ["First line", "Second line"])

    def test_empty_ocr_breaks_consecutive_stability_and_never_emits(self):
        self.tick(0, "Hello")
        self.tick(0.4, " ", background=16)
        self.tick(0.8, "Hello", background=32)
        self.tick(1.2)
        self.assertEqual(self.events, [])
        self.tick(1.6)
        self.assertEqual([text for _, text in self.events], ["Hello"])
        self.text = ""
        self.watcher.force_trigger()
        self.assertEqual(len(self.events), 1)

    def test_missing_capture_breaks_consecutive_stability(self):
        self.tick(0)
        self.available = False
        self.tick(0.4)
        self.available = True
        self.tick(0.8)
        self.tick(1.2)
        self.assertEqual(self.events, [])
        self.tick(1.6)
        self.assertEqual(len(self.events), 1)

    def test_static_idle_scene_still_gets_periodic_ocr(self):
        self.settle_initial()
        initial_samples = self.watcher.stats["ocr_samples"]
        for index in range(1, 60):
            self.tick(0.8 + index * 0.3)
        self.assertGreater(self.watcher.stats["ocr_samples"], initial_samples + 8)
        self.assertLess(self.watcher.stats["ocr_samples"], initial_samples + 55)
        self.assertGreater(self.watcher.next_poll_interval, 0.3)
        self.assertLessEqual(self.watcher.next_poll_interval, 0.9 + 1e-9)
        self.assertEqual(len(self.events), 1)

    def test_auto_throttles_slow_ocr_and_reports_observable_timings(self):
        self.ocr_cost = 0.8
        status = self.tick(0)
        self.assertAlmostEqual(self.watcher.stats["ocr_duration"], 0.8)
        self.assertAlmostEqual(self.watcher.next_poll_interval, 1.2)
        self.assertIn("OCR 0.80s", status)
        self.ocr_cost = 0.01
        self.tick(2)
        self.assertLess(self.watcher.next_poll_interval, 1.2)

    def test_model_cold_start_does_not_add_tens_of_seconds_of_wait(self):
        self.ocr_cost = 20.0
        self.tick(0)
        self.assertLessEqual(self.watcher.next_poll_interval, 1.5)
        self.ocr_cost = 0.01
        self.tick(21.5)
        self.assertLessEqual(self.watcher.next_poll_interval, 1.5)

    def test_ocr_error_breaks_consecutive_samples(self):
        self.tick(0)
        with patch.object(self.watcher, "_quick_ocr", side_effect=RuntimeError("OCR failed")):
            with self.assertRaises(RuntimeError):
                self.tick(0.4)
        self.tick(0.8)
        self.assertEqual(self.events, [])
        self.tick(1.2)
        self.assertEqual(self.events, [])
        self.tick(1.6)
        self.assertEqual(len(self.events), 1)

    def assert_recovery_requires_fresh_samples(self):
        self.tick(0.8)
        self.assertEqual(self.events, [])
        self.tick(1.2)
        self.assertEqual(self.events, [])
        self.tick(1.6)
        self.assertEqual(len(self.events), 1)

    def test_capture_error_breaks_consecutive_samples(self):
        self.tick(0)
        with patch.object(self.watcher, "_capture", side_effect=RuntimeError("Capture failed")):
            with self.assertRaises(RuntimeError):
                self.tick(0.4)
        self.assert_recovery_requires_fresh_samples()

    def test_hash_error_breaks_consecutive_samples(self):
        self.tick(0)
        with patch("src.core.watcher.imagehash.phash", side_effect=RuntimeError("Hash failed")):
            with self.assertRaises(RuntimeError):
                self.tick(0.4)
        self.assert_recovery_requires_fresh_samples()

    def test_forced_capture_error_breaks_consecutive_samples(self):
        self.tick(0)
        self.clock.now = 0.4
        with patch.object(self.watcher, "_capture", side_effect=RuntimeError("Capture failed")):
            with self.assertRaises(RuntimeError):
                self.watcher.force_trigger()
        self.assert_recovery_requires_fresh_samples()

    def test_forced_missing_capture_breaks_consecutive_samples(self):
        self.tick(0)
        self.clock.now = 0.4
        self.available = False
        self.watcher.force_trigger()
        self.available = True
        self.assert_recovery_requires_fresh_samples()

    def test_forced_empty_ocr_breaks_consecutive_samples(self):
        self.tick(0)
        self.clock.now = 0.4
        with patch.object(self.watcher, "_quick_ocr", return_value="  "):
            self.watcher.force_trigger()
        self.assert_recovery_requires_fresh_samples()

    def test_forced_ocr_error_breaks_consecutive_samples(self):
        self.tick(0)
        self.clock.now = 0.4
        with patch.object(self.watcher, "_quick_ocr", side_effect=RuntimeError("OCR failed")):
            with self.assertRaises(RuntimeError):
                self.watcher.force_trigger()
        self.assert_recovery_requires_fresh_samples()

    def test_capture_error_does_not_erase_previous_translation_deduplication(self):
        self.settle_initial()
        with patch.object(self.watcher, "_capture", side_effect=RuntimeError("Capture failed")):
            with self.assertRaises(RuntimeError):
                self.tick(1.2)
        self.tick(1.6)
        self.tick(2.0)
        self.tick(2.4)
        self.assertEqual(len(self.events), 1)

    def test_force_bypasses_stability_and_deduplication(self):
        self.settle_initial()
        self.watcher.force_trigger()
        self.assertEqual(len(self.events), 2)

    def test_settings_updates_preserve_translation_deduplication(self):
        self.settle_initial()
        self.watcher.update_settings(preset="fast")
        self.tick(2.0)
        self.tick(2.4)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.watcher.poll_interval, 0.2)

    def test_presets_resolve_and_custom_retains_manual_values(self):
        self.assertEqual(resolve_watch_settings("fast", 4, 10, 20)["poll_interval"], 0.2)
        self.assertEqual(resolve_watch_settings("unknown")["preset"], "auto")
        custom = resolve_watch_settings("custom", 0.7, 4, 12)
        self.assertEqual((custom["poll_interval"], custom["stability_count"], custom["hash_threshold"]), (0.7, 4, 12))

    def test_normalization_keeps_semantic_characters(self):
        for before, after in [("x²", "x2"), ("can not", "can"), ("10", "11"), ("No", "Go"), ("US", "us"), ("ready?", "ready!")]:
            with self.subTest(before=before, after=after):
                self.assertNotEqual(normalize_ocr_text(before), normalize_ocr_text(after))


if __name__ == "__main__":
    unittest.main()


