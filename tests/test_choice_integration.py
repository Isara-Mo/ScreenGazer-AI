"""Choices travel through real Qt request signals without a second OCR pass."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from PySide6.QtWidgets import QApplication

from tests import test_main_window as fixture
from src.core.capture import CaptureRegion, WindowInfo
from src.core.dialogue_content import pack_scene_text, unpack_scene_text, scene_image_parts
from src.core.watcher import ChangeWatcher, WatchObservation, normalize_ocr_text


class ChoiceIntegrationTests(unittest.TestCase):
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

    def test_capture_ocr_and_request_keep_choices_separate_in_one_model_call(self):
        self.cfg.set("game", "profile", "genshin")
        self.cfg.set("game", "genshin", "use_glossary", False)
        self.window._on_config_changed()
        dialogue = Image.new("RGB", (100, 40))
        dialogue.info["text"] = "Fresh newspapers!"
        options = []
        for text in ("What news today, young\nman?", "I'm fine without any\npapers to read."):
            image = Image.new("RGB", (60, 40))
            image.info["text"] = text
            options.append(SimpleNamespace(image=image))
        response = {"corrected":"Fresh newspapers!", "translation":"新鲜出炉的报纸！", "choices":[
            {"index":2, "corrected":"I'm fine without any papers to read.", "translation":"不用报纸也没关系。"},
            {"index":1, "corrected":"What news today, young man?", "translation":"小伙子，今天有什么新闻？"},
        ]}
        with patch("src.ui.main_window.prepare_genshin_dialogue",
                   return_value=SimpleNamespace(image=dialogue, detected=True)), \
             patch("src.ui.main_window.detect_genshin_choices", return_value=options), \
             patch.object(self.client, "chat", return_value=json.dumps(response)) as chat:
            worker = self.attach_monitor()
            image = worker._capture_fn()
            self.assertEqual(len(scene_image_parts(image).choices), 2)
            raw = worker._quick_ocr_fn(image)
            scene = unpack_scene_text(raw)
            self.assertEqual(scene.choices[0], "What news today, young man?")
            worker.observation_changed.emit(WatchObservation("submitted", normalize_ocr_text(raw)))
            worker.translation_needed.emit(image, raw)
            self.wait_until(lambda: self.choice_panel.show_choices.called)
        chat.assert_called_once()
        self.assertEqual(len(self.ocr.images), 3)
        self.assertEqual(self.panel.show_result.call_args.kwargs["corrected"], "Fresh newspapers!")
        choices = self.choice_panel.show_choices.call_args.args[0]
        self.assertEqual([c.index for c in choices], [1, 2])
        self.assertEqual(choices[0].translation, "小伙子，今天有什么新闻？")
        self.assertNotIn("news today", self.panel.show_result.call_args.kwargs["translation"])

    def test_choice_panel_hides_on_absence_and_restores_cached_translation(self):
        worker = self.attach_monitor()
        raw = pack_scene_text("NPC", ["Yes", "No"])
        response = {"corrected":"NPC", "translation":"台词", "choices":[
            {"index":1, "corrected":"Yes", "translation":"好"},
            {"index":2, "corrected":"No", "translation":"不"},
        ]}
        with patch.object(self.client, "chat", return_value=json.dumps(response)) as chat:
            worker.observation_changed.emit(WatchObservation("submitted", normalize_ocr_text(raw)))
            worker.translation_needed.emit(Image.new("RGB", (8,8)), raw)
            self.wait_until(lambda: self.choice_panel.show_choices.called)
            worker.observation_changed.emit(WatchObservation("empty"))
            self.assertTrue(self.window._choice_hide_timer.isActive())
            self.choice_panel.suspend.assert_not_called()
            worker.observation_changed.emit(WatchObservation("current", normalize_ocr_text(raw)))
            self.assertFalse(self.window._choice_hide_timer.isActive())
            worker.observation_changed.emit(WatchObservation("unavailable"))
            self.wait_until(lambda: self.choice_panel.suspend.called)
            self.choice_panel.show_choices.reset_mock()
            worker.observation_changed.emit(WatchObservation("current", normalize_ocr_text(raw)))
            self.choice_panel.show_choices.assert_called_once()
            chat.assert_called_once()

    def test_bound_genshin_window_expands_runtime_selection_only(self):
        self.cfg.set("game", "profile", "genshin")
        original = CaptureRegion(200, 700, 600, 240, hwnd=77,
                                 rel_x=.2, rel_y=.70, rel_w=.60, rel_h=.24)
        self.window._capture_region = original
        with patch("src.ui.main_window.get_window_info", return_value=WindowInfo("Game",77,0,0,1000,1000)):
            expanded = self.window._game_capture_region()
        self.assertLessEqual(expanded.rel_y, .38)
        self.assertGreaterEqual(expanded.rel_x + expanded.rel_w, .99)
        self.assertIs(self.window._capture_region, original)
        self.assertEqual(original.rel_y, .70)
        self.cfg.save.assert_not_called()
        self.cfg.set("game", "profile", "generic")
        self.assertIs(self.window._game_capture_region(), original)

    def test_stably_disappearing_and_returning_choices_reuse_full_scene(self):
        worker = self.attach_monitor()
        raw = pack_scene_text("NPC", ["Yes", "No"])
        response = {"corrected": "NPC", "translation": "台词", "choices": [
            {"index": 1, "corrected": "Yes", "translation": "好"},
            {"index": 2, "corrected": "No", "translation": "不"},
        ]}
        with patch.object(self.client, "chat", return_value=json.dumps(response)) as chat:
            for i, source in enumerate((raw, "NPC", raw), 1):
                worker.observation_changed.emit(WatchObservation("submitted", normalize_ocr_text(source)))
                worker.translation_needed.emit(Image.new("RGB", (8, 8)), source)
                self.wait_until(lambda: self.panel.show_result.call_count == i)
            self.assertEqual(chat.call_count, 2)
            restored = self.choice_panel.show_choices.call_args.args[0]
            self.assertEqual([choice.translation for choice in restored], ["好", "不"])
            self.assertIn("本次模型请求 0 次", self.window._last_timing_label.text())

    def test_choice_only_scene_does_not_open_or_clear_npc_subtitle_panels(self):
        worker = self.attach_monitor()
        raw = pack_scene_text("", ["Accept", "Decline"])
        response = {"corrected":"Invented NPC line", "translation":"多余的台词", "choices":[
            {"index":1,"corrected":"Accept","translation":"接受"},
            {"index":2,"corrected":"Decline","translation":"拒绝"},
        ]}
        with patch.object(self.client, "chat", return_value=json.dumps(response)):
            worker.observation_changed.emit(WatchObservation("submitted", normalize_ocr_text(raw)))
            worker.translation_needed.emit(Image.new("RGB", (8,8)), raw)
            self.wait_until(lambda: self.choice_panel.show_choices.called)
        self.panel.show_loading.assert_not_called()
        self.panel.show_result.assert_not_called()
        self.assertEqual(self.choice_panel.show_choices.call_args.args[0][1].translation, "拒绝")

    def test_only_choice_changes_trigger_and_curly_quotes_keep_valid_scene_encoding(self):
        raw = [pack_scene_text('He said “hello”.', ['Yes, “please”.', 'No.'])]
        normalized = normalize_ocr_text(raw[0])
        self.assertEqual(unpack_scene_text(normalized).choices[0], 'Yes, "please".')
        clock = [0.0]
        requests = []
        image = Image.new("RGB", (16,16))
        watcher = ChangeWatcher(lambda: image, lambda image: raw[0],
                                lambda image,text: requests.append(text), clock=lambda:clock[0])
        with patch("src.core.watcher.imagehash.phash", return_value=0):
            for at in (0, .3, .65):
                clock[0] = at
                status = watcher.tick()
            self.assertEqual(len(requests), 1)
            self.assertNotIn("SCREENGAZER", status)
            raw[0] = pack_scene_text('He said “hello”.', ['Take the papers.', 'Leave.'])
            for at in (1.1, 1.4, 1.75):
                clock[0] = at
                watcher.tick()
        self.assertEqual(len(requests), 2)
        self.assertEqual(unpack_scene_text(requests[-1]).dialogue, 'He said “hello”.')


if __name__ == "__main__":
    unittest.main()
