import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_path_exists = Path.exists
with patch.object(
    Path, "exists",
    lambda path: False if path.name == "config.json" else _path_exists(path),
):
    from src.ui.word_tooltip import WordTooltipWidget
from src.utils import vocabulary


class MemoryConfig:
    def __init__(self):
        self.values = {}
        self.saves = 0

    def get(self, *keys, default=None):
        return self.values.get(keys, default)

    def set(self, *args):
        self.values[args[:-1]] = args[-1]

    def save(self):
        self.saves += 1


class WordTooltipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # Windows' offscreen plugin has no default font database. Load a real
        # local font so layout assertions use readable Chinese/Latin metrics.
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
        if os.name == "nt" and font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                cls.app.setFont(QFont(families[0], 10))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "vocab.txt"
        self.path_patch = patch.object(vocabulary, "get_vocab_path", return_value=self.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.config = MemoryConfig()
        self.widget = WordTooltipWidget(config=self.config)
        self.addCleanup(self.widget.close)

    def show_result(self, **overrides):
        data = {"word": "example", "meaning": "示例：用来说明意思的事物。"}
        data.update(overrides)
        self.widget.show_result(data)
        self.app.processEvents()

    def test_favorite_can_be_removed_and_saved_state_is_loaded(self):
        self.show_result()
        self.widget._fav_btn.click()
        self.assertTrue(vocabulary.is_favorite("example"))
        self.assertTrue(self.widget._fav_btn.isEnabled())
        self.widget.hide()
        self.show_result(word="EXAMPLE")
        self.assertTrue(self.widget._fav_btn.isChecked())
        self.widget._fav_btn.click()
        self.assertFalse(vocabulary.is_favorite("example"))
        self.assertFalse(self.widget._fav_btn.isChecked())

    def test_loading_then_result_keeps_dragged_position_and_size(self):
        self.widget.show_loading("example", QPoint(10, 10))
        self.app.processEvents()
        self.assertFalse(self.widget._fav_btn.isEnabled())
        self.widget.move(50, 70)
        self.widget.resize(500, 330)
        self.show_result()
        self.assertEqual(self.widget.pos(), QPoint(50, 70))
        self.assertEqual((self.widget.width(), self.widget.height()), (500, 330))

    def test_pin_font_size_and_geometry_survive_recreation(self):
        self.show_result()
        self.widget.move(40, 55)
        self.widget.resize(480, 310)
        self.widget._pin_btn.click()
        self.widget._font_up_btn.click()
        self.widget._top_btn.click()
        self.widget.show_result({"word": "second", "meaning": "第二"}, QPoint(300, 300))
        self.assertEqual(self.widget.pos(), QPoint(40, 55))
        self.widget.close()
        restored = WordTooltipWidget(config=self.config)
        self.addCleanup(restored.close)
        self.assertTrue(restored._pinned)
        self.assertEqual(restored._font_size, 15)
        self.assertFalse(restored.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertEqual(restored.geometry(), self.widget.geometry())

    def test_title_drag_moves_window(self):
        self.show_result()
        self.widget.move(30, 30)
        start = self.widget.pos()
        handle = self.widget._title_bar
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=QPoint(15, 12))
        QTest.mouseMove(handle, QPoint(65, 42))
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=QPoint(65, 42))
        self.app.processEvents()
        self.assertNotEqual(self.widget.pos(), start)

    def test_long_text_scrolls_without_growing_window(self):
        self.widget.resize(360, 220)
        self.show_result(meaning="很长的释义，应该能够滚动阅读。" * 100)
        self.assertEqual(self.widget.height(), 220)
        self.assertGreater(self.widget._scroll.verticalScrollBar().maximum(), 0)
        self.widget._scroll.verticalScrollBar().setValue(100)
        self.show_result(meaning="短释义")
        self.assertEqual(self.widget._scroll.verticalScrollBar().value(), 0)

    def test_error_style_resets_and_html_stays_plain_text(self):
        self.widget.show_loading("example")
        self.widget.show_error("网络中断")
        self.assertIn("#f87171", self.widget._meaning_label.styleSheet())
        self.show_result(meaning="<b>原样显示</b>")
        self.assertNotIn("#f87171", self.widget._meaning_label.styleSheet())
        self.assertEqual(self.widget._meaning_label.textFormat(), Qt.TextFormat.PlainText)

    def test_favorite_write_failure_preserves_truthful_button_state(self):
        self.show_result()
        with patch.object(vocabulary, "toggle_word", side_effect=OSError("test failure")):
            self.widget._fav_btn.click()
        self.assertFalse(self.widget._fav_btn.isChecked())
        self.assertFalse(self.widget._status_label.isHidden())


if __name__ == "__main__":
    unittest.main()
