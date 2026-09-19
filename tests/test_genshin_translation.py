"""Genshin translation contracts, with local glossary and fake model responses."""
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from PIL import Image

_exists = Path.exists
with patch.object(Path, 'exists', lambda p: False if p.name == 'config.json' else _exists(p)):
    from src.core.glossary import GameGlossary
    from src.core.translator import Translator


class GenshinTranslationTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new('RGB', (64, 32))
        self.client = Mock()
        self.ocr = Mock()
        self.glossary = GameGlossary([
            {'en': 'Pacal', 'zhCN': '帕加尔'},
            {'en': 'Children of Echoes', 'zhCN': '回声之子'},
            {'en': 'Liyue', 'zhCN': '璃月'},
            {'en': 'Amber', 'zhCN': '安柏'},
        ])
        self.translator = Translator(self.client, self.ocr, 'Translate: {text}',
                                     'Read and translate.', game_profile='genshin',
                                     glossary=self.glossary)
        quiet = patch('builtins.print')
        quiet.start()
        self.addCleanup(quiet.stop)

    def response(self, corrected, translation):
        return json.dumps({'corrected': corrected, 'translation': translation}, ensure_ascii=False)

    def test_ocr_passes_original_english_and_only_matching_terms(self):
        source = 'Pacal leads the Children of Echoes.'
        self.client.chat.return_value = self.response(source, '帕加尔领导回声之子。')
        result = self.translator.translate_ocr(self.image, source)
        self.ocr.recognize.assert_not_called()
        prompt = self.client.chat.call_args.args[0][0]['content']
        self.assertIn('Translate: ' + source, prompt)
        self.assertIn('帕加尔', prompt)
        self.assertIn('回声之子', prompt)
        self.assertNotIn('璃月', prompt)
        self.assertEqual(result.corrected, source)
        self.assertEqual(result.original_ocr, source)
        self.assertEqual(len(result.glossary_hits), 2)
        self.client.chat.assert_called_once()

    def test_unmatched_text_has_no_dictionary_payload(self):
        source = 'It is getting late.'
        self.client.chat.return_value = self.response(source, '天色已晚。')
        result = self.translator.translate_ocr(self.image, source)
        self.assertEqual(result.glossary_hits, [])
        self.assertNotIn('帕加尔', self.client.chat.call_args.args[0][0]['content'])

    def test_generic_mode_ignores_a_supplied_game_glossary(self):
        translator = Translator(self.client, translate_text_prompt='{text}', glossary=self.glossary)
        self.client.chat.return_value = self.response('Amber', '琥珀')
        translator.translate_ocr(self.image, 'Amber')
        self.assertEqual(self.client.chat.call_args.args[0], [{'role': 'user', 'content': 'Amber'}])

    def test_custom_translation_replaces_bundled_hint(self):
        custom = GameGlossary([{'en': 'Pacal', 'zhCN': '旧译名'}], overrides={'Pacal': '帕加尔'})
        translator = Translator(self.client, translate_text_prompt='{text}', game_profile='genshin', glossary=custom)
        self.client.chat.return_value = self.response('Pacal', '帕加尔')
        translator.translate_ocr(self.image, 'Pacal')
        prompt = self.client.chat.call_args.args[0][0]['content']
        self.assertIn('帕加尔', prompt)
        self.assertNotIn('旧译名', prompt)

    def test_monitored_vl_reuses_ocr_terms_in_one_vision_call(self):
        self.client.chat_vision.return_value = self.response('Pacal is here.', '帕加尔来了。')
        result = self.translator.translate_vl(self.image, ocr_text='Pacal is here.')
        self.client.chat_vision.assert_called_once()
        self.client.chat.assert_not_called()
        prompt, image = self.client.chat_vision.call_args.args
        self.assertIn('帕加尔', prompt)
        self.assertIn('gold speaker name', prompt)
        self.assertIs(image, self.image)
        self.assertEqual(result.translation, '帕加尔来了。')

    def test_manual_vl_refines_with_same_model_without_a_text_model(self):
        source = 'Pacal is here.'
        self.client.chat_vision.side_effect = [
            self.response(source, '帕卡尔来了。'), self.response('帕加尔来了。', '帕加尔来了。')]
        result = self.translator.translate_vl(self.image)
        self.assertEqual(self.client.chat_vision.call_count, 2)
        self.client.chat.assert_not_called()
        self.ocr.recognize.assert_not_called()
        self.assertEqual(result.corrected, source)
        self.assertEqual(result.translation, '帕加尔来了。')
        self.assertIn('帕加尔', self.client.chat_vision.call_args.args[0])
        self.assertIs(self.client.chat_vision.call_args.args[1], self.image)

    def test_vl_can_add_terms_missed_by_monitor_ocr(self):
        self.client.chat_vision.side_effect = [
            self.response('Pacal visits Liyue.', '帕加尔来访。'),
            self.response('Pacal visits Liyue.', '帕加尔来到璃月。')]
        result = self.translator.translate_vl(self.image, ocr_text='Pacal visits.')
        self.assertEqual(self.client.chat_vision.call_count, 2)
        self.assertEqual(result.translation, '帕加尔来到璃月。')

    def test_vl_without_matches_needs_no_extra_call(self):
        self.client.chat_vision.return_value = self.response('Good morning.', '早上好。')
        result = self.translator.translate_vl(self.image)
        self.client.chat_vision.assert_called_once()
        self.assertEqual(result.glossary_hits, [])

    def test_refinement_failure_preserves_usable_first_translation_with_warning(self):
        self.client.chat_vision.side_effect = [self.response('Pacal is here.', '首轮译文'), RuntimeError('offline')]
        result = self.translator.translate_vl(self.image)
        self.assertTrue(result.success)
        self.assertEqual(result.translation, '首轮译文')
        self.assertIn('术语校正失败', result.warning)
        self.assertEqual(self.client.chat_vision.call_count, 2)

    def test_refinement_cannot_loop_if_model_ignores_glossary(self):
        self.client.chat_vision.return_value = self.response('Pacal is here.', '旧译名')
        self.translator.translate_vl(self.image, 'Pacal is here.')
        self.assertEqual(self.client.chat_vision.call_count, 2)

    def test_lookup_uses_term_meanings_and_preserves_selected_english(self):
        self.client.chat.return_value = json.dumps({'word': 'Pacal', 'meaning': '帕加尔'})
        data = self.translator.lookup_word('Pacal', 'Pacal leads the Children of Echoes.', prompt_template='{selected} | {context}')
        prompt = self.client.chat.call_args.args[0][0]['content']
        self.assertIn('帕加尔', prompt)
        self.assertIn('回声之子', prompt)
        self.assertIn('meaning', prompt)
        self.assertEqual(data['word'], 'Pacal')


if __name__ == '__main__':
    unittest.main()
