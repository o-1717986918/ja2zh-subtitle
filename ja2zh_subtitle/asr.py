from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Iterable

from .device import prepare_windows_dll_directories, resolve_compute_type
from .models import SubtitleCue, WordTiming


LOGGER = logging.getLogger(__name__)
BREAK_PUNCTUATION = set("。！？!?…")
INCOMPLETE_ENDINGS = (
    "と思",
    "と言",
    "って",
    "ので",
    "のに",
    "けど",
    "ながら",
    "ため",
    "よう",
    "こと",
)


def _word_text(word: Any) -> str:
    return str(getattr(word, "word", getattr(word, "text", "")))


def _word_probability(word: Any) -> float | None:
    value = getattr(word, "probability", None)
    return float(value) if value is not None else None


def _make_cue(
    cue_id: int, words: list[WordTiming], origin: str = "primary"
) -> SubtitleCue:
    text = "".join(word.text for word in words).strip()
    probabilities = [word.probability for word in words if word.probability is not None]
    confidence = sum(probabilities) / len(probabilities) if probabilities else None
    return SubtitleCue(
        id=cue_id,
        start=max(0.0, words[0].start),
        end=max(words[0].start + 0.05, words[-1].end),
        ja=text,
        confidence=confidence,
        words=words,
        origin=origin,
    )


def _looks_incomplete(text: str) -> bool:
    value = text.rstrip()
    return any(value.endswith(suffix) for suffix in INCOMPLETE_ENDINGS)


def _recalculate_confidence(cue: SubtitleCue) -> None:
    probabilities = [
        word.probability for word in cue.words if word.probability is not None
    ]
    if probabilities:
        cue.confidence = sum(probabilities) / len(probabilities)


def merge_short_fragments(
    cues: list[SubtitleCue], max_chars: int = 2, max_gap: float = 0.3
) -> list[SubtitleCue]:
    """Join ASR fragments such as ``と思`` + ``う`` before translation."""
    merged: list[SubtitleCue] = []
    for cue in sorted(cues, key=lambda item: (item.start, item.end)):
        text = cue.ja.strip()
        if (
            merged
            and len(text.rstrip("、。！？!?…")) <= max_chars
            and cue.start - merged[-1].end <= max_gap
        ):
            previous = merged[-1]
            previous.ja = (previous.ja + text).strip()
            previous.end = max(previous.end, cue.end)
            previous.words.extend(cue.words)
            if previous.origin != cue.origin:
                previous.origin = "merged"
            _recalculate_confidence(previous)
            continue
        merged.append(cue)
    for index, cue in enumerate(merged, start=1):
        cue.id = index
    return merged


def uncovered_intervals(
    cues: list[SubtitleCue], duration: float, min_gap: float
) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    cursor = 0.0
    for cue in sorted(cues, key=lambda item: (item.start, item.end)):
        if cue.start - cursor >= min_gap:
            intervals.append((cursor, cue.start))
        cursor = max(cursor, cue.end)
    if duration - cursor >= min_gap:
        intervals.append((cursor, duration))
    return intervals


def _normalized_text(text: str) -> str:
    return "".join(char for char in text if char not in " \t\r\n、。！？!?…")


def _overlap_ratio(first: SubtitleCue, second: SubtitleCue) -> float:
    overlap = max(0.0, min(first.end, second.end) - max(first.start, second.start))
    shorter = max(0.05, min(first.end - first.start, second.end - second.start))
    return overlap / shorter


def merge_recovered_cues(
    primary: list[SubtitleCue], recovered: list[SubtitleCue]
) -> list[SubtitleCue]:
    result = list(primary)
    for candidate in recovered:
        # A no-VAD clip can continue a few frames into the next primary cue.
        # Keep only the genuinely missing lead-in, then attach it to that cue.
        following = next(
            (
                cue
                for cue in sorted(result, key=lambda item: item.start)
                if candidate.start < cue.start < candidate.end
            ),
            None,
        )
        trimmed_lead = False
        if following is not None and candidate.words:
            lead_words = [word for word in candidate.words if word.end <= following.start]
            if lead_words and len(lead_words) < len(candidate.words):
                candidate.words = lead_words
                candidate.ja = "".join(word.text for word in lead_words).strip()
                candidate.end = lead_words[-1].end
                _recalculate_confidence(candidate)
                trimmed_lead = True

        candidate_text = _normalized_text(candidate.ja)
        duplicate = False
        for existing in result:
            existing_text = _normalized_text(existing.ja)
            if not candidate_text or not existing_text:
                continue
            if _overlap_ratio(candidate, existing) >= 0.55 and (
                candidate_text in existing_text or existing_text in candidate_text
            ):
                duplicate = True
                break
            near_next = 0.0 <= existing.start - candidate.end <= 2.0
            if near_next and len(candidate_text) <= 8 and existing_text.startswith(
                candidate_text
            ):
                duplicate = True
                break
        if not duplicate:
            if (
                trimmed_lead
                and following is not None
                and 0.0 <= following.start - candidate.end <= 0.35
                and (
                    len(candidate_text) <= 4
                    or candidate.ja.rstrip().endswith(
                        ("、", "が", "は", "を", "に", "で", "と", "も", "の", "て")
                    )
                )
            ):
                following.ja = candidate.ja + following.ja
                following.start = candidate.start
                following.words = candidate.words + following.words
                following.origin = "merged"
                _recalculate_confidence(following)
                continue
            result.append(candidate)
    return merge_short_fragments(result)


def segments_to_cues(
    segments: Iterable[Any],
    config: dict[str, Any],
    origin: str = "primary",
) -> list[SubtitleCue]:
    max_chars = int(config.get("max_segment_chars", 34))
    max_duration = float(config.get("max_segment_duration", 7.0))
    max_overrun_chars = max(0, int(config.get("max_segment_overrun_chars", 8)))
    max_overrun_duration = max(
        0.0, float(config.get("max_segment_overrun_duration", 1.5))
    )
    pause_split = float(config.get("pause_split_seconds", 0.75))
    cues: list[SubtitleCue] = []
    current: list[WordTiming] = []

    def flush() -> None:
        nonlocal current
        if current:
            cues.append(_make_cue(len(cues) + 1, current, origin))
            current = []

    for segment in segments:
        raw_words = list(getattr(segment, "words", None) or [])
        if not raw_words:
            flush()
            text = str(getattr(segment, "text", "")).strip()
            if text:
                cues.append(
                    SubtitleCue(
                        id=len(cues) + 1,
                        start=max(0.0, float(segment.start)),
                        end=max(float(segment.start) + 0.05, float(segment.end)),
                        ja=text,
                        origin=origin,
                    )
                )
            continue

        for raw_word in raw_words:
            text = _word_text(raw_word)
            if not text:
                continue
            word = WordTiming(
                start=float(raw_word.start),
                end=float(raw_word.end),
                text=text,
                probability=_word_probability(raw_word),
            )
            if current and word.start - current[-1].end >= pause_split:
                flush()
            current.append(word)
            joined = "".join(item.text for item in current).strip()
            duration = current[-1].end - current[0].start
            punctuation_break = bool(joined) and joined[-1] in BREAK_PUNCTUATION
            size_break = len(joined) >= max_chars or duration >= max_duration
            may_wait_for_completion = (
                size_break
                and _looks_incomplete(joined)
                and len(joined) < max_chars + max_overrun_chars
                and duration < max_duration + max_overrun_duration
            )
            if (punctuation_break and len(joined) >= 6) or (
                size_break and not may_wait_for_completion
            ):
                flush()

    flush()

    return merge_short_fragments([cue for cue in cues if cue.ja.strip()])


class FasterWhisperASR:
    def __init__(
        self,
        config: dict[str, Any],
        device: str,
        model_root: Path,
        offline: bool,
    ) -> None:
        prepare_windows_dll_directories()
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "缺少 faster-whisper，请运行 pip install -r requirements.txt"
            ) from exc
        self.config = config
        self.device = device
        model_root.mkdir(parents=True, exist_ok=True)
        compute_type = resolve_compute_type(str(config.get("compute_type", "auto")), device)
        LOGGER.info("加载 Whisper：%s (%s/%s)", config["model"], device, compute_type)
        model_name = str(config["model"])
        local_candidates = [
            model_root / model_name,
            model_root / f"faster-whisper-{model_name}",
        ]
        cache_root = model_root / f"models--Systran--faster-whisper-{model_name}" / "snapshots"
        if cache_root.is_dir():
            local_candidates.extend(sorted(cache_root.iterdir(), reverse=True))
        local_model = next(
            (
                candidate
                for candidate in local_candidates
                if candidate.is_dir()
                and (candidate / "model.bin").is_file()
                and (candidate / "config.json").is_file()
            ),
            None,
        )
        self.model = WhisperModel(
            str(local_model or model_name),
            device=device,
            compute_type=compute_type,
            download_root=str(model_root),
            local_files_only=offline or local_model is not None,
        )

    def _transcribe_pass(
        self,
        audio: Path,
        *,
        vad_filter: bool,
        origin: str,
        clip_timestamps: list[float] | None = None,
    ) -> list[SubtitleCue]:
        kwargs: dict[str, Any] = {
            "language": "ja",
            "beam_size": int(self.config.get("beam_size", 5)),
            "vad_filter": vad_filter,
            "word_timestamps": True,
            "condition_on_previous_text": bool(
                self.config.get("condition_on_previous_text", True)
            ),
        }
        if vad_filter:
            kwargs["vad_parameters"] = dict(self.config.get("vad_parameters", {}))
        if clip_timestamps:
            kwargs["clip_timestamps"] = clip_timestamps
            kwargs["condition_on_previous_text"] = False
        if self.config.get("initial_prompt"):
            kwargs["initial_prompt"] = str(self.config["initial_prompt"])
        if self.config.get("hotwords"):
            kwargs["hotwords"] = str(self.config["hotwords"])
        segments, _ = self.model.transcribe(str(audio), **kwargs)
        return segments_to_cues(segments, self.config, origin=origin)

    def transcribe(self, audio: Path, duration: float = 0.0) -> list[SubtitleCue]:
        use_vad = bool(self.config.get("vad_filter", True))
        primary = self._transcribe_pass(
            audio,
            vad_filter=use_vad,
            origin="primary",
        )
        recovery = dict(self.config.get("gap_recovery", {}))
        if not use_vad or not bool(recovery.get("enabled", True)) or duration <= 0:
            return primary

        min_gap = max(0.5, float(recovery.get("min_gap_seconds", 1.5)))
        padding = max(0.0, float(recovery.get("padding_seconds", 0.2)))
        gaps = uncovered_intervals(primary, duration, min_gap)
        if not gaps:
            return primary

        clips: list[float] = []
        for start, end in gaps:
            clips.extend([max(0.0, start - padding), min(duration, end + padding)])
        LOGGER.info(
            "检测到 %s 个字幕空白区，执行无 VAD 补识别（共 %.1f 秒）",
            len(gaps),
            sum(end - start for start, end in gaps),
        )
        candidates = self._transcribe_pass(
            audio,
            vad_filter=False,
            origin="gap_recovery",
            clip_timestamps=clips,
        )

        min_chars = max(1, int(recovery.get("min_text_chars", 1)))
        min_confidence = float(recovery.get("min_confidence", 0.25))
        low_probability = float(recovery.get("low_word_probability", 0.3))
        max_low_ratio = float(recovery.get("max_low_probability_ratio", 0.35))
        recovered: list[SubtitleCue] = []
        for cue in candidates:
            midpoint = (cue.start + cue.end) / 2
            inside_gap = any(start <= midpoint <= end for start, end in gaps)
            visible = _normalized_text(cue.ja)
            confidence_ok = cue.confidence is None or cue.confidence >= min_confidence
            probabilities = [
                word.probability
                for word in cue.words
                if word.probability is not None
            ]
            low_ratio = (
                sum(value < low_probability for value in probabilities)
                / len(probabilities)
                if probabilities
                else 0.0
            )
            if (
                inside_gap
                and len(visible) >= min_chars
                and confidence_ok
                and low_ratio <= max_low_ratio
            ):
                recovered.append(cue)
        LOGGER.info("无 VAD 补识别恢复 %s 条候选对白", len(recovered))
        return merge_recovered_cues(primary, recovered)

    def close(self) -> None:
        self.model = None


class MockASR:
    """Deterministic backend used by tests and installation diagnostics."""

    SAMPLE = [
        "みなさん、こんにちは。",
        "今日は一緒に字幕生成を試してみましょう。",
        "じゃ、先に行ってますね。",
        "ご視聴ありがとうございました。",
    ]

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def transcribe(self, audio: Path, duration: float = 0.0) -> list[SubtitleCue]:
        usable_duration = max(2.0, duration)
        count = min(len(self.SAMPLE), max(1, math.ceil(usable_duration / 1.5)))
        step = usable_duration / count
        cues: list[SubtitleCue] = []
        for index, text in enumerate(self.SAMPLE[:count], start=1):
            start = (index - 1) * step
            end = min(usable_duration, index * step - 0.08)
            cues.append(SubtitleCue(index, start, max(start + 0.4, end), text, confidence=1.0))
        return cues

    def close(self) -> None:
        return None


def create_asr(
    config: dict[str, Any], device: str, model_root: Path, offline: bool, mock: bool
) -> FasterWhisperASR | MockASR:
    if mock:
        return MockASR(config)
    return FasterWhisperASR(config, device, model_root, offline)
