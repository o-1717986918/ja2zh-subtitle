from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ja2zh_subtitle.config import load_config  # noqa: E402
from ja2zh_subtitle.device import detect_device  # noqa: E402


WHISPER_REPOSITORIES = {
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="预下载本地日语识别所需的 Whisper 模型")
    parser.add_argument(
        "--preset",
        choices=("auto", "lite", "balanced", "quality"),
        default="auto",
    )
    return parser


def download(repo_id: str, destination: Path) -> None:
    from huggingface_hub import snapshot_download

    destination.mkdir(parents=True, exist_ok=True)
    print(f"下载 {repo_id} → {destination}")
    snapshot_download(repo_id=repo_id, cache_dir=str(destination))


def main() -> int:
    args = build_parser().parse_args()
    profile = detect_device("auto")
    preset = profile.recommended_preset if args.preset == "auto" else args.preset
    config = load_config(ROOT / "config.yaml", preset)
    model_root = ROOT / str(config["runtime"].get("model_root", "models"))

    whisper_name = str(config["asr"]["model"])
    whisper_repo = WHISPER_REPOSITORIES.get(whisper_name, whisper_name)
    download(whisper_repo, model_root / "whisper")
    print(
        f"\n{preset} 档 Whisper 准备完成。--offline 仅适用于 --ja-only；"
        "中文字幕仍需 DEEPSEEK_API_KEY 和网络。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
