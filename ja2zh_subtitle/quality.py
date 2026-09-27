from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import SubtitleCue


@dataclass(slots=True)
class ReviewIssue:
    cue_id: int
    start: float
    end: float
    text: str
    reasons: list[str]


def timeline_problems(cues: list[SubtitleCue]) -> list[str]:
    problems: list[str] = []
    previous_end = -1.0
    for cue in cues:
        if cue.start < 0 or cue.end <= cue.start:
            problems.append(f"字幕 {cue.id} 时间范围无效")
        if cue.start < previous_end:
            problems.append(f"字幕 {cue.id} 与前一条时间重叠或倒序")
        previous_end = max(previous_end, cue.end)
    return problems


def long_timeline_gaps(
    cues: list[SubtitleCue], duration: float, threshold: float
) -> list[tuple[float, float]]:
    gaps: list[tuple[float, float]] = []
    cursor = 0.0
    for cue in cues:
        if cue.start - cursor >= threshold:
            gaps.append((cursor, cue.start))
        cursor = max(cursor, cue.end)
    if duration > 0 and duration - cursor >= threshold:
        gaps.append((cursor, duration))
    return gaps


def _clock(seconds: float) -> str:
    total = max(0, round(seconds * 1000))
    minutes, remainder = divmod(total, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def inspect_cues(
    cues: list[SubtitleCue],
    language: str,
    config: dict[str, Any],
) -> list[ReviewIssue]:
    min_confidence = float(config.get("min_confidence", 0.55))
    min_duration = float(config.get("min_duration", 0.35))
    max_cps = float(
        config.get("max_japanese_chars_per_second", 13.0)
        if language == "ja"
        else config.get("max_chinese_chars_per_second", 11.0)
    )
    issues: list[ReviewIssue] = []
    for cue in cues:
        text = cue.ja if language == "ja" else cue.zh or cue.raw_zh
        compact = "".join(text.split())
        duration = max(0.001, cue.end - cue.start)
        reasons: list[str] = []
        if cue.confidence is not None and cue.confidence < min_confidence:
            reasons.append(f"识别置信度偏低（{cue.confidence:.2f}）")
        if duration < min_duration:
            reasons.append(f"显示时间过短（{duration:.2f}s）")
        if len(compact.rstrip("、。！？…")) <= 1:
            reasons.append("疑似孤立单字/语气词")
        cps = len(compact) / duration
        if cps > max_cps:
            reasons.append(f"阅读速度过快（{cps:.1f} 字/秒）")
        if reasons:
            issues.append(
                ReviewIssue(cue.id, cue.start, cue.end, text.replace("\n", " "), reasons)
            )
    return issues


def write_review_report(
    cues: list[SubtitleCue],
    path: Path,
    config: dict[str, Any],
    duration: float = 0.0,
    chinese_cues: list[SubtitleCue] | None = None,
) -> Path:
    mode = str(config.get("mode", "warn")).lower()
    if mode not in {"off", "warn", "strict"}:
        mode = "warn"
    issues = [] if mode == "off" else inspect_cues(cues, "ja", config)
    recovered = sum(cue.origin in {"gap_recovery", "merged"} for cue in cues)
    gap_threshold = max(1.0, float(config.get("report_gap_seconds", 8.0)))
    gaps = [] if mode == "off" else long_timeline_gaps(cues, duration, gap_threshold)
    timeline_errors = timeline_problems(cues)
    lines = [
        "ja2zh-subtitle 字幕质量检查报告",
        "=" * 36,
        f"质量模式：{mode}",
        f"字幕总数：{len(cues)}",
        f"补识别恢复：{recovered}",
        f"建议复核：{len(issues)}",
        "说明：warn 模式只标记风险并继续输出，不会阻止烧录。",
        "",
    ]
    if mode == "off":
        lines.append("非技术性质量检查已关闭。")
    elif not issues:
        lines.append("未发现达到当前阈值的风险项。")
    else:
        for issue in issues:
            reason = "；".join(issue.reasons)
            lines.extend(
                [
                    f"#{issue.cue_id}  {_clock(issue.start)} --> {_clock(issue.end)}",
                    f"原因：{reason}",
                    f"文本：{issue.text}",
                    "",
                ]
            )
    if gaps:
        lines.extend(["", "较长无字幕区间（可能是静音，也可能需要复核）："])
        for start, end in gaps:
            lines.append(f"- {_clock(start)} --> {_clock(end)}（{end - start:.2f}s）")
    if chinese_cues is not None and mode != "off":
        chinese_issues = inspect_cues(chinese_cues, "zh", config)
        lines.extend(
            [
                "",
                f"中文字幕条数：{len(chinese_cues)}",
                f"中文字幕阅读风险：{len(chinese_issues)}",
            ]
        )
        for issue in chinese_issues:
            lines.append(
                f"- #{issue.cue_id} {_clock(issue.start)}-{_clock(issue.end)}："
                + "；".join(issue.reasons)
            )
    if timeline_errors:
        lines.extend(["", "技术性时间轴错误：", *[f"- {item}" for item in timeline_errors]])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path
