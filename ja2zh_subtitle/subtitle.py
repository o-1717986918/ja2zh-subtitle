from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Iterable

from .models import SubtitleCue


PUNCTUATION_MAP = str.maketrans(
    {
        ",": "，",
        "?": "？",
        "!": "！",
        ";": "；",
    }
)
JAPANESE_PUNCTUATION_MAP = str.maketrans(
    {
        ",": "、",
        ".": "。",
        "?": "？",
        "!": "！",
    }
)
SPLIT_AFTER = set("。！？；…")


def normalize_chinese(text: str) -> str:
    text = text.replace("\r", "").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.translate(PUNCTUATION_MAP)
    text = re.sub(r"([，。！？；：、])\1+", r"\1", text)
    text = text.replace("...", "……")
    return text.strip()


def normalize_japanese(text: str) -> str:
    """Conservatively normalize ASR text without guessing missing dialogue."""
    text = text.replace("\r", "").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.translate(JAPANESE_PUNCTUATION_MAP)
    text = re.sub(r"([、。！？])\1+", r"\1", text)
    text = re.sub(r"(?:\.\.\.|…{2,})", "……", text)
    return text.strip()


def visible_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def split_text(text: str, limit: int) -> list[str]:
    text = normalize_chinese(text)
    if visible_length(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for char in text:
        current += char
        length = visible_length(current)
        if length >= limit or char in SPLIT_AFTER and length >= max(5, limit // 2):
            parts.append(current.strip())
            current = ""
    if current.strip():
        parts.append(current.strip())
    return [part for part in parts if part]


def split_long_cues(cues: Iterable[SubtitleCue], config: dict) -> list[SubtitleCue]:
    per_line = max(4, int(config.get("max_chars_per_line", 18)))
    max_lines = max(1, int(config.get("max_lines", 2)))
    total_limit = per_line * max_lines
    result: list[SubtitleCue] = []
    for cue in cues:
        source_text = cue.zh or cue.raw_zh or cue.ja
        parts = split_text(source_text, total_limit)
        if len(parts) == 1:
            cloned = copy.deepcopy(cue)
            cloned.zh = normalize_chinese(source_text)
            result.append(cloned)
            continue
        weights = [max(1, visible_length(part)) for part in parts]
        total_weight = sum(weights)
        duration = max(0.1, cue.end - cue.start)
        cursor = cue.start
        for index, (part, weight) in enumerate(zip(parts, weights, strict=True)):
            part_duration = duration * weight / total_weight
            end = cue.end if index == len(parts) - 1 else cursor + part_duration
            cloned = copy.deepcopy(cue)
            cloned.start = cursor
            cloned.end = end
            cloned.zh = part
            cloned.words = []
            result.append(cloned)
            cursor = end
    for index, cue in enumerate(result, start=1):
        cue.id = index
    return result


def optimize_timings(cues: list[SubtitleCue], config: dict) -> list[SubtitleCue]:
    if not cues:
        return cues
    min_duration = max(0.1, float(config.get("min_duration", 0.8)))
    max_duration = max(min_duration, float(config.get("max_duration", 7.0)))
    gap = max(0.0, float(config.get("minimum_gap", 0.06)))
    result = [copy.deepcopy(cue) for cue in cues]
    for index, cue in enumerate(result):
        cue.start = max(0.0, cue.start)
        if index > 0 and cue.start < result[index - 1].end + gap:
            cue.start = result[index - 1].end + gap
        desired_end = max(cue.end, cue.start + min_duration)
        desired_end = min(desired_end, cue.start + max_duration)
        if index + 1 < len(result):
            latest = max(cue.start + 0.08, result[index + 1].start - gap)
            desired_end = min(desired_end, latest)
        cue.end = max(cue.start + 0.08, desired_end)
    return result


def wrap_text(text: str, width: int, max_lines: int) -> str:
    text = normalize_chinese(text)
    if visible_length(text) <= width:
        return text
    lines: list[str] = []
    current = ""
    for char in text:
        current += char
        if visible_length(current) >= width:
            lines.append(current.strip())
            current = ""
            if len(lines) == max_lines - 1:
                break
    consumed = sum(len(line) for line in lines)
    remainder = text[consumed:].strip()
    if remainder:
        lines.append(remainder)
    return "\n".join(lines[:max_lines])


def prepare_final_cues(cues: list[SubtitleCue], config: dict) -> list[SubtitleCue]:
    result = split_long_cues(cues, config)
    result = optimize_timings(result, config)
    width = int(config.get("max_chars_per_line", 18))
    max_lines = int(config.get("max_lines", 2))
    for cue in result:
        cue.zh = wrap_text(cue.zh, width, max_lines)
    return result


def prepare_japanese_cues(cues: list[SubtitleCue], config: dict) -> list[SubtitleCue]:
    """Normalize, deduplicate and repair timings for source-language subtitles."""
    cleaned: list[SubtitleCue] = []
    duplicate_gap = max(0.0, float(config.get("duplicate_gap", 0.35)))
    for cue in cues:
        text = normalize_japanese(cue.ja)
        if not text:
            continue
        if (
            cleaned
            and cleaned[-1].ja == text
            and cue.start <= cleaned[-1].end + duplicate_gap
        ):
            cleaned[-1].end = max(cleaned[-1].end, cue.end)
            cleaned[-1].words.extend(copy.deepcopy(cue.words))
            continue
        cloned = copy.deepcopy(cue)
        cloned.ja = text
        cleaned.append(cloned)

    for index, cue in enumerate(cleaned, start=1):
        cue.id = index
    return optimize_timings(cleaned, config)


def wrap_japanese_cues(cues: list[SubtitleCue], config: dict) -> list[SubtitleCue]:
    """Create display copies with at most two balanced Japanese subtitle lines."""
    width = max(4, int(config.get("max_chars_per_line", 20)))
    max_lines = max(1, int(config.get("max_lines", 2)))
    result = [copy.deepcopy(cue) for cue in cues]
    for cue in result:
        text = normalize_japanese(cue.ja)
        if visible_length(text) <= width:
            cue.ja = text
            continue
        if visible_length(text) <= width * max_lines:
            preferred = len(text) // 2
            candidates = [
                index + 1
                for index, char in enumerate(text[:-1])
                if char in "、。！？…"
            ]
            split_at = min(candidates, key=lambda value: abs(value - preferred)) if candidates else preferred
            cue.ja = text[:split_at].strip() + "\n" + text[split_at:].strip()
            continue
        # ASR normally splits before this point; retain all text if a custom
        # configuration produces a longer cue rather than silently truncating it.
        lines = [text[index : index + width] for index in range(0, len(text), width)]
        cue.ja = "\n".join(lines)
    return result


def srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def write_srt(cues: Iterable[SubtitleCue], path: Path, field: str = "zh") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        text = str(getattr(cue, field) or cue.ja).replace("-->", "→").strip()
        blocks.append(
            f"{index}\n{srt_timestamp(cue.start)} --> {srt_timestamp(cue.end)}\n{text}"
        )
    path.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")
    return path


def _ass_escape(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def write_ass(
    cues: Iterable[SubtitleCue],
    path: Path,
    config: dict,
    field: str = "zh",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = f"""[Script Info]
; Generated by ja2zh-subtitle
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{config.get('font_name', 'Noto Sans CJK SC')},{config.get('font_size', 48)},{config.get('primary_colour', '&H00FFFFFF')},&H000000FF,{config.get('outline_colour', '&H00000000')},&H64000000,0,0,0,0,100,100,0,0,1,{config.get('outline', 2.2)},{config.get('shadow', 0.8)},2,60,60,{config.get('margin_v', 48)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cue in cues:
        text = str(getattr(cue, field, "") or cue.zh or cue.raw_zh or cue.ja)
        events.append(
            "Dialogue: 0,"
            f"{ass_timestamp(cue.start)},{ass_timestamp(cue.end)},"
            f"Default,,0,0,0,,{_ass_escape(text)}"
        )
    path.write_text(header + "\n".join(events) + ("\n" if events else ""), encoding="utf-8-sig")
    return path
