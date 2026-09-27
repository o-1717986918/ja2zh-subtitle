from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)


class MediaError(RuntimeError):
    pass


_MEDIA_BINARIES = {"ffmpeg", "ffprobe"}
_MEDIA_ENV_VARS = {
    "ffmpeg": "JA2ZH_FFMPEG",
    "ffprobe": "JA2ZH_FFPROBE",
}


def _binary_from_path(value: str, name: str) -> str | None:
    expanded = Path(os.path.expandvars(value)).expanduser()
    candidates = [expanded]
    if expanded.is_dir():
        candidates = [expanded / name, expanded / f"{name}.exe"]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def _windows_registry_paths() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    locations = (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    )
    paths: list[str] = []
    for hive, key_name in locations:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        paths.extend(
            os.path.expandvars(item.strip())
            for item in str(value).split(os.pathsep)
            if item.strip()
        )
    return paths


def _windows_winget_candidates(name: str) -> list[Path]:
    if sys.platform != "win32":
        return []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return []
    packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    if not packages.is_dir():
        return []
    pattern = f"Gyan.FFmpeg_*{os.sep}ffmpeg-*{os.sep}bin{os.sep}{name}.exe"
    return sorted(
        packages.glob(pattern),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def find_media_binary(name: str) -> str | None:
    """Locate FFmpeg tools even when the current Windows shell has a stale PATH."""
    normalized = Path(name).stem.lower()
    if normalized not in _MEDIA_BINARIES:
        raise ValueError(f"不支持的媒体工具：{name}")

    override = os.environ.get(_MEDIA_ENV_VARS[normalized], "").strip()
    if override:
        found = _binary_from_path(override, normalized)
        if found:
            return found

    found = shutil.which(normalized)
    if found:
        return str(Path(found).resolve())

    registry_paths = _windows_registry_paths()
    if registry_paths:
        found = shutil.which(normalized, path=os.pathsep.join(registry_paths))
        if found:
            return str(Path(found).resolve())

    for candidate in _windows_winget_candidates(normalized):
        if candidate.is_file():
            return str(candidate.resolve())

    executable_dir = Path(sys.executable).resolve().parent
    for directory in (executable_dir, executable_dir / "Library" / "bin"):
        found = _binary_from_path(str(directory), normalized)
        if found:
            return found
    return None


def _resolve_media_command(command: list[str]) -> list[str]:
    if not command:
        raise ValueError("媒体命令不能为空")
    name = Path(command[0]).stem.lower()
    if name not in _MEDIA_BINARIES:
        return command
    executable = find_media_binary(name)
    if executable is None:
        raise MediaError(
            f"找不到 {name}，请安装 FFmpeg，或设置 {_MEDIA_ENV_VARS[name]} 指定路径"
        )
    return [executable, *command[1:]]


def _run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = _resolve_media_command(command)
    LOGGER.debug("执行命令：%s", " ".join(command))
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        tail = "\n".join(result.stderr.splitlines()[-20:])
        raise MediaError(f"媒体命令失败（退出码 {result.returncode}）：\n{tail}")
    return result


def require_ffmpeg() -> None:
    missing = [name for name in _MEDIA_BINARIES if find_media_binary(name) is None]
    if missing:
        variables = ", ".join(_MEDIA_ENV_VARS[name] for name in sorted(missing))
        raise MediaError(
            f"找不到 {', '.join(sorted(missing))}，请安装 FFmpeg 并加入 PATH，"
            f"或通过 {variables} 指定路径"
        )


def probe_media(path: Path) -> dict[str, Any]:
    require_ffmpeg()
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError("ffprobe 返回了无法解析的数据") from exc


def media_duration(probe: dict[str, Any]) -> float:
    try:
        return float(probe.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        return 0.0


def audio_streams(probe: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in probe.get("streams", []) if item.get("codec_type") == "audio"]


def extract_audio(video: Path, output: Path, audio_stream: int = 0) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "warning",
            "-i",
            str(video),
            "-map",
            f"0:a:{audio_stream}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
    )
    return output


def _escape_filter_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return value.replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")


def burn_subtitles(
    video: Path,
    subtitle: Path,
    output: Path,
    config: dict[str, Any],
    style: dict[str, Any] | None = None,
) -> Path:
    if not subtitle.is_file():
        raise FileNotFoundError(f"字幕文件不存在：{subtitle}")
    subtitle_format = subtitle.suffix.lower()
    if subtitle_format not in {".ass", ".srt"}:
        raise ValueError("字幕烧录只支持 ASS 或 SRT")
    output.parent.mkdir(parents=True, exist_ok=True)
    codec_name = str(config.get("codec", "h264")).lower()
    video_codec = {
        "h264": "libx264",
        "x264": "libx264",
        "h265": "libx265",
        "hevc": "libx265",
        "x265": "libx265",
    }.get(codec_name)
    if video_codec is None:
        raise ValueError(f"不支持的视频编码：{codec_name}")

    subtitle_path = _escape_filter_path(subtitle)
    filter_name = "ass" if subtitle_format == ".ass" else "subtitles"
    filter_value = f"{filter_name}=filename='{subtitle_path}'"
    fonts_dir = str(config.get("fonts_dir", "")).strip()
    if fonts_dir:
        font_path = Path(fonts_dir)
        if not font_path.is_dir():
            raise FileNotFoundError(f"字幕字体目录不存在：{font_path}")
        filter_value += f":fontsdir='{_escape_filter_path(font_path)}'"
    if subtitle_format == ".srt" and style:
        force_style = ",".join(
            [
                f"FontName={style.get('font_name', 'sans-serif')}",
                f"FontSize={style.get('font_size', 48)}",
                f"PrimaryColour={style.get('primary_colour', '&H00FFFFFF')}",
                f"OutlineColour={style.get('outline_colour', '&H00000000')}",
                f"Outline={style.get('outline', 2.2)}",
                f"Shadow={style.get('shadow', 0.8)}",
                "Alignment=2",
                f"MarginV={style.get('margin_v', 48)}",
            ]
        )
        filter_value += f":force_style='{force_style}'"

    base = [
        "ffmpeg",
        "-y",
        "-v",
        "warning",
        "-i",
        str(video),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        filter_value,
        "-c:v",
        video_codec,
        "-preset",
        str(config.get("preset", "medium")),
        "-crf",
        str(config.get("crf", 20)),
        "-map_metadata",
        "0",
        "-movflags",
        "+faststart",
    ]
    if config.get("audio_copy", True):
        try:
            _run(base + ["-c:a", "copy", str(output)])
            return output
        except MediaError:
            LOGGER.warning("原音频无法直接封装，改用音频转码")

    _run(
        base
        + [
            "-c:a",
            str(config.get("audio_fallback_codec", "aac")),
            "-b:a",
            str(config.get("audio_bitrate", "192k")),
            str(output),
        ]
    )
    return output


def ffmpeg_has_libass() -> bool:
    executable = find_media_binary("ffmpeg")
    if executable is None:
        return False
    result = subprocess.run(
        [executable, "-hide_banner", "-filters"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return " subtitles " in result.stdout or " ass " in result.stdout
