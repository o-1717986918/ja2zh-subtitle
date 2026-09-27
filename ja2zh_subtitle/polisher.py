from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from .models import SubtitleCue


LOGGER = logging.getLogger(__name__)

POLISH_CACHE_VERSION = 5
KANA_RE = re.compile(r"[\u3040-\u30ff\uff65-\uff9f]")
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
REPEATED_PUNCTUATION_RE = re.compile(r"([,，。.!！?？、;；:：])\1{2,}")


class PolishFormatError(ValueError):
    pass


def extract_json_array(text: str) -> list[dict[str, Any]]:
    cleaned = re.sub(r"^\s*```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    start = cleaned.find("[")
    if start < 0:
        raise PolishFormatError("模型输出中没有 JSON 数组")
    try:
        value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        raise PolishFormatError(f"无法解析模型 JSON：{exc}") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise PolishFormatError("模型输出必须是对象数组")
    return value


def validate_polish_result(
    value: list[dict[str, Any]], expected_ids: list[int]
) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in value:
        try:
            cue_id = int(item["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PolishFormatError("润色结果缺少有效 id") from exc
        text = item.get("zh", item.get("polished_zh", ""))
        if not isinstance(text, str) or not text.strip():
            raise PolishFormatError(f"字幕 {cue_id} 的润色结果为空")
        if cue_id in result:
            raise PolishFormatError(f"字幕 ID {cue_id} 重复")
        result[cue_id] = text.strip()
    if list(result) != expected_ids:
        raise PolishFormatError(
            f"字幕 ID 不匹配，期望 {expected_ids}，实际 {list(result)}"
        )
    return result


def validate_translation_polish_result(
    value: list[dict[str, Any]], expected_ids: list[int]
) -> dict[int, tuple[str, str]]:
    result: dict[int, tuple[str, str]] = {}
    for item in value:
        try:
            cue_id = int(item["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PolishFormatError("翻译结果缺少有效 id") from exc
        literal = item.get("literal_zh", "")
        polished = item.get("zh", "")
        if not isinstance(literal, str) or not literal.strip():
            raise PolishFormatError(f"字幕 {cue_id} 的直译为空")
        if not isinstance(polished, str) or not polished.strip():
            raise PolishFormatError(f"字幕 {cue_id} 的润色结果为空")
        if cue_id in result:
            raise PolishFormatError(f"字幕 ID {cue_id} 重复")
        result[cue_id] = (literal.strip(), polished.strip())
    if list(result) != expected_ids:
        raise PolishFormatError(
            f"字幕 ID 不匹配，期望 {expected_ids}，实际 {list(result)}"
        )
    return result


def polish_quality_error(text: str, cue: SubtitleCue) -> str | None:
    """Return a concise reason when a polished subtitle is not usable Chinese."""
    value = text.strip()
    if not value:
        return "译文为空"
    if KANA_RE.search(value):
        return "仍包含日文假名"
    if REPEATED_PUNCTUATION_RE.search(value):
        return "包含连续重复标点"

    meaningful = sum(char.isalnum() for char in value)
    punctuation = sum(
        unicodedata.category(char).startswith("P") or char in "…—～~"
        for char in value
    )
    if meaningful == 0:
        return "只有标点或符号"
    if len(value) >= 4 and punctuation > max(4, meaningful * 2):
        return "标点占比异常"
    if HAN_RE.search(cue.ja) and not HAN_RE.search(value):
        return "不包含中文字符"

    normalized_value = re.sub(r"\s+", "", value)
    normalized_source = re.sub(r"\s+", "", cue.ja)
    if KANA_RE.search(cue.ja) and normalized_value == normalized_source:
        return "直接复制了日文原文"
    return None


def validate_polish_quality(
    result: dict[int, str], targets: list[SubtitleCue]
) -> dict[int, str]:
    errors: dict[int, str] = {}
    for cue in targets:
        reason = polish_quality_error(result[cue.id], cue)
        if reason:
            errors[cue.id] = reason
    return errors


class QwenPolisher:
    def __init__(
        self,
        config: dict[str, Any],
        device: str,
        model_root: Path,
        offline: bool,
        prompt_path: Path,
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "缺少 Qwen 运行依赖，请运行 pip install -r requirements.txt"
            ) from exc
        self.torch = torch
        self.config = config
        self.device = device
        self.prompt_template = prompt_path.read_text(encoding="utf-8")
        model_root.mkdir(parents=True, exist_ok=True)
        model_name = str(config["model"])
        LOGGER.info("加载润色模型：%s (%s)", model_name, device)
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name, cache_dir=str(model_root), local_files_only=offline
        )
        dtype = self._dtype(str(config.get("dtype", "auto")))
        load_kwargs: dict[str, Any] = {
            "cache_dir": str(model_root),
            "local_files_only": offline,
            "dtype": dtype,
        }
        use_4bit = bool(config.get("load_in_4bit", False)) and device == "cuda"
        if use_4bit:
            try:
                from transformers import BitsAndBytesConfig
            except ImportError as exc:
                raise RuntimeError("4-bit Qwen 需要 bitsandbytes") from exc
            load_kwargs.update(
                quantization_config=BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=dtype,
                ),
                device_map={"": device},
            )
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name, **load_kwargs
            )
        else:
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name, **load_kwargs
            ).to(device)
        self.model.eval()

    def _dtype(self, name: str) -> Any:
        if name == "float16" or name == "auto" and self.device == "cuda":
            return self.torch.float16
        if name == "bfloat16":
            return self.torch.bfloat16
        return self.torch.float32

    def _render_prompt(
        self,
        before: list[SubtitleCue],
        targets: list[SubtitleCue],
        after: list[SubtitleCue],
        previous_error: str = "",
    ) -> str:
        def compact(cue: SubtitleCue) -> dict[str, Any]:
            # Small local models tend to copy even obviously broken NLLB drafts.
            # Keep the draft as an emergency fallback, but translate from Japanese
            # here so the model cannot be anchored by a fluent-looking mistranslation.
            return {"id": cue.id, "ja": cue.ja}

        payload = {
            "context_before": [compact(cue) for cue in before],
            "target_subtitles": [compact(cue) for cue in targets],
            "context_after": [compact(cue) for cue in after],
        }
        prompt = self.prompt_template.replace(
            "{{SUBTITLE_PAYLOAD}}", json.dumps(payload, ensure_ascii=False, indent=2)
        )
        if previous_error:
            prompt += (
                f"\n\n上次输出未通过校验：{previous_error}"
                "\n请修正这些问题，确保每个 zh 都是简体中文且只输出合法 JSON。"
            )
        return prompt

    def _generate(self, prompt: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是日语到简体中文的影视字幕翻译校对员。"
                    "zh 字段只能写简体中文，禁止复制日文，只返回要求的 JSON。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        template_kwargs = {
            "tokenize": False,
            "add_generation_prompt": True,
        }
        if "enable_thinking" in self.config:
            template_kwargs["enable_thinking"] = bool(self.config["enable_thinking"])
        try:
            rendered = self.tokenizer.apply_chat_template(messages, **template_kwargs)
        except TypeError:
            template_kwargs.pop("enable_thinking", None)
            rendered = self.tokenizer.apply_chat_template(messages, **template_kwargs)

        inputs = self.tokenizer(rendered, return_tensors="pt").to(self.device)
        temperature = float(self.config.get("temperature", 0.2))
        generate_kwargs: dict[str, Any] = {
            "max_new_tokens": int(self.config.get("max_new_tokens", 1024)),
            "do_sample": temperature > 0,
            "pad_token_id": self.tokenizer.eos_token_id,
        }
        if temperature > 0:
            generate_kwargs.update(
                temperature=temperature,
                top_p=float(self.config.get("top_p", 0.8)),
            )
        with self.torch.inference_mode():
            generated = self.model.generate(**inputs, **generate_kwargs)
        new_tokens = generated[0, inputs["input_ids"].shape[1] :]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    def _request_valid_polish(
        self,
        before: list[SubtitleCue],
        targets: list[SubtitleCue],
        after: list[SubtitleCue],
        attempts: int,
    ) -> dict[int, tuple[str, str]]:
        accepted: dict[int, tuple[str, str]] = {}
        pending = list(targets)
        error = ""
        generate_literal = bool(self.config.get("generate_literal", False))

        for attempt in range(attempts):
            expected_ids = [cue.id for cue in pending]
            try:
                response = self._generate(
                    self._render_prompt(before, pending, after, error)
                )
                payload = extract_json_array(response)
                if generate_literal:
                    candidate = validate_translation_polish_result(
                        payload, expected_ids
                    )
                else:
                    polished_only = validate_polish_result(payload, expected_ids)
                    candidate = {
                        cue.id: (cue.raw_zh, polished_only[cue.id]) for cue in pending
                    }
                literal_text = {
                    cue_id: pair[0] for cue_id, pair in candidate.items()
                }
                polished_text = {
                    cue_id: pair[1] for cue_id, pair in candidate.items()
                }
                quality_errors = validate_polish_quality(polished_text, pending)
                if generate_literal:
                    literal_errors = validate_polish_quality(literal_text, pending)
                    for cue_id, reason in literal_errors.items():
                        quality_errors[cue_id] = f"直译{reason}"
                for cue in pending:
                    if cue.id not in quality_errors:
                        accepted[cue.id] = candidate[cue.id]
                if not quality_errors:
                    return accepted
                error = "；".join(
                    f"字幕 {cue_id}：{reason}"
                    for cue_id, reason in quality_errors.items()
                )
                pending = [cue for cue in pending if cue.id in quality_errors]
            except PolishFormatError as exc:
                error = str(exc)

            LOGGER.warning(
                "润色字幕 %s 第 %s 次输出无效：%s",
                expected_ids,
                attempt + 1,
                error,
            )
        return accepted

    def polish(self, cues: list[SubtitleCue]) -> list[SubtitleCue]:
        batch_size = max(1, int(self.config.get("batch_size", 12)))
        before_count = max(0, int(self.config.get("context_before", 3)))
        after_count = max(0, int(self.config.get("context_after", 3)))
        retries = max(0, int(self.config.get("retries", 2)))

        for offset in range(0, len(cues), batch_size):
            targets = cues[offset : offset + batch_size]
            before = cues[max(0, offset - before_count) : offset]
            after = cues[offset + len(targets) : offset + len(targets) + after_count]
            expected_ids = [cue.id for cue in targets]
            polished = self._request_valid_polish(
                before, targets, after, retries + 1
            )

            missing = [cue for cue in targets if cue.id not in polished]
            if missing:
                LOGGER.warning(
                    "润色批次 %s 仍有异常，改为逐条重试：%s",
                    expected_ids,
                    [cue.id for cue in missing],
                )
            for cue in missing:
                cue_index = offset + targets.index(cue)
                single_before = cues[max(0, cue_index - before_count) : cue_index]
                single_after = cues[
                    cue_index + 1 : cue_index + 1 + after_count
                ]
                polished.update(
                    self._request_valid_polish(
                        single_before,
                        [cue],
                        single_after,
                        max(1, min(2, retries + 1)),
                    )
                )

            for cue in targets:
                if cue.id in polished:
                    continue
                fallback_error = polish_quality_error(cue.raw_zh, cue)
                if fallback_error:
                    raise RuntimeError(
                        f"字幕 {cue.id} 无法生成合格中文译文，"
                        f"回退结果也无效：{fallback_error}"
                    )
                LOGGER.error(
                    "字幕 %s 润色失败，回退到已通过质量检查的直译",
                    cue.id,
                )
                polished[cue.id] = (cue.raw_zh, cue.raw_zh)
            for cue in targets:
                literal, final = polished[cue.id]
                if bool(self.config.get("generate_literal", False)):
                    cue.raw_zh = literal
                cue.zh = final
        return cues

    def close(self) -> None:
        self.model = None
        self.tokenizer = None


class DeepSeekPolisher(QwenPolisher):
    """DeepSeek OpenAI-compatible API backend sharing the validation pipeline."""

    def __init__(self, config: dict[str, Any], prompt_path: Path) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "缺少在线 API 依赖，请运行 pip install -r requirements.txt"
            ) from exc
        self.httpx = httpx
        self.config = config
        self.prompt_template = prompt_path.read_text(encoding="utf-8")
        key_env = str(config.get("api_key_env", "DEEPSEEK_API_KEY"))
        self.api_key = os.environ.get(key_env, "").strip()
        if not self.api_key:
            raise RuntimeError(
                f"未设置 {key_env}。请先设置 DeepSeek API 密钥，"
                "或使用 --ja-only 仅生成日语字幕。"
            )
        self.base_url = str(config.get("base_url", "https://api.deepseek.com")).rstrip(
            "/"
        )
        timeout = max(10.0, float(config.get("api_timeout_seconds", 180)))
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "ja2zh-subtitle/online-api",
            },
        )
        LOGGER.info("使用 DeepSeek API：%s", config.get("model", "deepseek-v4-flash"))

    def _generate(self, prompt: str) -> str:
        body: dict[str, Any] = {
            "model": str(self.config.get("model", "deepseek-v4-flash")),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是日语到简体中文的影视字幕翻译校对员。"
                        "只返回符合用户格式要求的合法 JSON 对象；"
                        "literal_zh 和 zh 禁止复制日文。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": str(self.config.get("thinking", "disabled"))},
            "max_tokens": int(self.config.get("max_new_tokens", 4096)),
            "temperature": float(self.config.get("temperature", 0.0)),
            "top_p": float(self.config.get("top_p", 0.8)),
            "stream": False,
        }
        retries = max(0, int(self.config.get("api_retries", 5)))
        retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
        response = None
        for attempt in range(retries + 1):
            try:
                response = self.client.post(
                    f"{self.base_url}/chat/completions", json=body
                )
                if response.status_code not in retry_statuses:
                    response.raise_for_status()
                    break
                message = f"HTTP {response.status_code}"
            except self.httpx.HTTPError as exc:
                message = str(exc)
                response = None
            if attempt >= retries:
                raise RuntimeError(f"DeepSeek API 请求失败：{message}")
            delay = min(2**attempt, 20)
            if response is not None:
                try:
                    delay = min(float(response.headers.get("retry-after", delay)), 30)
                except ValueError:
                    pass
            LOGGER.warning(
                "DeepSeek API 请求失败（%s），%.0f 秒后重试 %s/%s",
                message,
                delay,
                attempt + 1,
                retries,
            )
            time.sleep(delay)

        assert response is not None
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("DeepSeek API 返回结构无效") from exc
        if not isinstance(content, str) or not content.strip():
            raise PolishFormatError("DeepSeek API 返回了空 JSON 内容")
        usage = payload.get("usage", {})
        if isinstance(usage, dict):
            LOGGER.info(
                "DeepSeek API 用量：输入 %s，输出 %s tokens",
                usage.get("prompt_tokens", "?"),
                usage.get("completion_tokens", "?"),
            )
        return content.strip()

    def close(self) -> None:
        self.client.close()
        self.api_key = ""


class MockPolisher:
    REPLACEMENTS = {
        "那么，我先去了。": "那我先走啦。",
        "感谢您的观看。": "感谢观看。",
    }

    def polish(self, cues: list[SubtitleCue]) -> list[SubtitleCue]:
        for cue in cues:
            if not cue.raw_zh:
                cue.raw_zh = f"测试译文：{cue.ja}"
            cue.zh = self.REPLACEMENTS.get(cue.raw_zh, cue.raw_zh)
        return cues

    def close(self) -> None:
        return None


def create_polisher(
    config: dict[str, Any],
    device: str,
    model_root: Path,
    offline: bool,
    prompt_path: Path,
    mock: bool,
) -> QwenPolisher | DeepSeekPolisher | MockPolisher:
    if mock:
        return MockPolisher()
    provider = str(config.get("provider", "deepseek")).lower()
    if provider == "deepseek":
        if offline:
            raise RuntimeError("DeepSeek 在线 API 与 --offline 不兼容")
        return DeepSeekPolisher(config, prompt_path)
    if provider != "qwen":
        raise ValueError(f"不支持的翻译润色提供方：{provider}")
    return QwenPolisher(config, device, model_root, offline, prompt_path)
