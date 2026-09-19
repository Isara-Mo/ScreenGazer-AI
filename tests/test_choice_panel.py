"""Reply cards stay readable, ordered and quiet when observations repeat."""

import copy
import unittest
from unittest.mock import Mock, patch

from tests import test_main_window as fixture
from PySide6.QtWidgets import QApplication
from src.core.dialogue_content import ReplyChoice
from src.ui.choice_panel import ReplyChoicesPanel


class ChoicePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.cfg = object.__new__(fixture.ConfigManager)
        self.cfg._config = copy.deepcopy(fixture.DEFAULT_CONFIG)
        self.cfg.save = Mock()
        with patch("src.ui.result_panel.ConfigManager", return_value=self.cfg):
            self.panel = ReplyChoicesPanel()
        self.addCleanup(self.panel.close)
        self.choices = [ReplyChoice(1, "What news?", "What news?", "有什么新闻？"),
                        ReplyChoice(2, "No papers.", "No papers.", "我不需要报纸。")]

    def test_same_choices_do_not_rebuild_or_reopen_user_dismissal(self):
        self.panel.show_choices(self.choices)
        self.app.processEvents()
        cards = list(self.panel._cards)
        self.assertEqual([zh.text() for _,zh,_ in cards], ["1.  有什么新闻？", "2.  我不需要报纸。"])
        self.panel.dismiss()
        self.panel.show_choices(self.choices)
        self.assertFalse(self.panel.isVisible())
        self.assertEqual(self.panel._cards, cards)
        self.panel.reveal()
        self.assertTrue(self.panel.isVisible())
        self.panel.suspend()
        self.panel.show_choices(self.choices)
        self.assertTrue(self.panel.isVisible())
        self.assertEqual(self.panel._cards, cards)

    def test_changed_choices_show_again_and_text_is_plain_and_selectable(self):
        self.panel.show_choices(self.choices)
        self.panel.dismiss()
        changed = [ReplyChoice(1, "<keep>\nall words", "<keep>\nall words", "保留文字"),
                   ReplyChoice(2, "Leave", "Leave", "")]
        self.panel.show_choices(changed)
        self.assertTrue(self.panel.isVisible())
        self.assertEqual(self.panel._cards[0][2].text(), "<keep>\nall words")
        self.assertIn("暂未取得译文", self.panel._cards[1][1].text())
        self.panel.clear_choices()
        self.assertFalse(self.panel.has_choices)
        self.assertFalse(self.panel.isVisible())
        self.panel.reveal()
        self.assertFalse(self.panel.isVisible())

    def test_font_and_geometry_are_remembered(self):
        self.panel.show_choices(self.choices)
        self.app.processEvents()
        self.panel._change_font(2)
        self.assertEqual(self.cfg.get("ui", "choice_font_size"), 16)
        self.panel.move(30,40)
        self.panel.resize(450,380)
        self.app.processEvents()
        self.assertEqual(self.cfg.get("ui", "panel_geometry_choices"), [30,40,450,380])
        self.assertTrue(self.cfg.save.called)


if __name__ == "__main__":
    unittest.main()
