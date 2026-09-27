from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .models import SubtitleCue


LOGGER = logging.getLogger(__name__)


class NLLBTranslator:
    def __init__(
        self,
        config: dict[str, Any],
        device: str,
        model_root: Path,
        offline: bool,
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "缺少 NLLB 运行依赖，请运行 pip install -r requirements.txt"
            ) from exc

        self.torch = torch
        self.config = config
        self.device = device
        model_root.mkdir(parents=True, exist_ok=True)
        model_name = str(config["model"])
        LOGGER.info("加载翻译模型：%s (%s)", model_name, device)
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            src_lang=str(config.get("source_language", "jpn_Jpan")),
            cache_dir=str(model_root),
            local_files_only=offline,
        )
        dtype = self._dtype(str(config.get("dtype", "auto")))
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_name,
            cache_dir=str(model_root),
            local_files_only=offline,
            torch_dtype=dtype,
        ).to(device)
        self.model.eval()

    def _dtype(self, name: str) -> Any:
        if name == "float16" or name == "auto" and self.device == "cuda":
            return self.torch.float16
        if name == "bfloat16":
            return self.torch.bfloat16
        return self.torch.float32

    def translate(self, cues: list[SubtitleCue]) -> list[SubtitleCue]:
        batch_size = max(1, int(self.config.get("batch_size", 8)))
        target = str(self.config.get("target_language", "zho_Hans"))
        forced_bos = self.tokenizer.convert_tokens_to_ids(target)
        if forced_bos is None or forced_bos == self.tokenizer.unk_token_id:
            raise RuntimeError(f"NLLB 不支持目标语言代码：{target}")

        for offset in range(0, len(cues), batch_size):
            batch = cues[offset : offset + batch_size]
            texts = [cue.ja for cue in batch]
            inputs = self.tokenizer(
                texts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=int(self.config.get("max_input_tokens", 256)),
            )
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            with self.torch.inference_mode():
                generated = self.model.generate(
                    **inputs,
                    forced_bos_token_id=forced_bos,
                    num_beams=int(self.config.get("num_beams", 4)),
                    max_new_tokens=int(self.config.get("max_new_tokens", 256)),
                )
            translations = self.tokenizer.batch_decode(generated, skip_special_tokens=True)
            for cue, translation in zip(batch, translations, strict=True):
                cue.raw_zh = translation.strip()
        return cues

    def close(self) -> None:
        self.model = None
        self.tokenizer = None


class MockTranslator:
    TRANSLATIONS = {
        "みなさん、こんにちは。": "大家好。",
        "今日は一緒に字幕生成を試してみましょう。": "今天，让我们一起尝试生成字幕。",
        "じゃ、先に行ってますね。": "那么，我先去了。",
        "ご視聴ありがとうございました。": "感谢您的观看。",
    }

    def translate(self, cues: list[SubtitleCue]) -> list[SubtitleCue]:
        for cue in cues:
            cue.raw_zh = self.TRANSLATIONS.get(cue.ja, f"测试译文：{cue.ja}")
        return cues

    def close(self) -> None:
        return None


def create_translator(
    config: dict[str, Any], device: str, model_root: Path, offline: bool, mock: bool
) -> NLLBTranslator | MockTranslator:
    if mock:
        return MockTranslator()
    return NLLBTranslator(config, device, model_root, offline)

