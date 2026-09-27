from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ja2zh_subtitle.asr import (
    merge_recovered_cues,
    segments_to_cues,
    uncovered_intervals,
)
from ja2zh_subtitle.models import SubtitleCue, WordTiming
from ja2zh_subtitle.config import load_config
from ja2zh_subtitle.pipeline import SubtitlePipeline


class JapaneseOnlyTests(unittest.TestCase):
    def test_words_are_joined_across_whisper_segment_boundaries(self) -> None:
        segments = [
            SimpleNamespace(
                words=[SimpleNamespace(start=0.0, end=0.2, word="浮", probability=0.9)]
            ),
            SimpleNamespace(
                words=[SimpleNamespace(start=0.21, end=0.5, word="気すんなよ。", probability=0.9)]
            ),
        ]
        cues = segments_to_cues(
            segments,
            {
                "max_segment_chars": 34,
                "max_segment_duration": 7.0,
                "pause_split_seconds": 0.75,
            },
        )
        self.assertEqual([cue.ja for cue in cues], ["浮気すんなよ。"])

    def test_incomplete_ending_waits_for_next_word(self) -> None:
        segments = [
            SimpleNamespace(
                words=[
                    SimpleNamespace(start=0.0, end=1.0, word="長い文章だと思", probability=0.9),
                    SimpleNamespace(start=1.01, end=1.2, word="う", probability=0.9),
                ]
            )
        ]
        cues = segments_to_cues(
            segments,
            {
                "max_segment_chars": 7,
                "max_segment_duration": 7.0,
                "max_segment_overrun_chars": 4,
                "pause_split_seconds": 0.75,
            },
        )
        self.assertEqual([cue.ja for cue in cues], ["長い文章だと思う"])

    def test_uncovered_intervals_include_long_gaps(self) -> None:
        cues = [
            SubtitleCue(1, 1.0, 3.0, "一"),
            SubtitleCue(2, 5.0, 6.0, "二"),
        ]
        self.assertEqual(
            uncovered_intervals(cues, duration=9.0, min_gap=1.5),
            [(3.0, 5.0), (6.0, 9.0)],
        )

    def test_recovery_cues_are_merged_and_deduplicated(self) -> None:
        primary = [SubtitleCue(1, 1.0, 2.0, "こんにちは")]
        recovered = [
            SubtitleCue(1, 1.1, 1.9, "こんにちは", origin="gap_recovery"),
            SubtitleCue(2, 3.0, 3.5, "はい", origin="gap_recovery"),
        ]
        result = merge_recovered_cues(primary, recovered)
        self.assertEqual([cue.ja for cue in result], ["こんにちは", "はい"])
        self.assertEqual(result[1].origin, "gap_recovery")

    def test_recovery_overlap_keeps_only_missing_lead_in(self) -> None:
        primary = [
            SubtitleCue(
                1,
                5.0,
                6.0,
                "新しく始めた仕事だ",
                words=[WordTiming(5.0, 5.2, "新しく", 0.9)],
            )
        ]
        recovered = [
            SubtitleCue(
                1,
                4.0,
                5.2,
                "お父さんが新しい",
                words=[
                    WordTiming(4.0, 4.4, "お父さん", 0.9),
                    WordTiming(4.4, 4.9, "が", 0.9),
                    WordTiming(4.9, 5.2, "新しい", 0.7),
                ],
                origin="gap_recovery",
            )
        ]
        result = merge_recovered_cues(primary, recovered)
        self.assertEqual([cue.ja for cue in result], ["お父さんが新しく始めた仕事だ"])
        self.assertEqual(result[0].origin, "merged")

    @patch("ja2zh_subtitle.pipeline.probe_media")
    @patch("ja2zh_subtitle.pipeline.extract_audio")
    def test_japanese_only_does_not_create_translator(
        self, extract_audio_mock, probe_mock
    ) -> None:
        probe_mock.return_value = {
            "streams": [{"codec_type": "audio"}],
            "format": {"duration": "3.0"},
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "sample.mp4"
            source.write_bytes(b"mock-video")
            output = root / "out"
            config = load_config(None, "lite")
            config["runtime"]["mock"] = True
            config["runtime"]["output_dir"] = str(output)
            pipeline = SubtitlePipeline(config, root)
            with patch(
                "ja2zh_subtitle.pipeline.create_polisher",
                side_effect=AssertionError("polisher must not load"),
            ):
                result = pipeline.run(
                    source,
                    japanese_only=True,
                    subtitle_only=True,
                    force=True,
                )
            self.assertTrue(result.raw_japanese_srt.is_file())
            self.assertTrue(result.japanese_srt.is_file())
            self.assertTrue(result.japanese_ass.is_file())
            self.assertIsNone(result.raw_chinese_srt)
            self.assertIsNone(result.video)

    @patch("ja2zh_subtitle.pipeline.probe_media")
    @patch("ja2zh_subtitle.pipeline.extract_audio")
    @patch("ja2zh_subtitle.pipeline.burn_subtitles")
    def test_japanese_only_burns_video_by_default(
        self, burn_mock, extract_audio_mock, probe_mock
    ) -> None:
        probe_mock.return_value = {
            "streams": [{"codec_type": "audio"}],
            "format": {"duration": "3.0"},
        }
        burn_mock.side_effect = lambda _video, _subtitle, output, _config: output.write_bytes(
            b"mock-output"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "sample.mp4"
            source.write_bytes(b"mock-video")
            config = load_config(None, "lite")
            config["runtime"]["mock"] = True
            config["runtime"]["output_dir"] = str(root / "out")
            pipeline = SubtitlePipeline(config, root)
            result = pipeline.run(source, japanese_only=True, force=True)
            self.assertEqual(result.video.name, "sample_ja_sub.mp4")
            self.assertTrue(result.video.is_file())
            burn_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
