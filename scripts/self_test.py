from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ja2zh_subtitle.media import find_media_binary


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    ffmpeg = find_media_binary("ffmpeg")
    ffprobe = find_media_binary("ffprobe")
    if not ffmpeg or not ffprobe:
        print("自检失败：找不到 ffmpeg/ffprobe", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="ja2zh-self-test-") as temp:
        work = Path(temp)
        video = work / "sample.mp4"
        output = work / "output"
        japanese_output = work / "japanese-output"
        reburn_output = work / "reburn-output"
        run(
            [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x243447:s=640x360:d=6:r=24",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=6",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(video),
            ]
        )
        run(
            [
                sys.executable,
                "main.py",
                str(video),
                "--mock",
                "--ja-only",
                "--force",
                "--output-dir",
                str(japanese_output),
            ]
        )
        run(
            [
                sys.executable,
                "main.py",
                str(video),
                "--mock",
                "--force",
                "--output-dir",
                str(output),
            ]
        )
        expected = [
            output / "sample_review.txt",
            output / "sample_ja.srt",
            output / "sample_raw_zh.srt",
            output / "sample_zh.srt",
            output / "sample_zh.ass",
            output / "sample_zh_sub.mp4",
        ]
        missing = [str(path) for path in expected if not path.is_file() or path.stat().st_size == 0]
        if missing:
            print("自检失败，缺少输出：", *missing, sep="\n", file=sys.stderr)
            return 1
        japanese_expected = [
            japanese_output / "sample_raw_ja.srt",
            japanese_output / "sample_ja.srt",
            japanese_output / "sample_ja.ass",
            japanese_output / "sample_review.txt",
            japanese_output / "sample_ja_sub.mp4",
        ]
        japanese_missing = [
            str(path)
            for path in japanese_expected
            if not path.is_file() or path.stat().st_size == 0
        ]
        if japanese_missing:
            print(
                "日语工作流自检失败，缺少输出：",
                *japanese_missing,
                sep="\n",
                file=sys.stderr,
            )
            return 1
        run(
            [
                sys.executable,
                "main.py",
                str(video),
                "--burn-subtitle",
                str(japanese_output / "sample_ja.srt"),
                "--subtitle-language",
                "ja",
                "--output-dir",
                str(reburn_output),
            ]
        )
        reburn_video = reburn_output / "sample_ja_sub.mp4"
        if not reburn_video.is_file() or reburn_video.stat().st_size == 0:
            print("SRT 重新烧录自检失败", file=sys.stderr)
            return 1
        run([ffprobe, "-v", "error", "-show_format", str(expected[-1])])
        run([ffprobe, "-v", "error", "-show_format", str(japanese_expected[-1])])
        run([ffprobe, "-v", "error", "-show_format", str(reburn_video)])
        print("\n自检通过：中日字幕分支、质量报告、SRT/ASS 和重新烧录均可运行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
