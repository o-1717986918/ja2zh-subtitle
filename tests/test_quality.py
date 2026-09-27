from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ja2zh_subtitle.models import SubtitleCue
from ja2zh_subtitle.quality import (
    inspect_cues,
    timeline_problems,
    write_review_report,
)


class QualityTests(unittest.TestCase):
    def test_flags_low_confidence_and_fast_cue(self) -> None:
        cues = [SubtitleCue(1, 0.0, 0.2, "長い字幕です", confidence=0.3)]
        issues = inspect_cues(cues, "ja", {"min_confidence": 0.55})
        self.assertEqual(len(issues), 1)
        self.assertGreaterEqual(len(issues[0].reasons), 2)

    def test_writes_human_readable_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.txt"
            write_review_report(
                [SubtitleCue(1, 0.0, 1.0, "え", confidence=0.9)],
                path,
                {},
            )
            content = path.read_text(encoding="utf-8")
            self.assertIn("建议复核：1", content)
            self.assertIn("疑似孤立单字", content)

    def test_warn_report_records_recovered_cues_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.txt"
            write_review_report(
                [SubtitleCue(1, 2.0, 3.0, "はい", origin="gap_recovery")],
                path,
                {"mode": "warn", "report_gap_seconds": 1.5},
                duration=5.0,
            )
            content = path.read_text(encoding="utf-8")
            self.assertIn("质量模式：warn", content)
            self.assertIn("补识别恢复：1", content)
            self.assertIn("较长无字幕区间", content)

    def test_timeline_problems_are_always_detected(self) -> None:
        cues = [
            SubtitleCue(1, 1.0, 2.0, "一"),
            SubtitleCue(2, 1.5, 3.0, "二"),
        ]
        self.assertTrue(timeline_problems(cues))


if __name__ == "__main__":
    unittest.main()
