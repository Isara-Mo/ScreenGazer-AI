import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.utils import vocabulary


class VocabularyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "vocab.txt"
        self.path_patch = patch.object(vocabulary, "get_vocab_path", return_value=self.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def test_toggle_add_remove_and_case_insensitive_deduplication(self):
        self.assertTrue(vocabulary.toggle_word("  Hello  "))
        vocabulary.add_word("hello")
        self.assertEqual(vocabulary.get_all_words(), ["Hello"])
        self.assertTrue(vocabulary.is_favorite("HELLO"))
        self.assertFalse(vocabulary.toggle_word("hello"))
        self.assertEqual(vocabulary.get_all_words(), [])

    def test_remove_preserves_unrelated_bytes_and_removes_legacy_duplicates(self):
        self.path.write_bytes(b"\xef\xbb\xbfhello\r\n  keep me  \r\n\r\nHELLO\nlast")
        self.assertTrue(vocabulary.remove_word("hello"))
        self.assertEqual(self.path.read_bytes(), b"\xef\xbb\xbf  keep me  \r\n\r\nlast")
        self.assertFalse(vocabulary.remove_word("missing"))

    def test_append_preserves_unterminated_existing_entry_and_normalizes_phrase(self):
        self.path.write_bytes("原有词条".encode("utf-8"))
        vocabulary.add_word("new\n phrase")
        self.assertEqual(vocabulary.get_all_words(), ["原有词条", "new phrase"])
        vocabulary.add_word("NEW  PHRASE")
        self.assertEqual(len(vocabulary.get_all_words()), 2)

    def test_failed_atomic_replace_leaves_original_intact(self):
        original = b"hello\nkeep\n"
        self.path.write_bytes(original)
        with patch.object(vocabulary.os, "replace", side_effect=OSError("test failure")):
            with self.assertRaises(OSError):
                vocabulary.remove_word("hello")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_empty_word_does_not_create_file(self):
        self.assertFalse(vocabulary.toggle_word(" \n "))
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
