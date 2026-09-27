from __future__ import annotations

import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from ja2zh_subtitle.polisher import (
    DeepSeekPolisher,
    PolishFormatError,
    extract_json_array,
    polish_quality_error,
    validate_polish_quality,
    validate_polish_result,
    validate_translation_polish_result,
)
from ja2zh_subtitle.models import SubtitleCue


class PolisherTests(unittest.TestCase):
    def test_extract_fenced_json(self) -> None:
        value = extract_json_array('```json\n[{"id": 1, "zh": "你好。"}]\n```')
        self.assertEqual(value[0]["zh"], "你好。")

    def test_reject_changed_ids(self) -> None:
        with self.assertRaises(PolishFormatError):
            validate_polish_result([{"id": 2, "zh": "错误"}], [1])

    def test_accept_polished_zh_alias(self) -> None:
        result = validate_polish_result([{"id": "1", "polished_zh": "你好"}], [1])
        self.assertEqual(result, {1: "你好"})

    def test_reject_japanese_polish_content(self) -> None:
        cue = SubtitleCue(1, 0.0, 1.0, "昨日は楽しかった", "昨天很开心。")
        result = {1: "昨日は楽しかった"}
        self.assertEqual(
            validate_polish_quality(result, [cue]), {1: "仍包含日文假名"}
        )

    def test_reject_punctuation_garbage(self) -> None:
        cue = SubtitleCue(1, 0.0, 1.0, "ごめんなさい", ",,,,,")
        self.assertEqual(polish_quality_error("，，，，，", cue), "包含连续重复标点")

    def test_accept_simplified_chinese_polish(self) -> None:
        cue = SubtitleCue(1, 0.0, 1.0, "ごめんなさい", "对不起。")
        self.assertIsNone(polish_quality_error("真的很抱歉。", cue))

    def test_accept_literal_and_polished_translation(self) -> None:
        result = validate_translation_polish_result(
            [{"id": 1, "literal_zh": "不许出轨。", "zh": "不准背着我乱来。"}],
            [1],
        )
        self.assertEqual(result[1], ("不许出轨。", "不准背着我乱来。"))

    def test_deepseek_requires_key_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            prompt = Path(temp) / "prompt.txt"
            prompt.write_text("输出 JSON", encoding="utf-8")
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
                with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY"):
                    DeepSeekPolisher(
                        {
                            "api_key_env": "DEEPSEEK_API_KEY",
                            "model": "deepseek-v4-flash",
                        },
                        prompt,
                    )

    def test_deepseek_uses_json_non_thinking_chat_completion(self) -> None:
        class FakeResponse:
            status_code = 200
            headers: dict[str, str] = {}

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"subtitles":[{"id":1,"literal_zh":"你好","zh":"你好"}]}'
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 8},
                }

        class FakeClient:
            def __init__(self) -> None:
                self.url = ""
                self.body: dict = {}

            def post(self, url: str, json: dict) -> FakeResponse:
                self.url = url
                self.body = json
                return FakeResponse()

        import httpx

        polisher = DeepSeekPolisher.__new__(DeepSeekPolisher)
        polisher.httpx = httpx
        polisher.config = {
            "model": "deepseek-v4-flash",
            "thinking": "disabled",
            "max_new_tokens": 4096,
            "api_retries": 0,
        }
        polisher.base_url = "https://api.deepseek.com"
        polisher.client = FakeClient()
        result = polisher._generate("请输出 JSON")
        self.assertIn("subtitles", result)
        self.assertEqual(
            polisher.client.url, "https://api.deepseek.com/chat/completions"
        )
        self.assertEqual(polisher.client.body["response_format"], {"type": "json_object"})
        self.assertEqual(polisher.client.body["thinking"], {"type": "disabled"})


if __name__ == "__main__":
    unittest.main()
