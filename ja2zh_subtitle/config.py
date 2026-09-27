from __future__ import annotations

import copy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "runtime": {
        "device": "auto",
        "offline": False,
        "mock": False,
        "resume": True,
        "keep_audio": False,
        "output_dir": "output",
        "cache_dir": None,
        "model_root": "models",
        "audio_stream": 0,
    },
    "asr": {
        "model": "medium",
        "compute_type": "auto",
        "beam_size": 5,
        "batch_size": 1,
        "vad_filter": True,
        "vad_parameters": {
            "threshold": 0.3,
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 500,
        },
        "gap_recovery": {
            "enabled": True,
            "min_gap_seconds": 1.5,
            "padding_seconds": 0.2,
            "min_text_chars": 2,
            "min_confidence": 0.55,
            "low_word_probability": 0.3,
            "max_low_probability_ratio": 0.35,
        },
        "condition_on_previous_text": True,
        "initial_prompt": "",
        "hotwords": "",
        "max_segment_chars": 70,
        "max_segment_duration": 14.0,
        "max_segment_overrun_chars": 12,
        "max_segment_overrun_duration": 2.0,
        "pause_split_seconds": 0.55,
    },
    "translation": {
        "enabled": True,
        "backend": "deepseek",
        "prompt_file": "prompts/subtitle_translate_polish.txt",
    },
    "polish": {
        "enabled": True,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "api_timeout_seconds": 180,
        "api_retries": 5,
        "prompt_file": "prompts/subtitle_polish.txt",
        "batch_size": 12,
        "context_before": 6,
        "context_after": 6,
        "max_new_tokens": 4096,
        "temperature": 0.0,
        "top_p": 0.8,
        "retries": 2,
        "thinking": "disabled",
    },
    "subtitle": {
        "max_chars_per_line": 18,
        "max_lines": 2,
        "min_duration": 0.8,
        "max_duration": 7.0,
        "minimum_gap": 0.06,
        "font_name": "Noto Sans CJK SC",
        "font_size": 48,
        "primary_colour": "&H00FFFFFF",
        "outline_colour": "&H00000000",
        "outline": 2.2,
        "shadow": 0.8,
        "margin_v": 48,
    },
    "japanese_subtitle": {
        "max_chars_per_line": 20,
        "max_lines": 2,
        "min_duration": 0.55,
        "max_duration": 7.0,
        "minimum_gap": 0.06,
        "duplicate_gap": 0.35,
        "font_name": "Noto Sans CJK JP",
        "font_size": 54,
        "primary_colour": "&H00FFFFFF",
        "outline_colour": "&H00000000",
        "outline": 2.4,
        "shadow": 0.6,
        "margin_v": 48,
    },
    "quality_control": {
        "mode": "warn",
        "report_gap_seconds": 8.0,
        "min_confidence": 0.55,
        "min_duration": 0.35,
        "max_japanese_chars_per_second": 13.0,
        "max_chinese_chars_per_second": 11.0,
    },
    "video": {
        "codec": "h264",
        "crf": 18,
        "preset": "medium",
        "audio_copy": True,
        "audio_fallback_codec": "aac",
        "audio_bitrate": "192k",
        "fonts_dir": "assets/fonts",
    },
    "presets": {
        "lite": {
            "asr": {"model": "small", "compute_type": "int8", "beam_size": 3},
        },
        "balanced": {
            "asr": {"model": "medium", "compute_type": "auto", "beam_size": 5},
        },
        "quality": {
            "asr": {"model": "large-v3", "compute_type": "auto", "beam_size": 5},
        },
    },
}


def deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(path: Path | None, preset: str) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    if path is not None:
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在：{path}")
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("缺少 PyYAML，请先运行 pip install -r requirements.txt") from exc
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config.yaml 顶层必须是映射结构")
        config = deep_merge(config, loaded)

    presets = config.get("presets", {})
    if preset not in presets:
        choices = ", ".join(sorted(presets))
        raise ValueError(f"未知预设 {preset!r}，可选值：{choices}")
    config = deep_merge(config, presets[preset])
    config["selected_preset"] = preset
    return config
