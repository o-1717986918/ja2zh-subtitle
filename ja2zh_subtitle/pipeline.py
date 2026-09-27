from __future__ import annotations

import copy
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .asr import create_asr
from .cache import StageCache, file_fingerprint, stable_hash
from .device import detect_device, release_accelerator_memory
from .media import audio_streams, burn_subtitles, extract_audio, media_duration, probe_media
from .models import SubtitleCue
from .polisher import POLISH_CACHE_VERSION, create_polisher
from .quality import timeline_problems, write_review_report
from .subtitle import (
    prepare_final_cues,
    prepare_japanese_cues,
    wrap_japanese_cues,
    write_ass,
    write_srt,
)


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineResult:
    raw_japanese_srt: Path
    japanese_srt: Path
    japanese_ass: Path
    review_report: Path
    raw_chinese_srt: Path | None
    chinese_srt: Path | None
    chinese_ass: Path | None
    video: Path | None
    cache_dir: Path


class SubtitlePipeline:
    def __init__(self, config: dict[str, Any], project_root: Path) -> None:
        self.config = config
        self.project_root = project_root
        runtime = config["runtime"]
        self.mock = bool(runtime.get("mock", False))
        self.offline = bool(runtime.get("offline", False))
        if self.offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        self.profile = detect_device(str(runtime.get("device", "auto")))
        self.device = self.profile.device

    def _resolve_project_path(self, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.project_root / path

    def _video_config(self) -> dict[str, Any]:
        config = copy.deepcopy(self.config["video"])
        fonts_dir = str(config.get("fonts_dir", "")).strip()
        if fonts_dir:
            config["fonts_dir"] = str(self._resolve_project_path(fonts_dir))
        return config

    def burn_existing_subtitle(
        self,
        input_video: Path,
        subtitle: Path,
        output_dir: Path | None = None,
        language: str = "auto",
    ) -> Path:
        input_video = input_video.resolve()
        subtitle = subtitle.resolve()
        if not input_video.is_file():
            raise FileNotFoundError(f"输入视频不存在：{input_video}")
        if not subtitle.is_file():
            raise FileNotFoundError(f"字幕文件不存在：{subtitle}")
        if subtitle.suffix.lower() not in {".srt", ".ass"}:
            raise ValueError("只支持 SRT 或 ASS 字幕文件")
        if language == "auto":
            language = "ja" if "_ja" in subtitle.stem.lower() else "zh"
        style = (
            self.config["japanese_subtitle"]
            if language == "ja"
            else self.config["subtitle"]
        )
        target_dir = output_dir or Path(str(self.config["runtime"].get("output_dir", "output")))
        if not target_dir.is_absolute():
            target_dir = Path.cwd() / target_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        prefix = subtitle.stem if subtitle.stem.startswith(input_video.stem) else f"{input_video.stem}_{subtitle.stem}"
        output = target_dir / f"{prefix}_sub.mp4"
        return burn_subtitles(
            input_video,
            subtitle,
            output,
            self._video_config(),
            style=style,
        )

    def run(
        self,
        input_video: Path,
        subtitle_only: bool = False,
        japanese_only: bool = False,
        no_polish: bool = False,
        force: bool = False,
    ) -> PipelineResult:
        input_video = input_video.resolve()
        if not input_video.is_file():
            raise FileNotFoundError(f"输入视频不存在：{input_video}")

        runtime = self.config["runtime"]
        output_dir = Path(str(runtime.get("output_dir", "output")))
        if not output_dir.is_absolute():
            output_dir = Path.cwd() / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = input_video.stem
        source_key = stable_hash(file_fingerprint(input_video))[:10]
        configured_cache = runtime.get("cache_dir")
        cache_dir = (
            Path(str(configured_cache))
            if configured_cache
            else output_dir / ".cache" / f"{stem}-{source_key}"
        )
        if not cache_dir.is_absolute():
            cache_dir = Path.cwd() / cache_dir
        cache = StageCache(
            cache_dir,
            enabled=bool(runtime.get("resume", True)) and not force,
        )

        probe = probe_media(input_video)
        streams = audio_streams(probe)
        if not streams:
            raise RuntimeError("输入文件没有音轨")
        audio_index = int(runtime.get("audio_stream", 0))
        if audio_index < 0 or audio_index >= len(streams):
            raise ValueError(f"音轨索引 {audio_index} 无效；文件共有 {len(streams)} 条音轨")
        duration = media_duration(probe)
        audio_path = cache_dir / "audio_16k_mono.wav"
        if force or not audio_path.exists():
            LOGGER.info("[1/6] 提取 16kHz 单声道音频")
            extract_audio(input_video, audio_path, audio_index)
        else:
            LOGGER.info("[1/6] 使用缓存音频")

        model_root = self._resolve_project_path(runtime.get("model_root", "models"))
        source_fp = file_fingerprint(input_video)

        asr_signature = stable_hash({"source": source_fp, "asr": self.config["asr"]})
        cues = cache.load("asr", asr_signature)
        if cues is None:
            LOGGER.info("[2/6] 日语语音识别")
            asr = create_asr(
                self.config["asr"],
                self.device,
                model_root / "whisper",
                self.offline,
                self.mock,
            )
            try:
                cues = asr.transcribe(audio_path, duration)
            finally:
                asr.close()
                release_accelerator_memory()
            if not cues:
                raise RuntimeError("没有识别到日语语音")
            cache.save("asr", asr_signature, cues)
        else:
            LOGGER.info("[2/6] 使用缓存识别结果")

        raw_japanese_srt = output_dir / f"{stem}_raw_ja.srt"
        write_srt(cues, raw_japanese_srt, "ja")

        japanese_config = self.config["japanese_subtitle"]
        japanese_cues = prepare_japanese_cues(cues, japanese_config)
        japanese_srt = output_dir / f"{stem}_ja.srt"
        japanese_ass = output_dir / f"{stem}_ja.ass"
        write_srt(japanese_cues, japanese_srt, "ja")
        write_ass(
            wrap_japanese_cues(japanese_cues, japanese_config),
            japanese_ass,
            japanese_config,
            field="ja",
        )
        review_report = write_review_report(
            japanese_cues,
            output_dir / f"{stem}_review.txt",
            self.config["quality_control"],
            duration=duration,
        )

        japanese_only = japanese_only or not bool(
            self.config["translation"].get("enabled", True)
        )
        if japanese_only:
            LOGGER.info("[3/6] 已跳过翻译和润色")
            output_video: Path | None = None
            if subtitle_only:
                LOGGER.info("[4/4] 已按要求跳过视频烧录")
            else:
                LOGGER.info("[4/4] 烧录日语字幕")
                output_video = output_dir / f"{stem}_ja_sub.mp4"
                burn_subtitles(
                    input_video,
                    japanese_ass,
                    output_video,
                    self._video_config(),
                )
            return PipelineResult(
                raw_japanese_srt=raw_japanese_srt,
                japanese_srt=japanese_srt,
                japanese_ass=japanese_ass,
                review_report=review_report,
                raw_chinese_srt=None,
                chinese_srt=None,
                chinese_ass=None,
                video=output_video,
                cache_dir=cache_dir,
            )

        translation_backend = str(
            self.config["translation"].get("backend", "deepseek")
        ).lower()
        if translation_backend != "deepseek":
            raise ValueError(
                f"当前版本只支持 DeepSeek 在线翻译，实际配置为：{translation_backend}"
            )
        LOGGER.info("[3/6] 使用 DeepSeek API 统一执行忠实翻译与润色")
        translated = copy.deepcopy(japanese_cues)

        polish_enabled = bool(self.config["polish"].get("enabled", True)) and not no_polish
        prompt_path = self._resolve_project_path(
            self.config["translation"].get(
                "prompt_file", "prompts/subtitle_translate_polish.txt"
            )
        )
        polisher_config = copy.deepcopy(self.config["polish"])
        polisher_config["provider"] = "deepseek"
        polisher_config["generate_literal"] = True
        polish_signature = stable_hash(
            {
                "translated": [cue.to_dict() for cue in translated],
                "polish": polisher_config,
                "translation_backend": translation_backend,
                "enabled": polish_enabled,
                "cache_version": POLISH_CACHE_VERSION,
                "prompt": (
                    prompt_path.read_text(encoding="utf-8")
                ),
            }
        )
        polished = cache.load("polished", polish_signature)
        if polished is None:
            LOGGER.info(
                "[4/6] %s",
                "上下文忠实翻译与润色" if polish_enabled else "上下文忠实直译",
            )
            polisher = create_polisher(
                polisher_config,
                self.device,
                model_root / "api",
                self.offline,
                prompt_path,
                self.mock,
            )
            try:
                polished = polisher.polish(translated)
            finally:
                polisher.close()
                release_accelerator_memory()
            if not polish_enabled:
                for cue in polished:
                    cue.zh = cue.raw_zh
            cache.save("polished", polish_signature, polished)
        else:
            LOGGER.info("[4/6] 使用缓存润色结果")

        raw_chinese_srt = output_dir / f"{stem}_raw_zh.srt"
        write_srt(polished, raw_chinese_srt, "raw_zh")

        LOGGER.info("[5/6] 字幕断句、排版与时间轴优化")
        final_cues = prepare_final_cues(polished, self.config["subtitle"])
        invalid_timeline = timeline_problems(final_cues)
        if invalid_timeline:
            raise RuntimeError("中文字幕时间轴无效：" + "；".join(invalid_timeline))
        chinese_srt = output_dir / f"{stem}_zh.srt"
        chinese_ass = output_dir / f"{stem}_zh.ass"
        write_srt(final_cues, chinese_srt, "zh")
        write_ass(final_cues, chinese_ass, self.config["subtitle"])
        write_review_report(
            japanese_cues,
            review_report,
            self.config["quality_control"],
            duration=duration,
            chinese_cues=final_cues,
        )

        output_video: Path | None = None
        if subtitle_only:
            LOGGER.info("[6/6] 已按要求跳过视频烧录")
        else:
            LOGGER.info("[6/6] 烧录中文字幕")
            output_video = output_dir / f"{stem}_zh_sub.mp4"
            burn_subtitles(input_video, chinese_ass, output_video, self._video_config())

        return PipelineResult(
            raw_japanese_srt=raw_japanese_srt,
            japanese_srt=japanese_srt,
            japanese_ass=japanese_ass,
            review_report=review_report,
            raw_chinese_srt=raw_chinese_srt,
            chinese_srt=chinese_srt,
            chinese_ass=chinese_ass,
            video=output_video,
            cache_dir=cache_dir,
        )
