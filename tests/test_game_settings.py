"""Offline game-settings regressions; never load or write a user's config."""

import copy
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_path_exists = Path.exists
with patch.object(
    Path, "exists",
    lambda path: False if path.name == "config.json" else _path_exists(path),
):
    from src.utils.config_manager import ConfigManager, DEFAULT_CONFIG
    from src.ui.config_dialog import ConfigDialog, parse_custom_terms

from PySide6.QtWidgets import QApplication, QDialog


class CustomTermsTests(unittest.TestCase):
    def test_preserves_user_spelling_and_ignores_blank_lines(self):
        self.assertEqual(
            parse_custom_terms("\n Paimon = 派蒙 \n\nChildren of Echoes = 回声之子\n"),
            {"Paimon": "派蒙", "Children of Echoes": "回声之子"},
        )

    def test_rejects_incomplete_or_ambiguous_lines(self):
        for line in ("Paimon 派蒙", "= 派蒙", "Paimon =", "Paimon = 派蒙 = 另一项"):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, "第 2 行"):
                parse_custom_terms("Liyue = 璃月\n" + line)

    def test_rejects_case_width_and_whitespace_duplicates(self):
        for first, second in (
            ("Paimon", "paimon"),
            ("Paimon", "Ｐａｉｍｏｎ"),
            ("Children of Echoes", "children  of   echoes"),
            ("Paimon", '"Paimon"'),
            ("Dragon's", "Dragon’s"),
        ):
            with self.subTest(second=second), self.assertRaisesRegex(ValueError, "第 2 行.*第 1 行重复"):
                parse_custom_terms(f"{first} = 名字\n{second} = 另一个名字")

    def test_rejects_every_field_the_glossary_backend_would_reject(self):
        for line in ("Paimon = 派/蒙", "<Paimon> = 派蒙", "Paimon = <派蒙>",
                     "A" * 241 + " = 名字", "Paimon = " + "名" * 241,
                     "Children\tof Echoes = 回声之子", '" " = 空名', 'Paimon = " "'):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, "第 2 行"):
                parse_custom_terms("Liyue = 璃月\n" + line)


class GameSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config = object.__new__(ConfigManager)
        self.config._config = copy.deepcopy(DEFAULT_CONFIG)
        self.config.save = Mock()
        self.manager_patch = patch("src.ui.config_dialog.ConfigManager", return_value=self.config)
        self.manager_patch.start()
        self.addCleanup(self.manager_patch.stop)

    def make_dialog(self):
        dialog = ConfigDialog()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog

    def test_defaults_use_generic_and_old_config_keeps_models(self):
        saved = {"models": [{"id": "user-model", "api_key": "fake-key"}], "capture": {"region": [1, 2, 3, 4]}}
        merged = self.config._deep_merge(DEFAULT_CONFIG, saved)
        self.assertEqual(merged["game"]["profile"], "generic")
        self.assertEqual(merged["game"]["genshin"], {
            "adaptive_dialogue": True, "use_glossary": True, "custom_terms": {},
        })
        self.assertEqual(merged["models"], saved["models"])
        self.assertEqual(merged["capture"]["region"], [1, 2, 3, 4])
        self.assertIsNone(merged["capture"]["relative_region"])

    def test_genshin_controls_disabled_until_selected(self):
        dialog = self.make_dialog()
        self.assertFalse(dialog._genshin_group.isEnabled())
        dialog._game_profile.setCurrentIndex(dialog._game_profile.findData("genshin"))
        self.assertTrue(dialog._genshin_group.isEnabled())
        dialog._genshin_custom_terms.setPlainText("Paimon = 派蒙")
        dialog._genshin_adaptive_dialogue.setChecked(False)
        dialog._genshin_use_glossary.setChecked(False)
        dialog._game_profile.setCurrentIndex(dialog._game_profile.findData("generic"))
        self.assertFalse(dialog._genshin_group.isEnabled())
        dialog._save_values()
        self.assertEqual(self.config.get("game", "profile"), "generic")
        self.assertEqual(self.config.get("game", "genshin"), {
            "adaptive_dialogue": False, "use_glossary": False, "custom_terms": {"Paimon": "派蒙"},
        })

    def test_saved_values_reload_and_roundtrip(self):
        expected = {"profile": "genshin", "genshin": {
            "adaptive_dialogue": False, "use_glossary": True,
            "custom_terms": {"Paimon": "派蒙", "Liyue": "璃月"},
        }}
        self.config.set("game", copy.deepcopy(expected))
        dialog = self.make_dialog()
        self.assertEqual(dialog._game_profile.currentData(), "genshin")
        self.assertFalse(dialog._genshin_adaptive_dialogue.isChecked())
        dialog._save_values()
        self.assertEqual(self.config.get("game"), expected)

    def test_validation_failure_changes_no_config_and_keeps_dialog_open(self):
        self.config.set("game", "profile", "genshin")
        self.config.set("game", "genshin", "custom_terms", {"Paimon": "派蒙"})
        dialog = self.make_dialog()
        before = self.config.get_all()
        dialog._genshin_custom_terms.setPlainText("Paimon = 派蒙\npaimon = 别名")
        dialog._profile_name_edit.setText("Unsaved edit")
        with patch("src.ui.config_dialog.QMessageBox.warning") as warning:
            dialog._save_and_close()
        self.assertEqual(self.config.get_all(), before)
        self.config.save.assert_not_called()
        warning.assert_called_once()
        self.assertIn("重复", warning.call_args.args[2])
        self.assertIs(dialog._tabs.currentWidget(), dialog._game_tab)
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_direct_save_also_validates_before_any_write(self):
        dialog = self.make_dialog()
        before = self.config.get_all()
        dialog._genshin_custom_terms.setPlainText("Paimon")
        with self.assertRaises(ValueError):
            dialog._save_values()
        self.assertEqual(self.config.get_all(), before)
        self.config.save.assert_not_called()

    def test_unknown_game_falls_back_to_generic(self):
        self.config.set("game", "profile", "unknown")
        dialog = self.make_dialog()
        self.assertEqual(dialog._game_profile.currentData(), "generic")
        self.assertFalse(dialog._genshin_group.isEnabled())


if __name__ == "__main__":
    unittest.main()
