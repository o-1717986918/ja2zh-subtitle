from __future__ import annotations

import argparse
import copy
import importlib.util
import logging
import os
import sys
from pathlib import Path

from ja2zh_subtitle import __version__
from ja2zh_subtitle.config import load_config
from ja2zh_subtitle.device import detect_device
from ja2zh_subtitle.media import ffmpeg_has_libass, find_media_binary
from ja2zh_subtitle.pipeline import SubtitlePipeline
from ja2zh_subtitle.runtime import configure_bundled_environment, resource_root


configure_bundled_environment()
PROJECT_ROOT = resource_root()
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="完全本地运行的日语视频中文字幕生成工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", nargs="?", type=Path, help="输入视频路径")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.yaml")
    parser.add_argument(
        "--preset",
        choices=("auto", "lite", "balanced", "quality"),
        default="auto",
        help="模型档位；auto 根据显存自动选择",
    )
    parser.add_argument("--subtitle-only", action="store_true", help="只生成字幕，不烧录视频")
    parser.add_argument(
        "--ja-only",
        action="store_true",
        help="只生成日语字幕；默认继续烧录视频，与 --subtitle-only 联用则只输出字幕",
    )
    parser.add_argument("--no-polish", action="store_true", help="只保留 API 忠实直译，跳过口语化润色")
    parser.add_argument("--offline", action="store_true", help="禁止联网；仅与 --ja-only 联用")
    parser.add_argument("--mock", action="store_true", help="使用内置测试模型，仅用于安装验证")
    parser.add_argument("--force", action="store_true", help="忽略缓存，重新执行所有阶段")
    parser.add_argument("--output-dir", type=Path, help="输出目录")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="输入为目录时递归查找视频",
    )
    parser.add_argument(
        "--burn-subtitle",
        type=Path,
        help="直接烧录已编辑的 SRT/ASS，不运行识别和翻译",
    )
    parser.add_argument(
        "--subtitle-language",
        choices=("auto", "ja", "zh"),
        default="auto",
        help="外部 SRT 的样式语言",
    )
    parser.add_argument("--audio-stream", type=int, help="按音轨顺序选择音轨，从 0 开始")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), help="推理设备")
    parser.add_argument(
        "--no-vad",
        action="store_true",
        help="关闭静音过滤；对白被 VAD 漏掉时可使用",
    )
    parser.add_argument(
        "--quality-mode",
        choices=("off", "warn", "strict"),
        help="质量门禁：off 跳过，warn 只告警，strict 严格检查",
    )
    parser.add_argument("--doctor", action="store_true", help="检查运行环境后退出")
    parser.add_argument("--verbose", action="store_true", help="显示调试日志")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def doctor() -> int:
    profile = detect_device("auto")
    python_ok = (3, 10) <= sys.version_info[:2] <= (3, 12)
    print(f"Python: {sys.version.split()[0]} ({'OK' if python_ok else 'UNSUPPORTED'})")
    ffmpeg = find_media_binary("ffmpeg")
    ffprobe = find_media_binary("ffprobe")
    print(f"FFmpeg: {f'OK ({ffmpeg})' if ffmpeg else 'MISSING'}")
    print(f"ffprobe: {f'OK ({ffprobe})' if ffprobe else 'MISSING'}")
    print(f"libass 字幕滤镜: {'OK' if ffmpeg_has_libass() else 'MISSING'}")
    bundled_fonts = PROJECT_ROOT / "assets" / "fonts"
    print(f"随包中日字体: {'OK' if any(bundled_fonts.glob('*.otf')) else 'MISSING'}")
    modules = ("yaml", "ctranslate2", "faster_whisper", "httpx")
    module_status = {module: importlib.util.find_spec(module) is not None for module in modules}
    for module, installed in module_status.items():
        print(f"{module}: {'OK' if installed else 'MISSING'}")
    deepseek_key = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
    print(
        "DEEPSEEK_API_KEY: "
        + ("SET" if deepseek_key else "MISSING（中文字幕需设置；--ja-only 不需要）")
    )
    print(f"推理设备: {profile.device}")
    print(f"显存: {profile.vram_gb if profile.vram_gb is not None else '未知/无'} GB")
    print(f"内存: {profile.ram_gb if profile.ram_gb is not None else '未知'} GB")
    print(f"推荐档位: {profile.recommended_preset}")
    for note in profile.notes:
        print(f"说明: {note}")
    essential = (
        python_ok
        and ffmpeg
        and ffprobe
        and ffmpeg_has_libass()
        and any(bundled_fonts.glob("*.otf"))
        and all(module_status.values())
    )
    return 0 if essential else 1


def collect_videos(source: Path, recursive: bool) -> list[Path]:
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise FileNotFoundError(f"输入不存在：{source}")
    iterator = source.rglob("*") if recursive else source.glob("*")
    return sorted(
        path
        for path in iterator
        if path.is_file()
        and path.suffix.lower() in VIDEO_EXTENSIONS
        and not path.stem.endswith(("_ja_sub", "_zh_sub", "_sub"))
    )


def print_result(result) -> None:
    print(f"  原始日语字幕：{result.raw_japanese_srt}")
    print(f"  日语字幕：{result.japanese_srt}")
    print(f"  日语 ASS：{result.japanese_ass}")
    print(f"  质量检查：{result.review_report}")
    if result.raw_chinese_srt:
        print(f"  原始译文：{result.raw_chinese_srt}")
    if result.chinese_srt:
        print(f"  中文字幕：{result.chinese_srt}")
    if result.chinese_ass:
        print(f"  ASS 字幕：{result.chinese_ass}")
    if result.video:
        print(f"  烧录视频：{result.video}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.doctor:
        return doctor()
    if args.input is None:
        print("错误：请提供输入视频，或使用 --doctor 检查环境", file=sys.stderr)
        return 2

    try:
        requested_device = args.device or "auto"
        detected = detect_device(requested_device)
        selected_preset = (
            detected.recommended_preset if args.preset == "auto" else args.preset
        )
        base_config = load_config(args.config, selected_preset)
        if args.output_dir is not None:
            base_config["runtime"]["output_dir"] = str(args.output_dir)
        if args.audio_stream is not None:
            base_config["runtime"]["audio_stream"] = args.audio_stream
        if args.device is not None:
            base_config["runtime"]["device"] = args.device
        if args.no_vad:
            base_config["asr"]["vad_filter"] = False
        if args.quality_mode is not None:
            base_config["quality_control"]["mode"] = args.quality_mode
        base_config["runtime"]["offline"] = bool(args.offline)
        base_config["runtime"]["mock"] = bool(args.mock)

        pipeline = SubtitlePipeline(base_config, PROJECT_ROOT)
        profile = pipeline.profile
        logging.info(
            "运行设备：%s；显存：%s GB；当前档位：%s；推荐档位：%s",
            profile.device,
            profile.vram_gb if profile.vram_gb is not None else "未知/无",
            selected_preset,
            profile.recommended_preset,
        )

        if args.burn_subtitle is not None:
            if args.input.is_dir():
                raise ValueError("--burn-subtitle 只能与单个视频文件配合使用")
            output = pipeline.burn_existing_subtitle(
                args.input,
                args.burn_subtitle,
                args.output_dir,
                args.subtitle_language,
            )
            print(f"\n字幕烧录完成：{output}")
            return 0

        videos = collect_videos(args.input, args.recursive)
        if not videos:
            raise RuntimeError("输入目录中没有找到支持的视频文件")
        batch_mode = len(videos) > 1 or args.input.is_dir()
        output_root = Path(str(base_config["runtime"].get("output_dir", "output")))
        failures: list[tuple[Path, str]] = []
        for index, video in enumerate(videos, start=1):
            config = copy.deepcopy(base_config)
            if batch_mode:
                if args.input.is_dir():
                    relative = video.resolve().relative_to(args.input.resolve())
                    target_dir = output_root / relative.parent / relative.stem
                else:
                    target_dir = output_root / video.stem
                config["runtime"]["output_dir"] = str(target_dir)
                logging.info("批处理 [%s/%s]：%s", index, len(videos), video)
            try:
                result = SubtitlePipeline(config, PROJECT_ROOT).run(
                    video,
                    subtitle_only=args.subtitle_only,
                    japanese_only=args.ja_only,
                    no_polish=args.no_polish,
                    force=args.force,
                )
                print(f"\n处理完成：{video}")
                print_result(result)
            except Exception as exc:
                failures.append((video, str(exc)))
                logging.error("处理失败：%s：%s", video, exc)
                if not batch_mode:
                    raise
        if failures:
            print(f"\n批处理结束：成功 {len(videos) - len(failures)}，失败 {len(failures)}")
            for video, reason in failures:
                print(f"  失败：{video}：{reason}")
            return 1
        if batch_mode:
            print(f"\n批处理完成：共 {len(videos)} 个视频。")
        return 0
    except KeyboardInterrupt:
        print("\n用户取消。已完成阶段的缓存仍然保留。", file=sys.stderr)
        return 130
    except Exception as exc:
        logging.error("处理失败：%s", exc)
        if args.verbose:
            logging.exception("详细错误")
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
