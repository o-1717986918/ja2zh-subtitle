from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ja2zh_subtitle.models import SubtitleCue
from ja2zh_subtitle.subtitle import (
    normalize_chinese,
    normalize_japanese,
    prepare_final_cues,
    prepare_japanese_cues,
    srt_timestamp,
    wrap_japanese_cues,
    write_ass,
    write_srt,
)


class SubtitleTests(unittest.TestCase):
    def test_timestamp(self) -> None:
        self.assertEqual(srt_timestamp(3661.234), "01:01:01,234")

    def test_normalize(self) -> None:
        self.assertEqual(normalize_chinese(" 你好, 世界!! "), "你好， 世界！")

    def test_japanese_normalize_and_deduplicate(self) -> None:
        cues = [
            SubtitleCue(1, 0.0, 0.8, "こんにちは!!"),
            SubtitleCue(2, 0.9, 1.5, "こんにちは!!"),
        ]
        result = prepare_japanese_cues(
            cues,
            {"minimum_gap": 0.05, "min_duration": 0.5, "duplicate_gap": 0.35},
        )
        self.assertEqual(normalize_japanese("こんにちは!!"), "こんにちは！")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].ja, "こんにちは！")

    def test_japanese_wrap_preserves_all_text(self) -> None:
        text = "これは少し長い日本語字幕なので二行に分けて表示します。"
        result = wrap_japanese_cues(
            [SubtitleCue(1, 0.0, 2.0, text)],
            {"max_chars_per_line": 16, "max_lines": 2},
        )
        self.assertIn("\n", result[0].ja)
        self.assertEqual(result[0].ja.replace("\n", ""), text)

    def test_long_cue_is_split_and_non_overlapping(self) -> None:
        cues = [
            SubtitleCue(
                1,
                0.0,
                6.0,
                "長い台詞",
                raw_zh="这是第一句话。这是第二句话。这是第三句话。这是第四句话。",
                zh="这是第一句话。这是第二句话。这是第三句话。这是第四句话。",
            )
        ]
        config = {
            "max_chars_per_line": 8,
            "max_lines": 2,
            "min_duration": 0.5,
            "max_duration": 7.0,
            "minimum_gap": 0.05,
        }
        result = prepare_final_cues(cues, config)
        self.assertGreater(len(result), 1)
        self.assertTrue(all(result[i].end <= result[i + 1].start for i in range(len(result) - 1)))

    def test_writers(self) -> None:
        cues = [SubtitleCue(1, 0.0, 1.2, "こんにちは", "你好", "你好")]
        config = {"font_name": "sans-serif", "font_size": 42}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            srt = write_srt(cues, root / "test.srt")
            ass = write_ass(cues, root / "test.ass", config)
            self.assertIn("你好", srt.read_text(encoding="utf-8"))
            self.assertIn("Dialogue:", ass.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
