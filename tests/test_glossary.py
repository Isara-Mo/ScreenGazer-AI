import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.core import glossary
from src.core.glossary import GameGlossary
from scripts import update_genshin_glossary as updater


def row(en, zh, entry_id="test", tags=None):
    return {"id": entry_id, "en": en, "zhCN": zh, "tags": tags or ["character-sub"]}


class GameGlossaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundled = GameGlossary.load_bundled()

    def test_supplied_screenshot_names_are_source_backed(self):
        matches = self.bundled.match('Pacal and Odette join the "Children of Echoes".')
        mapping = {term.english: term.chinese for term in matches}
        self.assertEqual(mapping["Pacal"], "帕加尔")
        self.assertEqual(mapping["Odette"], "奥黛塔")
        self.assertEqual(mapping["Children of Echoes"], "回声之子")

    def test_longest_phrase_wins_over_overlap_and_results_are_unique(self):
        matcher = GameGlossary([row("Echoes", "回声"), row("Children of Echoes", "回声之子")])
        result = matcher.match("Children of Echoes and Children of Echoes")
        self.assertEqual([m.english for m in result], ["Children of Echoes"])
        # A separate short occurrence still has its own meaning.
        self.assertEqual([m.english for m in matcher.match("Children of Echoes, Echoes")], ["Children of Echoes", "Echoes"])

    def test_boundaries_case_and_possessives(self):
        matcher = GameGlossary([row("Jean", "琴"), row("Amber", "安柏"), row("Will", "小威")])
        self.assertEqual(matcher.match("Jeanne sells amber; I will buy it."), [])
        self.assertEqual([m.english for m in matcher.match("Jean's sword")], ["Jean"])
        self.assertEqual([m.english for m in matcher.match("Jean_ and _Jean")], [])
        self.assertTrue(all(m.conditional for m in matcher.match("Amber asked Will.")))
        hint = matcher.prompt_hint("Will we find Amber?")
        self.assertIn('"requires_game_context":true', hint)
        self.assertIn("否则按普通英语翻译", hint)

    def test_wrapped_lines_apostrophes_and_source_offsets(self):
        matcher = GameGlossary([row("Knights of Favonius", "西风骑士团"), row("Khaenri'ah", "坎瑞亚")])
        text = "The Knights\n  of\tFavonius visited Khaenri’ah."
        matches = matcher.match(text)
        self.assertEqual([m.english for m in matches], ["Knights of Favonius", "Khaenri'ah"])
        for match in matches:
            self.assertEqual(text[match.start:match.end], match.matched)

    def test_overrides_disable_add_and_resolve_conflicts(self):
        matcher = GameGlossary([row("Jean", "琴"), row("Amber", "安柏")], {"Jean": "自定琴", "Amber": "", "Player": "玩家"})
        self.assertEqual({m.english: m.chinese for m in matcher.match("Jean Amber Player")}, {"Jean": "自定琴", "Player": "玩家"})
        conflict = [row("Name", "名字甲"), row("Name", "名字乙")]
        self.assertEqual(GameGlossary(conflict).match("Name"), [])
        self.assertEqual(GameGlossary(conflict, {"Name": "校正名字"}).match("Name")[0].chinese, "校正名字")

    def test_lookup_preserves_word_and_translation_preserves_corrected(self):
        hint = self.bundled.prompt_hint("Pacal met Odette.")
        self.assertIn("corrected", hint)
        self.assertIn("保留英文", hint)
        self.assertNotIn('"en":"Amber"', hint)
        lookup = self.bundled.prompt_hint("Pacal", for_lookup=True)
        self.assertIn("meaning / note", lookup)
        self.assertIn("word 字段", lookup)
        self.assertNotIn("corrected", lookup)
        self.assertEqual(self.bundled.prompt_hint("ordinary lowercase words only"), "")

    def test_invalid_override_and_ambiguous_slash_rejected(self):
        for overrides in ([], {"bad": "x\n注入"}, {"x / y": "混合"}, {"x": "甲 / 乙"}, {1: "中文"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                GameGlossary([], overrides)

    def test_missing_and_corrupt_bundled_file_are_not_silent(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.json"
            glossary._bundled_rows.cache_clear()
            try:
                with patch.object(glossary, "BUNDLED_PATH", missing), self.assertRaises(FileNotFoundError):
                    GameGlossary.load_bundled()
                missing.write_text('{"schema_version": 1, "terms": []}', encoding="utf-8")
                with patch.object(glossary, "BUNDLED_PATH", missing), self.assertRaises(ValueError):
                    GameGlossary.load_bundled()
            finally:
                glossary._bundled_rows.cache_clear()

    def test_bundled_provenance_counts_and_common_words_filtered(self):
        data = json.loads(glossary.BUNDLED_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["source"]["entry_count"], len(data["terms"]))
        self.assertRegex(data["source"]["upstream_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(data["source"]["terms_url"], updater.TERMS_URL)
        self.assertGreater(len(self.bundled), 1000)
        mapping = {r["en"]: r["zhCN"] for r in data["terms"]}
        self.assertNotIn("pull", mapping)
        self.assertNotIn("Reward", mapping)
        self.assertNotIn("Chihu Rock", mapping)  # upstream has two Chinese names
        self.assertEqual(mapping["Orobashi"], mapping["Orobaxi"])
        self.assertTrue(all(set(r) == {"id", "en", "zhCN", "tags"} for r in data["terms"]))


class GlossaryUpdaterTests(unittest.TestCase):
    def fixture(self, extras=()):
        data = [row("Pacal", "帕加尔", "pacal"), row('"Children of Echoes"', "「回声之子」", "children-of-echoes", ["organization"])]
        data += [row(f"Testname{i}", f"测试名字{i}", f"test-{i}") for i in range(1000)]
        return json.dumps(data + list(extras), ensure_ascii=False).encode("utf-8")

    def test_filter_slash_conflicts_variants_and_unclassified_words(self):
        raw = self.fixture([
            row("Alias One / Alias Two", "同一名字", "aliases"),
            row("Many Names", "名字甲 / 名字乙", "multi"),
            row("Conflict", "名字甲", "conflict-a"),
            row("Conflict", "名字乙", "conflict-b"),
            row("slash/name", "混合", "invalid-slash"),
            {**row("Primary", "正式名", "primary"), "variants": {"en": ["Mispelt", "Unofficial"]}},
            {"en": "Reward", "zhCN": "奖励", "id": "reward", "tags": []},
            {"en": "", "zhCN": "空白", "id": "empty", "tags": []},
        ])
        data = updater.build_dataset(raw, "2026-09-19T00:00:00+00:00")
        mapping = {r["en"]: r["zhCN"] for r in data["terms"]}
        self.assertEqual(mapping["Alias One"], mapping["Alias Two"])
        for excluded in ("Many Names", "Conflict", "slash/name", "Mispelt", "Unofficial", "Reward"):
            self.assertNotIn(excluded, mapping)
        self.assertEqual(data["source"]["upstream_sha256"], hashlib.sha256(raw).hexdigest())

    def test_rejects_schema_changes_too_small_downloads_and_anchor_changes(self):
        for raw in (b"{}", b"[]", b"not json", self.fixture().replace("帕加尔".encode(), "错误名字".encode())):
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                updater.build_dataset(raw)

    def test_failed_atomic_replace_preserves_dataset_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "terms.json"
            path.write_bytes(b"original")
            with patch.object(updater.os, "replace", side_effect=OSError("failure")):
                with self.assertRaises(OSError):
                    updater.atomic_write(path, b"updated")
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_update_refuses_redirect_to_an_unrelated_or_insecure_host(self):
        handler = updater._SafeRedirect()
        for url in ("http://dataset.genshin-dictionary.com/words.json", "https://example.com/words.json"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                handler.redirect_request(None, None, 302, "", {}, url)


if __name__ == "__main__":
    unittest.main()
