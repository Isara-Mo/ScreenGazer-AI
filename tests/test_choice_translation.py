"""Dialogue/reply boundaries, stable IDs and glossary handling without API calls."""

import json
import threading
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import Mock, patch

from PIL import Image

from src.core.dialogue_content import (
    ReplyChoice, SceneText, SCENE_PREFIX, pack_scene_text, prepare_scene_image,
    recognize_scene, scene_image_parts, unpack_scene_text,
)
from src.core.glossary import GameGlossary
from src.core.translator import Translator, TranslationResult


class SceneContentTests(unittest.TestCase):
    def test_wire_preserves_quotes_wrapped_options_and_empty_indices(self):
        wire = pack_scene_text('Papers!\nFresh papers!', ['What "news"?\nYoung man?', '', "I'm fine."])
        self.assertEqual(unpack_scene_text(wire), SceneText(
            'Papers! Fresh papers!', ('What "news"? Young man?', '', "I'm fine.")))
        self.assertEqual(wire, pack_scene_text('Papers! Fresh papers!', ['What "news"? Young man?', '', "I'm fine."]))
        self.assertNotEqual(wire, pack_scene_text('Papers! Fresh papers!', ["I'm fine.", '', 'What "news"? Young man?']))

    def test_invalid_wire_is_not_treated_as_a_scene(self):
        for text in ('Ordinary dialogue', SCENE_PREFIX + '{}', SCENE_PREFIX + '[]',
                     SCENE_PREFIX + '{"dialogue":"ok","choices":[1]}'):
            with self.subTest(text=text):
                self.assertIsNone(unpack_scene_text(text))

    def test_ocr_separates_original_crops_and_never_ocr_labels(self):
        crops = [Image.new('RGB', (50, 20), color) for color in ('red', 'green', 'blue')]
        image = prepare_scene_image(crops[0], crops[1:])
        recognize = Mock(side_effect=['Fresh papers!', 'What news?\nYoung man?', 'No thanks.'])
        scene = unpack_scene_text(recognize_scene(image, recognize))
        self.assertEqual([c.args[0] for c in recognize.call_args_list], crops)
        self.assertEqual(scene.choices, ('What news? Young man?', 'No thanks.'))
        self.assertIs(scene_image_parts(image).dialogue, crops[0])
        self.assertGreater(image.height, sum(c.height for c in crops))

    def test_only_choices_empty_ocr_and_plain_dialogue_compatibility(self):
        crop = Image.new('RGB', (50, 20))
        image = prepare_scene_image(None, [crop, crop])
        recognize = Mock(side_effect=['', '  '])
        self.assertEqual(recognize_scene(image, recognize), '')
        self.assertEqual(recognize.call_count, 2)
        plain = prepare_scene_image(crop, [])
        self.assertIs(plain, crop)
        self.assertEqual(recognize_scene(plain, lambda _: 'plain\ntext'), 'plain\ntext')
        with self.assertRaises(ValueError):
            prepare_scene_image(None, [])

    def test_reply_value_is_immutable(self):
        choice = ReplyChoice(1, 'Yes.', 'Yes.', '是的。')
        with self.assertRaises(FrozenInstanceError):
            choice.index = 2


class ChoiceTranslationTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.ocr = Mock()
        self.lock = threading.Lock()
        self.glossary = GameGlossary([{'en': 'Pacal', 'zhCN': '帕加尔'}, {'en': 'Liyue', 'zhCN': '璃月'}])
        self.translator = Translator(self.client, self.ocr, 'Translate: {text}', 'Read image.',
                                     ocr_lock=self.lock, game_profile='genshin', glossary=self.glossary)
        self.crop = Image.new('RGB', (60, 20))
        self.image = prepare_scene_image(self.crop, [self.crop, self.crop])
        self.wire = pack_scene_text('Fresh papers!', ['What news, Pacal?', 'No thanks.'])
        self.data = {'corrected': 'Fresh papers!', 'translation': '新报纸！', 'choices': [
            {'index': 1, 'corrected': 'What news, Pacal?', 'translation': '帕加尔，有什么新闻？'},
            {'index': 2, 'corrected': 'No thanks.', 'translation': '不用了，谢谢。'},
        ]}
        quiet = patch('builtins.print')
        quiet.start()
        self.addCleanup(quiet.stop)

    def respond(self, data=None, *, vision=False):
        call = self.client.chat_vision if vision else self.client.chat
        call.return_value = json.dumps(self.data if data is None else data, ensure_ascii=False)

    def test_cached_ocr_uses_one_request_with_glossary_across_choices(self):
        self.respond()
        result = self.translator.translate_ocr(self.image, self.wire)
        self.client.chat.assert_called_once()
        self.ocr.recognize.assert_not_called()
        prompt = self.client.chat.call_args.args[0][0]['content']
        self.assertNotIn(SCENE_PREFIX, prompt)
        self.assertIn('帕加尔', prompt)
        self.assertEqual(result.original_ocr, 'Fresh papers!')
        self.assertEqual([c.original_ocr for c in result.choices], ['What news, Pacal?', 'No thanks.'])
        self.assertEqual(result.choices[1].translation, '不用了，谢谢。')
        self.assertEqual(result.glossary_hits, [('Pacal', '帕加尔')])
        self.assertTrue(result.success)

    def test_uncached_ocr_recognizes_each_block_under_the_shared_lock(self):
        answers = iter(['Fresh papers!', 'What news, Pacal?', 'No thanks.'])
        def recognize(_image):
            self.assertTrue(self.lock.locked())
            return next(answers)
        self.ocr.recognize.side_effect = recognize
        self.respond()
        result = self.translator.translate_ocr(self.image)
        self.assertTrue(result.success)
        self.assertEqual(self.ocr.recognize.call_count, 3)
        self.client.chat.assert_called_once()

    def test_reordered_response_matches_indices_not_list_positions(self):
        self.data['choices'].reverse()
        self.respond()
        result = self.translator.translate_ocr(self.image, self.wire)
        self.assertEqual([c.index for c in result.choices], [1, 2])
        self.assertEqual(result.choices[0].translation, '帕加尔，有什么新闻？')
        self.assertEqual(result.choices[1].translation, '不用了，谢谢。')
        self.assertEqual(result.warning, '')

    def test_missing_duplicate_and_invalid_indices_never_shift_an_answer(self):
        scenarios = [
            [self.data['choices'][1]],
            [self.data['choices'][0], self.data['choices'][0], self.data['choices'][1]],
            [{'index': True, 'translation': '错误'}, self.data['choices'][1]],
            [{'index': '1', 'translation': '错误'}, self.data['choices'][1]],
            [{'index': 9, 'translation': '错误'}, self.data['choices'][1]],
        ]
        for entries in scenarios:
            with self.subTest(entries=entries):
                self.respond({**self.data, 'choices': entries})
                result = self.translator.translate_ocr(self.image, self.wire)
                self.assertEqual(result.choices[0].corrected, 'What news, Pacal?')
                self.assertEqual(result.choices[0].translation, '')
                self.assertEqual(result.choices[1].translation, '不用了，谢谢。')
                self.assertIn('选项 1', result.warning)

    def test_non_json_output_preserves_originals_with_warning(self):
        self.client.chat.return_value = 'Here is my answer without any indices.'
        result = self.translator.translate_ocr(self.image, self.wire)
        self.assertEqual(result.corrected, 'Fresh papers!')
        self.assertEqual(result.choices[0].corrected, 'What news, Pacal?')
        self.assertTrue(result.warning)
        self.assertFalse(any(c.translation for c in result.choices))

    def test_only_choices_succeeds_and_model_cannot_invent_npc_dialogue(self):
        image = prepare_scene_image(None, [self.crop, self.crop])
        self.respond()
        result = self.translator.translate_ocr(image, pack_scene_text('', ['What news, Pacal?', 'No thanks.']))
        self.assertTrue(result.success)
        self.assertEqual((result.corrected, result.translation, result.original_ocr), ('', '', ''))
        self.assertEqual(len(result.choices), 2)
        self.assertEqual(TranslationResult(corrected='plain').choices, [])

    def test_malformed_internal_wire_is_never_displayed_or_sent(self):
        result = self.translator.translate_ocr(self.image, SCENE_PREFIX + '{}')
        self.assertFalse(result.success)
        self.assertEqual(result.original_ocr, '')
        self.client.chat.assert_not_called()

    def test_partial_empty_ocr_keeps_missing_slot_without_model_invention(self):
        self.respond()
        result = self.translator.translate_ocr(self.image, pack_scene_text('Fresh papers!', ['', 'No thanks.']))
        self.assertEqual(result.choices[0], ReplyChoice(1))
        self.assertIn('选项 1', result.warning)
        self.assertEqual(result.choices[1].translation, '不用了，谢谢。')

    def test_monitored_vl_uses_one_call_when_all_glossary_terms_are_correct(self):
        self.respond(vision=True)
        result = self.translator.translate_vl(self.image, self.wire)
        self.client.chat_vision.assert_called_once()
        self.client.chat.assert_not_called()
        self.ocr.recognize.assert_not_called()
        self.assertEqual(result.original_ocr, 'Fresh papers!')
        self.assertEqual(result.choices[0].original_ocr, 'What news, Pacal?')

    def test_manual_vl_refinement_preserves_choices_order_and_english(self):
        first = {**self.data, 'choices': [
            {'index': 1, 'corrected': 'Visit Liyue?', 'translation': '去离月？'},
            self.data['choices'][1],
        ]}
        revised = {**self.data, 'choices': [
            {'index': 2, 'corrected': '不要改变英文', 'translation': '不用了，谢谢。'},
            {'index': 1, 'corrected': '去璃月？', 'translation': '去璃月？'},
        ]}
        self.client.chat_vision.side_effect = [json.dumps(first), json.dumps(revised)]
        result = self.translator.translate_vl(self.image)
        self.assertEqual(self.client.chat_vision.call_count, 2)
        self.ocr.recognize.assert_not_called()
        self.assertEqual(result.choices[0], ReplyChoice(1, '', 'Visit Liyue?', '去璃月？'))
        self.assertEqual(result.choices[1].corrected, 'No thanks.')
        self.assertIn('ALL reply choices', self.client.chat_vision.call_args.args[0])

    def test_failed_or_incomplete_refinement_preserves_all_first_answers(self):
        first = {**self.data, 'choices': [
            {'index': 1, 'corrected': 'Visit Liyue?', 'translation': '首轮选项一'},
            self.data['choices'][1],
        ]}
        revised = {'corrected': 'Fresh papers!', 'translation': '对白校正但缺失选项', 'choices': []}
        for second in (RuntimeError('offline'), json.dumps(revised)):
            with self.subTest(second=second):
                self.client.chat_vision.side_effect = [json.dumps(first), second]
                result = self.translator.translate_vl(self.image)
                self.assertTrue(result.success)
                self.assertEqual(result.translation, '新报纸！')
                self.assertEqual(result.choices[0].translation, '首轮选项一')
                self.assertEqual(result.choices[1].translation, '不用了，谢谢。')
                self.assertIn('术语校正失败', result.warning)

    def test_model_error_never_returns_the_internal_wire_as_english(self):
        self.client.chat.side_effect = RuntimeError('offline')
        result = self.translator.translate_ocr(self.image, self.wire)
        self.assertFalse(result.success)
        self.assertEqual(result.corrected, 'Fresh papers!')
        self.assertEqual(result.choices[0].corrected, 'What news, Pacal?')
        self.assertNotIn(SCENE_PREFIX, result.original_ocr)


if __name__ == '__main__':
    unittest.main()
