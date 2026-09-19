"""Count adapter calls with fake SDKs: no credentials or network required."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from src.core.llm_client import DashScopeClient


def response(status=200, message="", content="translated"):
    return SimpleNamespace(
        status_code=status, message=message,
        output=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content))]),
    )


class DashScopeRetryTests(unittest.TestCase):
    def setUp(self):
        self.generation = Mock(return_value=response())
        self.multimodal = Mock(return_value=response(content=[{"text": "translated"}]))
        self.client = object.__new__(DashScopeClient)
        self.client._ds = SimpleNamespace(
            api_key="offline-test", Generation=SimpleNamespace(call=self.generation),
            MultiModalConversation=SimpleNamespace(call=self.multimodal),
        )
        self.client._text_model = "fake-text"
        self.client._vl_model = "fake-vision"
        self.client._thinking_mode = "off"
        self.messages = [{"role": "user", "content": "A single sentence."}]

    def test_successful_text_uses_one_call(self):
        self.assertEqual(self.client.chat(self.messages), "translated")
        self.generation.assert_called_once()
        self.multimodal.assert_not_called()

    def test_url_error_falls_back_once_and_preserves_prompt(self):
        self.generation.return_value = response(400, "Please check url: url error")
        self.assertEqual(self.client.chat(self.messages), "translated")
        self.generation.assert_called_once()
        self.multimodal.assert_called_once()
        self.assertEqual(self.multimodal.call_args.kwargs["messages"], [
            {"role": "user", "content": [{"text": "A single sentence."}]}])
        self.assertFalse(self.multimodal.call_args.kwargs["enable_thinking"])

    def test_failed_url_fallback_is_not_sent_twice(self):
        self.generation.return_value = response(400, "url error")
        self.multimodal.return_value = response(400, "invalid model")
        with self.assertRaisesRegex(RuntimeError, "invalid model"):
            self.client.chat(self.messages)
        self.generation.assert_called_once()
        self.multimodal.assert_called_once()

    def test_fallback_exception_is_not_retried_or_hidden(self):
        self.generation.side_effect = RuntimeError("400 url error")
        self.multimodal.side_effect = RuntimeError("400 fallback failed")
        with self.assertRaisesRegex(RuntimeError, "fallback failed"):
            self.client.chat(self.messages)
        self.generation.assert_called_once()
        self.multimodal.assert_called_once()

    def test_auth_server_or_timeout_errors_do_not_try_another_endpoint(self):
        for failure in (response(401, "unauthorized"), response(500, "server error"),
                        TimeoutError("timed out")):
            with self.subTest(failure=failure):
                self.generation.reset_mock()
                self.multimodal.reset_mock()
                self.generation.side_effect = failure if isinstance(failure, Exception) else None
                self.generation.return_value = failure
                with self.assertRaises((RuntimeError, TimeoutError)):
                    self.client.chat(self.messages)
                self.generation.assert_called_once()
                self.multimodal.assert_not_called()

    def test_successful_vision_does_not_send_base64_again(self):
        with patch("src.core.llm_client._save_image_to_temp", return_value="offline.png"), \
                patch("src.core.llm_client.os.unlink") as remove:
            self.assertEqual(self.client.chat_vision("Read it", Image.new("RGB", (5, 5))),
                             "translated")
        self.multimodal.assert_called_once()
        remove.assert_called_once_with("offline.png")

    def test_vision_file_fallback_is_bounded_even_when_base64_fails(self):
        self.multimodal.side_effect = [response(400, "unsupported image"),
                                      response(400, "invalid model")]
        with patch("src.core.llm_client._save_image_to_temp", return_value="offline.png"), \
                patch("src.core.llm_client.os.unlink") as remove:
            with self.assertRaisesRegex(RuntimeError, "invalid model"):
                self.client.chat_vision("Read it", Image.new("RGB", (5, 5)))
        self.assertEqual(self.multimodal.call_count, 2)
        sent_images = [call.kwargs["messages"][0]["content"][0]["image"]
                       for call in self.multimodal.call_args_list]
        self.assertTrue(sent_images[0].startswith("file:///"))
        self.assertTrue(sent_images[1].startswith("data:image/png;base64,"))
        remove.assert_called_once_with("offline.png")


if __name__ == "__main__":
    unittest.main()
