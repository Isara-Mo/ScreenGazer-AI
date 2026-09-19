"""Count real Translator model calls with offline clients and real Qt workers."""

import json
import threading
import unittest
from unittest.mock import patch

# This fixture imports config-owning modules with personal config reads disabled.
from tests import test_request_workers as fixture

from PIL import Image
from src.core.dialogue_content import pack_scene_text, unpack_scene_text
from src.core.translator import Translator
from src.workers.translate_worker import TranslateWorker


class OfflineClient:
    """A counted model boundary; no SDK, network or credentials are involved."""

    def __init__(self, block_source=None, responses=()):
        self.block_source = block_source
        self.responses = list(responses)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def _answer(self, mode, source):
        self.calls.append((mode, source))
        if source == self.block_source:
            self.entered.set()
            if not self.release.wait(4):
                raise RuntimeError("Test did not release its model request")
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return json.dumps(response, ensure_ascii=False)
        scene = unpack_scene_text(source)
        if scene is None:
            result = {"corrected": source, "translation": f"译文 {source}"}
        else:
            result = {
                "corrected": scene.dialogue,
                "translation": f"译文 {scene.dialogue}" if scene.dialogue else "",
                "choices": [
                    {"index": i, "corrected": text, "translation": f"选项 {text}"}
                    for i, text in enumerate(scene.choices, 1)
                ],
            }
        return json.dumps(result, ensure_ascii=False)

    def chat(self, messages):
        prompt = messages[0]["content"]
        if prompt.startswith('{"dialogue":'):
            data, _ = json.JSONDecoder().raw_decode(prompt)
            source = pack_scene_text(data["dialogue"], [c["text"] for c in data["choices"]])
        else:
            source = prompt
        return self._answer("ocr", source)

    def chat_vision(self, prompt, image):
        return self._answer("vl", image.info["source"])


class RequestDedupTests(unittest.TestCase):
    setUpClass = classmethod(fixture.RequestWorkerTests.setUpClass.__func__)
    tearDown = fixture.RequestWorkerTests.tearDown
    wait_until = fixture.RequestWorkerTests.wait_until
    make_worker = fixture.RequestWorkerTests.make_worker

    def setUp(self):
        fixture.RequestWorkerTests.setUp(self)
        quiet = patch("builtins.print")
        quiet.start()
        self.addCleanup(quiet.stop)

    def worker(self, block_source=None, responses=()):
        client = OfflineClient(block_source, responses)
        translator = Translator(client, translate_text_prompt="{text}", translate_vl_prompt="Read image")
        # The shared teardown releases and joins all background requests.
        translator.release = client.release
        worker, results, errors = self.make_worker(TranslateWorker, translator)
        return worker, client, results, errors

    @staticmethod
    def submit(worker, source, mode="ocr", automatic=True, observed=True):
        image = Image.new("RGB", (4, 4))
        image.info["source"] = source
        worker.translate(image, mode, ocr_text=source if observed else None, automatic=automatic)

    def complete(self, worker, source, mode="ocr", automatic=True):
        self.submit(worker, source, mode, automatic)
        self.wait_until(lambda: not worker._busy)

    def test_stable_a_b_a_reuses_completed_answer_in_ocr_and_vl(self):
        for mode in ("ocr", "vl"):
            with self.subTest(mode=mode):
                worker, client, results, errors = self.worker()
                for source in ("A", "B", "A", "B", "A"):
                    self.complete(worker, source, mode)
                self.assertEqual(client.calls, [(mode, "A"), (mode, "B")])
                self.assertEqual([r.corrected for r in results], ["A", "B", "A", "B", "A"])
                self.assertEqual(results[-1].timings["cache_hit"], 1)
                self.assertEqual(results[-1].timings["model"], 0)
                self.assertEqual(errors, [])

    def test_a_b_a_while_first_a_is_running_joins_it_in_both_modes(self):
        for mode in ("ocr", "vl"):
            with self.subTest(mode=mode):
                worker, client, results, errors = self.worker(block_source="A")
                self.submit(worker, "A", mode)
                self.assertTrue(client.entered.wait(2))
                self.submit(worker, "B", mode)
                self.submit(worker, "A", mode)
                client.release.set()
                self.wait_until(lambda: not worker._busy)
                self.assertEqual(client.calls, [(mode, "A")])
                self.assertEqual([r.corrected for r in results], ["A"])
                self.assertEqual(results[0].timings["joined_request"], 1)
                self.assertGreaterEqual(results[0].timings["reuse_wait"], 0)
                self.assertEqual(errors, [])

    def test_repeated_a_after_run_before_finished_delivery_reuses_outcome(self):
        worker, client, results, errors = self.worker()
        self.submit(worker, "A")
        self.assertTrue(worker.wait(2000))
        self.assertTrue(worker._busy)
        self.assertEqual(results, [])
        self.submit(worker, "A")
        self.wait_until(lambda: not worker._busy)
        self.assertEqual(client.calls, [("ocr", "A")])
        self.assertEqual([r.corrected for r in results], ["A"])
        self.assertEqual(errors, [])

    def test_cached_a_displays_while_b_is_running_and_drops_queued_c(self):
        worker, client, results, errors = self.worker(block_source="B")
        self.complete(worker, "A")
        self.submit(worker, "B")
        self.assertTrue(client.entered.wait(2))
        self.submit(worker, "C")
        self.submit(worker, "A")
        self.assertEqual([r.corrected for r in results], ["A", "A"])
        self.assertTrue(worker._busy)
        client.release.set()
        self.wait_until(lambda: not worker._busy)
        self.assertEqual(client.calls, [("ocr", "A"), ("ocr", "B")])
        self.assertEqual([r.corrected for r in results], ["A", "A"])
        # The superseded B is still valid for a future observation.
        self.complete(worker, "B")
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(results[-1].corrected, "B")
        self.assertEqual(errors, [])

    def test_cancel_blocks_old_results_and_old_cache_refill(self):
        worker, client, results, errors = self.worker(block_source="A")
        self.submit(worker, "A")
        self.assertTrue(client.entered.wait(2))
        worker.cancel_pending()
        client.release.set()
        self.wait_until(lambda: not worker._busy)
        self.assertEqual(results, [])
        self.complete(worker, "A")
        self.assertEqual(client.calls, [("ocr", "A"), ("ocr", "A")])
        self.assertEqual([r.corrected for r in results], ["A"])
        self.assertEqual(errors, [])

    def test_cancel_then_same_a_does_not_join_cancelled_active_request(self):
        worker, client, results, errors = self.worker(block_source="A")
        self.submit(worker, "A")
        self.assertTrue(client.entered.wait(2))
        worker.cancel_pending()
        self.submit(worker, "A")
        client.release.set()
        self.wait_until(lambda: not worker._busy)
        self.assertEqual(client.calls, [("ocr", "A"), ("ocr", "A")])
        self.assertEqual(len(results), 1)
        self.assertNotIn("joined_request", results[0].timings)
        self.assertEqual(errors, [])

    def test_translator_change_ignores_old_active_result_and_uses_new_client(self):
        worker, old, results, errors = self.worker(block_source="A")
        self.submit(worker, "A")
        self.assertTrue(old.entered.wait(2))
        new = OfflineClient()
        worker.update_translator(Translator(new, translate_text_prompt="{text}"))
        self.submit(worker, "A")
        old.release.set()
        self.wait_until(lambda: not worker._busy)
        self.assertEqual(old.calls, [("ocr", "A")])
        self.assertEqual(new.calls, [("ocr", "A")])
        self.assertEqual(len(results), 1)
        self.complete(worker, "A")
        self.assertEqual(len(new.calls), 1)
        self.assertEqual(errors, [])

    def test_manual_retry_is_fresh_and_invalidates_previous_cached_answer(self):
        worker, client, results, errors = self.worker(responses=[
            {"corrected": "A", "translation": "旧译文"},
            {"corrected": "A", "translation": "手动新译文"},
            {"corrected": "A", "translation": "自动新译文"},
        ])
        self.complete(worker, "A")
        self.complete(worker, "A", automatic=False)
        self.complete(worker, "A")
        self.complete(worker, "A")
        self.assertEqual(len(client.calls), 3)
        self.assertEqual([r.translation for r in results],
                         ["旧译文", "手动新译文", "自动新译文", "自动新译文"])
        self.assertEqual(errors, [])

    def test_manual_request_does_not_join_active_automatic_request(self):
        worker, client, results, errors = self.worker(block_source="A")
        self.submit(worker, "A")
        self.assertTrue(client.entered.wait(2))
        self.submit(worker, "A", automatic=False)
        client.release.set()
        self.wait_until(lambda: not worker._busy)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(len(results), 1)
        self.assertEqual(errors, [])

    def test_failed_incomplete_and_null_translation_answers_are_not_cached(self):
        for response in (RuntimeError("offline"),
                         {"corrected": "A", "translation": ""},
                         {"corrected": "A", "translation": None}):
            with self.subTest(response=response):
                worker, client, results, errors = self.worker(responses=[response])
                self.complete(worker, "A")
                self.complete(worker, "A")
                self.assertEqual(client.calls, [("ocr", "A"), ("ocr", "A")])
                self.assertEqual(results[-1].translation, "译文 A")
                self.assertEqual(errors, [])

    def test_partial_choice_answer_is_not_cached(self):
        scene = pack_scene_text("A", ["Yes.", "No."])
        partial = {"corrected": "A", "translation": "译文 A", "choices": [
            {"index": 1, "corrected": "Yes.", "translation": "是。"}]}
        worker, client, results, errors = self.worker(responses=[partial])
        self.complete(worker, scene)
        self.assertTrue(results[-1].warning)
        self.complete(worker, scene)
        self.assertEqual(client.calls, [("ocr", scene), ("ocr", scene)])
        self.assertTrue(all(c.translation for c in results[-1].choices))
        self.assertEqual(errors, [])

    def test_mode_numbers_negation_and_choice_order_are_distinct(self):
        worker, client, results, errors = self.worker()
        texts = ["Take 2 apples.", "Take 3 apples.", "Do take it.", "Do not take it.",
                 pack_scene_text("A", ["Yes.", "No."]),
                 pack_scene_text("A", ["No.", "Yes."]),
                 pack_scene_text("A", ["Yes."])]
        for text in texts:
            self.complete(worker, text)
        self.complete(worker, texts[0], "vl")
        self.assertEqual(len(client.calls), len(texts) + 1)
        self.complete(worker, texts[0])
        self.assertEqual(len(client.calls), len(texts) + 1)
        self.assertEqual(results[-1].timings["cache_hit"], 1)
        self.assertEqual(errors, [])

    def test_layout_and_curly_quotes_normalize_without_additional_call(self):
        worker, client, results, errors = self.worker()
        self.complete(worker, "It’s\n a test .")
        self.complete(worker, "It's a test.")
        scene = pack_scene_text("It’s a test .", ["Yes .", "No ."])
        normalized = pack_scene_text("It's a test.", ["Yes.", "No."])
        self.complete(worker, scene)
        self.complete(worker, normalized)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(results[-1].timings["cache_hit"], 1)
        self.assertEqual(errors, [])

    def test_lru_is_bounded_and_cache_hits_refresh_recentness(self):
        worker, client, results, errors = self.worker()
        worker.CACHE_LIMIT = 3
        for text in ("A", "B", "C", "A", "D", "A", "B"):
            self.complete(worker, text)
        self.assertEqual(client.calls, [("ocr", t) for t in ("A", "B", "C", "D", "B")])
        self.assertEqual(len(worker._cache), 3)
        self.assertEqual(results[-1].corrected, "B")
        self.assertEqual(errors, [])

    def test_delivered_results_and_timings_do_not_mutate_cache(self):
        worker, client, results, errors = self.worker()
        self.complete(worker, "A")
        results[-1].translation = "modified first delivery"
        results[-1].timings["model"] = 999
        self.complete(worker, "A")
        self.assertEqual(results[-1].translation, "译文 A")
        self.assertEqual(results[-1].timings["model"], 0)
        self.assertEqual(results[-1].timings["total"], 0)
        results[-1].translation = "modified cached delivery"
        results[-1].timings["model"] = 111
        self.complete(worker, "A")
        self.assertEqual(results[-1].translation, "译文 A")
        self.assertEqual(results[-1].timings["model"], 0)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(errors, [])

    def test_no_ocr_identity_never_reuses_vision_cache(self):
        worker, client, results, errors = self.worker()
        for _ in range(2):
            self.submit(worker, "A", mode="vl", observed=False)
            self.wait_until(lambda: not worker._busy)
        self.assertEqual(client.calls, [("vl", "A"), ("vl", "A")])
        self.assertEqual(len(results), 2)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
