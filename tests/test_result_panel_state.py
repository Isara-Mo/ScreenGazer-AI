"""Translation panels preserve readable dialogue throughout each request."""

import unittest
from unittest.mock import patch

from tests import test_main_window as fixture
from src.ui.result_panel import ResultPanel
from PySide6.QtWidgets import QApplication


class ResultPanelStateTests(unittest.TestCase):
    setUp = fixture.MainWindowIntegrationTests.setUp
    tearDown = fixture.MainWindowIntegrationTests.tearDown
    wait_until = fixture.MainWindowIntegrationTests.wait_until
    capture_image = staticmethod(fixture.MainWindowIntegrationTests.capture_image)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self):
        with patch("src.ui.result_panel.ConfigManager", return_value=self.cfg):
            panel = ResultPanel()
        self.addCleanup(panel.close)
        return panel

    def test_cancelled_request_preserves_split_text_and_hidden_windows(self):
        panel = self.make_panel()
        panel.show_result("The previous line.", "上一句译文。")
        panel.show_loading()
        self.assertEqual(panel._chinese_panel._chinese_edit.toPlainText(), "上一句译文。")
        self.assertEqual(panel._english_panel._english_edit.toPlainText(), "The previous line.")
        for subpanel in (panel._chinese_panel, panel._english_panel):
            self.assertEqual(subpanel._loading_label.text(), "⟳ 翻译中...")
            self.assertFalse(subpanel._loading_label.isHidden())
            self.assertTrue(subpanel._status_label.isHidden())
        panel.show_chinese_only()
        panel.clear_progress()
        self.assertFalse(panel._chinese_panel._status_label.isHidden())
        self.assertEqual(panel._chinese_panel._status_label.text(), "最近翻译 ✓")
        self.assertEqual(panel._english_panel._status_label.text(), "最近翻译 ✓")
        self.assertEqual(panel._chinese_panel._chinese_edit.toPlainText(), "上一句译文。")
        self.assertEqual(panel._english_panel._english_edit.toPlainText(), "The previous line.")
        self.assertTrue(panel._english_panel.isHidden())
        self.assertTrue(panel._combined_panel.isHidden())
        panel.hide()
        panel.clear_progress()
        self.assertFalse(panel.isVisible())

    def test_combined_request_keeps_previous_text_until_result_and_reports_error(self):
        panel = self.make_panel()
        panel.clear_progress()
        self.assertEqual(panel._chinese_panel._status_label.text(), "就绪")
        self.assertFalse(panel.isVisible())
        panel.set_split_mode(False)
        panel.show_result("The previous line.", "上一句译文。")
        panel.show_loading()
        self.assertEqual(panel._combined_panel._chinese_edit.toPlainText(), "上一句译文。")
        self.assertEqual(panel._combined_panel._english_edit.toPlainText(), "The previous line.")
        self.assertEqual(panel._combined_panel._loading_label.text(), "⟳ 翻译中...")
        self.assertFalse(panel._combined_panel._loading_label.isHidden())
        panel.show_result("The current line.", "当前句译文。")
        self.assertEqual(panel._combined_panel._chinese_edit.toPlainText(), "当前句译文。")
        self.assertEqual(panel._combined_panel._english_edit.toPlainText(), "The current line.")
        self.assertEqual(panel._combined_panel._status_label.text(), "最近翻译 ✓")
        self.assertTrue(panel._combined_panel._loading_label.isHidden())
        panel.show_loading()
        panel.show_error("请求失败")
        self.assertEqual(panel._combined_panel._status_label.text(), "⚠ 请求失败")
        self.assertTrue(panel._combined_panel._loading_label.isHidden())
        self.assertEqual(panel._combined_panel._chinese_edit.toPlainText(), "当前句译文。")
        self.assertEqual(panel._combined_panel._english_edit.toPlainText(), "The current line.")
        self.assertTrue(panel._chinese_panel.isHidden())
        self.assertTrue(panel._english_panel.isHidden())


if __name__ == "__main__":
    unittest.main()
