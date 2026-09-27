from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from main import collect_videos


class CliTests(unittest.TestCase):
    def test_collects_supported_videos_and_skips_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.mp4").write_bytes(b"a")
            (root / "a_ja_sub.mp4").write_bytes(b"a")
            (root / "note.txt").write_text("x", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "b.mkv").write_bytes(b"b")
            self.assertEqual([path.name for path in collect_videos(root, False)], ["a.mp4"])
            self.assertEqual(
                [path.name for path in collect_videos(root, True)],
                ["a.mp4", "b.mkv"],
            )


if __name__ == "__main__":
    unittest.main()
