"""Deterministic regressions: no screen capture, local OCR binary or API calls."""

import unittest
from unittest.mock import patch

from PIL import Image

from src.core.watcher import ChangeWatcher, WatchObservation, WatchTiming, normalize_ocr_text, resolve_watch_settings


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

    def test_observations_identify_candidate_submission_and_current_text(self):
        observations = []
        self.watcher = self.make_watcher(observation_callback=observations.append)
        self.settle_initial("Ｈｅｌｌｏ\nworld !")
        self.assertEqual(observations, [
            WatchObservation("candidate", "Hello world!"),
            WatchObservation("submitted", "Hello world!"),
        ])
        self.tick(1.5)
        self.tick(2.0)
        self.assertEqual(observations[-1], WatchObservation("current", "Hello world!"))
        self.assertEqual(len(observations), 3)

    def test_submission_observation_precedes_translation_and_keeps_raw_ocr(self):
        sequence = []
        self.watcher = self.make_watcher(observation_callback=lambda event: sequence.append(event))
        self.watcher._on_stable = lambda image, text: sequence.append(("translate", text))
        self.text = "Manual\ntext !"
        self.watcher.force_trigger()
        self.watcher.force_trigger()
        self.assertEqual(sequence, [
            WatchObservation("submitted", "Manual text!", manual=True),
            ("translate", "Manual\ntext !"),
            WatchObservation("submitted", "Manual text!", manual=True),
            ("translate", "Manual\ntext !"),
        ])

    def test_unavailable_and_empty_observations_are_distinct_and_deduplicated(self):
        observations = []
        self.watcher = self.make_watcher(observation_callback=observations.append)
        self.available = False
        self.tick(0)
        self.tick(0.4)
        self.available = True
        self.tick(0.8, "")
        self.tick(1.2)
        self.available = False
        self.tick(1.6)
        self.assertEqual(observations, [
            WatchObservation("unavailable"), WatchObservation("empty"),
            WatchObservation("unavailable"),
        ])
        self.assertEqual(self.events, [])

    def test_manual_empty_and_unavailable_observations_keep_request_origin(self):
        observations = []
        self.watcher = self.make_watcher(observation_callback=observations.append)
        self.available = False
        self.watcher.force_trigger()
        self.available = True
        self.text = " "
        self.watcher.force_trigger()
        self.assertEqual(observations, [
            WatchObservation("unavailable", manual=True),
            WatchObservation("empty", manual=True),
        ])

    def test_transient_candidate_reports_return_to_current_without_new_api(self):
        observations = []
        self.watcher = self.make_watcher(observation_callback=observations.append)
        self.settle_initial("Take 10 coins.")
        self.tick(1.5, "Take 1O coins.")
        self.tick(1.8, "Take 10 coins.")
        self.tick(2.3)
        self.assertEqual(observations[-2:], [
            WatchObservation("candidate", "Take 1O coins."),
            WatchObservation("current", "Take 10 coins."),
        ])
        self.assertEqual([text for _, text in self.events], ["Take 10 coins."])

    def test_hash_skip_does_not_report_unobserved_text(self):
        observations = []
        self.watcher = self.make_watcher(observation_callback=observations.append)
        self.settle_initial()
        self.tick(1.5)
        before = list(observations)
        self.tick(1.51, "Not sampled yet")
        self.assertEqual(observations, before)
        self.tick(2.0)
        self.assertEqual(observations[-1], WatchObservation("candidate", "Not sampled yet"))

    def test_restart_resets_observation_deduplication(self):
        observations = []
        self.watcher = self.make_watcher(observation_callback=observations.append)
        self.available = False
        self.tick(0)
        self.watcher.stop()
        self.watcher.start()
        self.tick(0.4)
        self.assertEqual(observations, [WatchObservation("unavailable")] * 2)

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

    def test_filtered_capture_skips_hash_ocr_and_translation_in_every_preset(self):
        self.available = False
        for preset in ("auto", "fast", "stable", "custom"):
            with self.subTest(preset=preset):
                self.watcher = self.make_watcher(
                    preset=preset, empty_capture_status="等待原神对白",
                )
                with patch.object(self.watcher, "_quick_ocr") as ocr, patch(
                    "src.core.watcher.imagehash.phash"
                ) as hash_image:
                    for at in (0, 0.4, 0.8, 5.0):
                        self.assertIn("等待原神对白", self.tick(at))
                ocr.assert_not_called()
                hash_image.assert_not_called()
                self.assertEqual(self.watcher.stats["ocr_samples"], 0)
                self.assertEqual(self.events, [])

    def test_dialogue_resumes_after_filtered_capture_with_fresh_stability(self):
        self.watcher = self.make_watcher(empty_capture_status="等待原神对白")
        self.settle_initial("First dialogue")
        self.available = False
        samples = self.watcher.stats["ocr_samples"]
        self.assertIn("等待原神对白", self.tick(1.2, "Lv. 90 19091/20706 Enter"))
        self.tick(1.6)
        self.assertEqual(self.watcher.stats["ocr_samples"], samples)
        self.available = True
        self.tick(2.0, "Next dialogue")
        self.tick(2.4)
        self.assertEqual([text for _, text in self.events], ["First dialogue"])
        self.tick(2.8)
        self.assertEqual([text for _, text in self.events], ["First dialogue", "Next dialogue"])

    def test_filtered_capture_preserves_previous_translation_deduplication(self):
        self.settle_initial()
        self.available = False
        self.tick(1.2)
        self.available = True
        for at in (1.6, 2.0, 2.4):
            self.tick(at)
        self.assertEqual(len(self.events), 1)

    def test_manual_capture_bypasses_filter_and_retains_automatic_deduplication(self):
        manual_image = Image.new("RGB", (48, 24), "blue")
        self.watcher = self.make_watcher(
            manual_capture_fn=lambda: manual_image,
            empty_capture_status="等待原神对白",
        )
        self.available = False
        self.assertIn("等待原神对白", self.tick(0))
        self.assertIn("已手动触发翻译", self.watcher.force_trigger())
        self.assertEqual(self.events, [(manual_image, "Hello world.")])
        # Manual translation must not permanently reopen automatic capture.
        self.assertIn("等待原神对白", self.tick(0.4))
        self.assertEqual(self.watcher.stats["ocr_samples"], 1)
        self.available = True
        for at in (0.8, 1.2, 1.6):
            self.tick(at)
        self.assertEqual(self.events, [(manual_image, "Hello world.")])

    def test_missing_manual_capture_uses_missing_region_status_and_clears_candidate(self):
        self.watcher = self.make_watcher(
            manual_capture_fn=lambda: None,
            empty_capture_status="等待原神对白",
        )
        self.tick(0)
        self.clock.now = 0.4
        status = self.watcher.force_trigger()
        self.assertIn("未配置捕获区域", status)
        self.assertNotIn("等待原神对白", status)
        self.assert_recovery_requires_fresh_samples()

    def test_static_idle_scene_still_gets_periodic_ocr(self):
        self.settle_initial()
        initial_samples = self.watcher.stats["ocr_samples"]
        for index in range(1, 60):
            self.tick(0.8 + index * 0.3)
        self.assertGreater(self.watcher.stats["ocr_samples"], initial_samples + 8)
        self.assertLess(self.watcher.stats["ocr_samples"], initial_samples + 55)
        self.assertGreater(self.watcher.stats["ocr_recheck_interval"], 0.3)
        self.assertLessEqual(self.watcher.next_poll_interval, 0.3 + 1e-9)
        self.assertEqual(len(self.events), 1)

    def drive_until_translation(self, max_ticks=20):
        for _ in range(max_ticks):
            self.watcher.tick()
            if self.events:
                return self.clock.now
            self.clock.now += self.watcher.next_poll_interval
        self.fail("stable text did not translate within the sampling budget")

    def test_auto_slow_ocr_does_not_stack_a_second_ocr_duration_of_wait(self):
        self.ocr_cost = 0.8
        status = self.tick(0)
        self.assertAlmostEqual(self.watcher.stats["ocr_duration"], 0.8)
        self.assertAlmostEqual(self.watcher.next_poll_interval, 0.15)
        self.assertIn("OCR 0.80s", status)
        self.clock.now += self.watcher.next_poll_interval
        triggered_at = self.drive_until_translation()
        self.assertAlmostEqual(triggered_at, 1.75)
        self.assertEqual(self.watcher.stats["ocr_samples"], 2)

    def test_stable_and_custom_cadence_includes_ocr_runtime(self):
        for settings, cost, expected_time in (
            ({"preset": "stable"}, 0.8, 2.7),
            ({"preset": "custom", "poll_interval": 0.75, "stability_count": 3}, 0.4, 1.9),
        ):
            with self.subTest(settings=settings):
                self.clock.now = 0
                self.events.clear()
                self.ocr_cost = cost
                self.watcher = self.make_watcher(**settings)
                triggered_at = self.drive_until_translation()
                self.assertAlmostEqual(triggered_at, expected_time)
                self.assertEqual(self.watcher.stats["ocr_samples"], 3)

    def test_capture_processing_time_is_part_of_the_sampling_cadence(self):
        self.watcher = self.make_watcher(preset="stable")
        self.ocr_cost = 0.05

        def capture():
            self.clock.now += 0.2
            return self.image

        with patch.object(self.watcher, "_capture", side_effect=capture):
            triggered_at = self.drive_until_translation()
        self.assertAlmostEqual(triggered_at, 1.25)
        self.assertEqual(self.watcher.stats["ocr_samples"], 3)

    def test_settle_deadline_avoids_a_sample_just_before_text_is_ready(self):
        self.ocr_cost = 0.05
        triggered_at = self.drive_until_translation()
        self.assertAlmostEqual(triggered_at, 0.7)
        self.assertEqual(self.watcher.stats["ocr_samples"], 3)

    def test_long_idle_dialogue_return_keeps_fast_capture_and_fresh_confirmation(self):
        self.settle_initial("First dialogue")
        self.available = False
        self.tick(60)
        self.assertLessEqual(self.watcher.next_poll_interval, 0.3)
        self.clock.now += self.watcher.next_poll_interval
        self.available = True
        self.text = "New dialogue"
        self.events.clear()
        self.ocr_cost = 0.05
        self.watcher.tick()
        self.assertEqual(self.events, [])
        self.clock.now += self.watcher.next_poll_interval
        self.assertLessEqual(self.drive_until_translation(), 61.01)

    def test_idle_ocr_deadline_does_not_wait_an_extra_capture_interval(self):
        self.settle_initial()
        self.tick(60)
        # The fully idle OCR deadline is 60.9. A capture at 60.85 should
        # wake for it, rather than sleeping another full 0.3 seconds.
        before = self.watcher.stats["ocr_samples"]
        self.tick(60.85)
        self.assertEqual(self.watcher.stats["ocr_samples"], before)
        self.assertAlmostEqual(self.watcher.next_poll_interval, 0.05)
        self.clock.now += self.watcher.next_poll_interval
        self.watcher.tick()
        self.assertEqual(self.watcher.stats["ocr_samples"], before + 1)

    def test_model_cold_start_does_not_add_tens_of_seconds_of_wait(self):
        self.ocr_cost = 20.0
        self.tick(0)
        self.assertLessEqual(self.watcher.next_poll_interval, 0.15)
        self.ocr_cost = 0.01
        self.clock.now += self.watcher.next_poll_interval
        self.assertAlmostEqual(self.drive_until_translation(), 20.16)
        self.assertEqual(self.watcher.stats["ocr_samples"], 2)

    def test_expensive_second_ocr_does_not_fake_a_stable_capture_interval(self):
        self.tick(0)
        self.ocr_cost = 2.0
        self.tick(0.1)
        self.assertEqual(self.events, [])
        self.ocr_cost = 0.01
        self.clock.now += self.watcher.next_poll_interval
        self.watcher.tick()
        self.assertEqual(len(self.events), 1)

    def test_progress_is_emitted_before_ocr_and_never_for_filtered_frames(self):
        progress = []
        self.watcher = self.make_watcher(progress_callback=progress.append)
        self.available = False
        self.tick(0)
        self.assertEqual(progress, [])
        self.available = True
        with patch.object(self.watcher, "_quick_ocr", side_effect=lambda image: (
            self.assertIn("首次加载", progress[-1]) or "First text"
        )):
            self.tick(0.3)
        self.tick(0.6)
        self.assertEqual(progress[-1], "本地 OCR 识别中")

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


class WatchTimingTests(unittest.TestCase):
    """Per-dialogue timing excludes idle history and measures repeated work."""

    def setUp(self):
        self.clock = FakeClock()
        self.image = Image.new("RGB", (32, 32), "white")
        self.capture_cost = 0.02
        self.ocr_cost = 0.05
        self.text = "A new dialogue."
        self.observations = []
        self.hash_mock = patch("src.core.watcher.imagehash.phash", return_value=0)
        self.hash_mock.start()
        self.addCleanup(self.hash_mock.stop)

        def capture():
            self.clock.now += self.capture_cost
            return self.image

        def ocr(image):
            self.clock.now += self.ocr_cost
            return self.text

        self.watcher = ChangeWatcher(
            capture, ocr, lambda image, text: None,
            clock=self.clock, observation_callback=self.observations.append,
        )
        self.watcher.start()

    def tick(self, at, text=None):
        self.clock.now = at
        if text is not None:
            self.text = text
        return self.watcher.tick()

    def submitted(self):
        return [event.timing for event in self.observations if event.kind == "submitted"]

    def test_multiple_samples_measure_capture_ocr_and_overlapping_stability(self):
        for at in (10.0, 10.3, 10.65):
            self.tick(at)
        timing, = self.submitted()
        self.assertAlmostEqual(timing.started_at, 10.0)
        self.assertAlmostEqual(timing.submitted_at, 10.72)
        self.assertAlmostEqual(timing.capture_seconds, 0.06)
        self.assertAlmostEqual(timing.ocr_seconds, 0.15)
        self.assertEqual(timing.ocr_samples, 3)
        self.assertAlmostEqual(timing.stable_seconds, 0.65)
        elapsed = timing.submitted_at - timing.started_at
        self.assertAlmostEqual(elapsed - timing.capture_seconds - timing.ocr_seconds, 0.51)
        self.assertTrue(all(event.timing is None for event in self.observations
                            if event.kind != "submitted"))
        # Timing must not change the identity/deduplication of an observation.
        self.assertEqual(self.observations[-1], WatchObservation("submitted", self.text))

    def test_growing_candidate_keeps_episode_work_but_restarts_stability(self):
        self.tick(10.0, "A new")
        self.tick(10.3, "A new dialogue.")
        self.tick(10.6)
        self.tick(10.95)
        timing, = self.submitted()
        self.assertAlmostEqual(timing.started_at, 10.0)
        self.assertAlmostEqual(timing.submitted_at, 11.02)
        self.assertEqual(timing.ocr_samples, 4)
        self.assertAlmostEqual(timing.capture_seconds, 0.08)
        self.assertAlmostEqual(timing.ocr_seconds, 0.20)
        self.assertAlmostEqual(timing.stable_seconds, 0.65)

    def test_return_to_translated_text_discards_noise_and_idle_time(self):
        for at in (0.0, 0.3, 0.65):
            self.tick(at)
        self.tick(2.0, "A new dial0gue.")
        self.tick(2.3, "A new dialogue.")
        for at in (100.0, 100.3, 100.65):
            self.tick(at, "Another dialogue.")
        first, second = self.submitted()
        self.assertAlmostEqual(second.started_at, 100.0)
        self.assertEqual(second.ocr_samples, 3)
        self.assertAlmostEqual(second.ocr_seconds, 0.15)
        self.assertAlmostEqual(first.started_at, 0.0)

    def test_missing_empty_or_failed_sample_restarts_timing(self):
        for failure in ("empty", "missing", "capture", "ocr", "hash"):
            with self.subTest(failure=failure):
                self.watcher.start()
                self.observations.clear()
                self.tick(0.0, "A new dialogue.")
                if failure == "empty":
                    self.tick(0.3, "")
                elif failure == "missing":
                    with patch.object(self.watcher, "_capture", return_value=None):
                        self.tick(0.3)
                else:
                    target = {"capture": "_capture", "ocr": "_quick_ocr"}.get(failure)
                    mock = (patch.object(self.watcher, target, side_effect=RuntimeError("failed"))
                            if target else patch("src.core.watcher.imagehash.phash",
                                                 side_effect=RuntimeError("failed")))
                    with mock, self.assertRaises(RuntimeError):
                        self.tick(0.3)
                for at in (5.0, 5.3, 5.65):
                    self.tick(at, "A new dialogue.")
                timing, = self.submitted()
                self.assertAlmostEqual(timing.started_at, 5.0)
                self.assertEqual(timing.ocr_samples, 3)
                self.assertAlmostEqual(timing.ocr_seconds, 0.15)

    def test_manual_timing_counts_only_its_own_capture_and_ocr(self):
        self.tick(0.0)
        self.clock.now = 10.0
        self.watcher.force_trigger()
        timing, = self.submitted()
        self.assertTrue(self.observations[-1].manual)
        self.assertAlmostEqual(timing.started_at, 10.0)
        self.assertAlmostEqual(timing.submitted_at, 10.07)
        self.assertAlmostEqual(timing.capture_seconds, 0.02)
        self.assertAlmostEqual(timing.ocr_seconds, 0.05)
        self.assertEqual(timing.ocr_samples, 1)
        self.assertEqual(timing.stable_seconds, 0.0)

    def test_slow_ocr_is_work_inside_elapsed_time_not_an_extra_wait(self):
        self.ocr_cost = 0.8
        self.tick(0.0)
        self.clock.now += self.watcher.next_poll_interval
        self.watcher.tick()
        timing, = self.submitted()
        self.assertAlmostEqual(timing.submitted_at - timing.started_at, 1.79)
        self.assertAlmostEqual(timing.capture_seconds, 0.04)
        self.assertAlmostEqual(timing.ocr_seconds, 1.6)
        self.assertEqual(timing.ocr_samples, 2)
        self.assertAlmostEqual(timing.stable_seconds, 0.97)
        self.assertLessEqual(timing.capture_seconds + timing.ocr_seconds,
                             timing.submitted_at - timing.started_at)

    def test_settings_change_restarts_measurement_without_recounting_old_ocr(self):
        self.tick(10.0)
        self.clock.now = 10.3
        self.watcher.update_settings(preset="auto")
        self.tick(11.0)
        self.tick(11.3)
        timing, = self.submitted()
        self.assertAlmostEqual(timing.started_at, 11.0)
        self.assertAlmostEqual(timing.submitted_at, 11.37)
        self.assertEqual(timing.ocr_samples, 2)
        self.assertAlmostEqual(timing.ocr_seconds, 0.1)
        self.assertAlmostEqual(timing.stable_seconds, 0.3)

    def test_restart_discards_unsubmitted_episode(self):
        self.tick(0.0)
        self.watcher.stop()
        self.clock.now = 20.0
        self.watcher.start()
        for at in (20.0, 20.3, 20.65):
            self.tick(at)
        timing, = self.submitted()
        self.assertAlmostEqual(timing.started_at, 20.0)
        self.assertEqual(timing.ocr_samples, 3)

    def test_submission_time_is_frozen_before_translation_callback(self):
        def translate(image, text):
            self.clock.now += 10.0

        self.watcher._on_stable = translate
        self.watcher.force_trigger()
        timing, = self.submitted()
        self.assertIsInstance(timing, WatchTiming)
        self.assertAlmostEqual(timing.submitted_at, 0.07)
        self.assertAlmostEqual(self.clock.now, 10.07)


if __name__ == "__main__":
    unittest.main()


