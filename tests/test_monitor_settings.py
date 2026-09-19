"""Offline regressions for watcher settings; never open the user's config file."""

import copy
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ConfigManager creates a module singleton on import. Skip only that file's
# existence check, so importing these tests cannot load real API credentials.
_path_exists = Path.exists
with patch.object(
    Path, "exists",
    lambda path: False if path.name == "config.json" else _path_exists(path),
):
    from src.utils.config_manager import ConfigManager, DEFAULT_CONFIG
    from src.ui.config_dialog import ConfigDialog

from PySide6.QtWidgets import QApplication


class MonitorSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config = object.__new__(ConfigManager)
        self.config._config = copy.deepcopy(DEFAULT_CONFIG)
        self.config.save = Mock()
        self.manager_patch = patch(
            "src.ui.config_dialog.ConfigManager", return_value=self.config
        )
        self.manager_patch.start()
        self.addCleanup(self.manager_patch.stop)

    def make_dialog(self):
        dialog = ConfigDialog()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog

    def test_disabled_flags_survive_open_and_save(self):
        self.config.set("watcher", "enabled", False)
        self.config.set("ui", "always_on_top", False)

        dialog = self.make_dialog()
        self.assertFalse(dialog._watcher_enabled.isChecked())
        self.assertFalse(dialog._always_on_top.isChecked())
        dialog._save_values()

        self.assertIs(self.config.get("watcher", "enabled"), False)
        self.assertIs(self.config.get("ui", "always_on_top"), False)
        self.config.save.assert_called()

    def test_preset_changes_preserve_manual_tuning(self):
        values = {"poll_interval": 0.8, "stability_count": 5, "hash_threshold": 21}
        for key, value in values.items():
            self.config.set("watcher", key, value)
        dialog = self.make_dialog()

        for preset in ("auto", "custom", "stable", "fast"):
            dialog._watcher_preset.setCurrentIndex(dialog._watcher_preset.findData(preset))
            self.assertEqual(dialog._watcher_custom_group.isHidden(), preset != "custom")
            self.assertEqual(dialog._watcher_custom_group.isEnabled(), preset == "custom")

        dialog._save_values()
        self.assertEqual(self.config.get("watcher", "preset"), "fast")
        for key, value in values.items():
            self.assertEqual(self.config.get("watcher", key), value)

    def test_legacy_settings_receive_defaults_without_losing_tuning(self):
        legacy = {
            "watcher": {
                "enabled": False,
                "poll_interval": 1.2,
                "stability_count": 4,
                "hash_threshold": 16,
            },
            "ui": {"always_on_top": False},
        }
        merged = self.config._deep_merge(DEFAULT_CONFIG, legacy)

        self.assertEqual(merged["watcher"]["preset"], "auto")
        self.assertEqual(merged["watcher"]["cooldown_seconds"], 0.5)
        for key, value in legacy["watcher"].items():
            self.assertEqual(merged["watcher"][key], value)
        self.assertIs(merged["ui"]["always_on_top"], False)
        self.assertIs(merged["ui"]["word_tooltip_pinned"], False)
        self.assertEqual(merged["ui"]["word_tooltip_font_size"], 14)

    def test_unknown_preset_falls_back_to_auto(self):
        self.config.set("watcher", "preset", "unknown")
        dialog = self.make_dialog()
        self.assertEqual(dialog._watcher_preset.currentData(), "auto")
        self.assertTrue(dialog._watcher_custom_group.isHidden())


if __name__ == "__main__":
    unittest.main()
