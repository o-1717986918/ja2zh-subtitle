from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ja2zh_subtitle.cache import StageCache
from ja2zh_subtitle.models import SubtitleCue


class CacheTests(unittest.TestCase):
    def test_signature_controls_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cache = StageCache(Path(temp))
            cues = [SubtitleCue(1, 0.0, 1.0, "テスト")]
            cache.save("asr", "right", cues)
            self.assertIsNone(cache.load("asr", "wrong"))
            loaded = cache.load("asr", "right")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded[0].ja, "テスト")


if __name__ == "__main__":
    unittest.main()

