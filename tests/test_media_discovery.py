from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ja2zh_subtitle.media import find_media_binary


class MediaDiscoveryTests(unittest.TestCase):
    def test_explicit_override_finds_binary_outside_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "ffmpeg.exe"
            executable.write_bytes(b"test")
            with (
                patch.dict(os.environ, {"JA2ZH_FFMPEG": str(executable)}),
                patch("ja2zh_subtitle.media.shutil.which", return_value=None),
            ):
                self.assertEqual(find_media_binary("ffmpeg"), str(executable.resolve()))

    def test_registered_windows_path_is_checked_after_process_path(self) -> None:
        expected = r"C:\tools\ffmpeg\bin\ffprobe.exe"

        def fake_which(name: str, path: str | None = None) -> str | None:
            if path == r"C:\tools\ffmpeg\bin":
                return expected
            return None

        with (
            patch.dict(os.environ, {"JA2ZH_FFPROBE": ""}),
            patch("ja2zh_subtitle.media.shutil.which", side_effect=fake_which),
            patch(
                "ja2zh_subtitle.media._windows_registry_paths",
                return_value=[r"C:\tools\ffmpeg\bin"],
            ),
        ):
            self.assertEqual(find_media_binary("ffprobe"), str(Path(expected).resolve()))


if __name__ == "__main__":
    unittest.main()
