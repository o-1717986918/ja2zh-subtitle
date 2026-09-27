# ja2zh-subtitle v0.3.0

[![Tests](https://github.com/o-1717986918/ja2zh-subtitle/actions/workflows/tests.yml/badge.svg)](https://github.com/o-1717986918/ja2zh-subtitle/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

代码以 MIT 许可证开放。模型权重、字体和桌面运行时可能各自适用不同许可，详见
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。本仓库不包含视频、模型权重、安装包或构建产物。

本地日语识别＋在线高质量翻译的日语视频字幕流水线：

```text
视频 → faster-whisper 日语识别 → VAD 漏句回捞
     → DeepSeek API 忠实直译＋上下文润色 → SRT/ASS → FFmpeg 烧录视频
```

也可以完全跳过翻译：

```text
视频 → faster-whisper 日语识别 → 日语字幕后处理
     → 日语 SRT/ASS → FFmpeg 烧录日语字幕视频
```

Whisper 在本机运行；翻译与润色默认调用 DeepSeek 的 OpenAI 兼容 API，不再下载本地大语言模型。每个阶段都有缓存；中断后再次执行同一命令会从最近的有效阶段继续，已经成功的 API 结果不会重复计费。

## 已实现功能

- MP4、MKV、MOV 等 FFmpeg 支持的视频输入；
- 多音轨选择和 16kHz 单声道 WAV 提取；
- faster-whisper 日语识别、Silero VAD、词级时间戳；
- 自动检测主识别结果中的长空洞，以 no-VAD 局部二次识别回捞漏句；
- DeepSeek API 在一次上下文调用中同时生成忠实直译和自然中文字幕；
- 译文 JSON 校验、自动重试和保守回退；
- 中文标点、断句、换行、时长和字幕重叠处理；
- UTF-8 SRT、带样式 ASS 和烧录 MP4 输出；
- 日语原文字幕的一键生成与烧录，完全不加载翻译模型；
- 随包提供 Noto Sans CJK 中日字体，避免字幕乱码；
- 自动生成低置信度、回捞字幕、长空洞和阅读速度异常复核报告；
- 质量检查支持 `off`、`warn`、`strict`；默认 `warn` 只提示、不阻断输出；
- 支持目录批处理和修改字幕后的快速重新烧录；
- 提供基于 Tkinter 的桌面 GUI；
- Lite、Balanced、Quality 三档预设；
- CPU/CUDA 检测、自动档位、模型与 API 结果缓存；
- 不下载模型也能运行的 `--mock` 安装自检。

## 环境要求

- Python 3.10～3.12；
- FFmpeg 和 ffprobe，FFmpeg 必须包含 libass 字幕滤镜；
- 建议至少 16GB 系统内存；
- CPU 可以运行 Lite 档，但速度较慢；
- NVIDIA GPU 推荐 6GB 以上显存。

当前 faster-whisper 的 GPU 版本通常需要 CUDA 12 对应的 cuBLAS，以及 cuDNN 9。具体版本应以安装时的 faster-whisper/CTranslate2 文档为准。

## 安装

### Windows（推荐 Conda）

安装 Miniconda 后，在项目目录执行：

```bat
conda create -n ja2zh-subtitle python=3.11 -y
conda activate ja2zh-subtitle
python -m pip install -r requirements.txt
$env:DEEPSEEK_API_KEY="你的 DeepSeek API 密钥"
python main.py --doctor
```

仍可使用项目自带的 `setup_windows.bat` 创建普通 `.venv`。程序需要包含 libass 的 FFmpeg；Windows 下会自动搜索 PATH、注册表、WinGet 和 Conda 常见安装目录。

```bat
.venv\Scripts\python.exe main.py --doctor
```

Windows 下程序也会读取注册表中的最新用户/系统 PATH，并自动识别 WinGet 安装的
Gyan FFmpeg，因此安装 FFmpeg 后不必重启已经打开的终端。需要使用自定义位置时，
可分别设置 `JA2ZH_FFMPEG` 和 `JA2ZH_FFPROBE` 为可执行文件或其所在目录。

### Linux

```bash
sudo apt install ffmpeg python3-tk
chmod +x setup_linux.sh run_linux.sh gui_linux.sh
./setup_linux.sh
.venv/bin/python main.py --doctor
```

如果机器上的 CUDA/cuDNN 与 CTranslate2 不兼容，可先使用 CPU：

```bash
python main.py input.mp4 --preset lite --device cpu
```

## 快速自检

自检不下载 Whisper，也不会调用 DeepSeek API。程序会生成一段临时视频，并完整测试音频提取、字幕生成和字幕烧录：

```bash
python scripts/self_test.py
```

也可以手工测试某个视频：

```bash
python main.py input.mp4 --mock
```

`--mock` 仅用于验证安装和媒体流水线，生成的不是视频真实字幕。

## 正式使用

### WebUI（推荐）

Windows 双击 `webui_windows.bat`，或在 Conda 环境中运行：

```bash
python webui.py
```

浏览器会打开 `http://127.0.0.1:8765`。WebUI 可完成：

- 选择、拖入或填写本机视频路径；
- 设置 DeepSeek API Key；密钥可只保留在当前会话，也可保存到系统凭据库；
- 调整 ASR 档位、VAD、漏句回捞、质量模式、字幕排版与视频编码；
- 查看六阶段进度和实时日志、停止任务；
- 预览成片并下载字幕、质量报告和视频。

WebUI 默认只监听本机回环地址。API Key 不会写入 `config.yaml`、任务配置、日志
或浏览器响应；保存时使用操作系统凭据库。

### Windows 桌面安装包

Windows x64 桌面版使用原生 WebView2 窗口，安装后不需要 Python、Conda、
FFmpeg 或额外下载 Whisper 模型。安装包内置 Whisper-medium、FFmpeg/ffprobe、
中日字体、CPU 运行库、NVIDIA CUDA/cuDNN 运行库和 WebView2 离线安装程序。
没有 NVIDIA GPU 时自动使用 CPU；GPU 加速仍要求机器具有可用的 NVIDIA 驱动。

开发者可在已配置的 Conda 环境中执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

构建脚本先生成 PyInstaller onedir 便携目录，再使用 Inno Setup 生成单个安装程序。
`-CpuOnly` 可生成较小的纯 CPU 包，`-SkipPortableBuild` 可复用已有便携目录。
DeepSeek API、网络连接和用户自己的 API Key 不属于本地安装依赖。

### 图形界面

旧版 Tkinter 界面仍可使用：Windows 双击 `gui_windows.bat`；Linux 运行：

```bash
./gui_linux.sh
```

GUI 可以选择单个视频或目录、模型档位、日语模式、字幕模式和输出目录，
并在窗口中实时显示处理日志。

### 命令行

默认根据显存自动选择 Lite、Balanced 或 Quality：

```bash
python main.py input.mp4
```

只生成字幕：

```bash
python main.py input.mp4 --subtitle-only
```

只识别日语原文字幕并烧录到视频，完全跳过在线 API：

```bash
python main.py input.mp4 --ja-only
```

只生成日语字幕文件，不烧录视频：

```bash
python main.py input.mp4 --ja-only --subtitle-only
```

批量处理目录中的全部视频：

```bash
python main.py ./videos --ja-only --recursive --output-dir ./output
```

批处理会为每个视频建立独立输出目录；单个视频失败不会阻止后续视频处理。

人工修改 SRT/ASS 后直接重新烧录，不再运行识别、翻译或润色：

```bash
python main.py input.mp4 --burn-subtitle output/input_ja.srt --subtitle-language ja
python main.py input.mp4 --burn-subtitle output/input_zh.ass --subtitle-language zh
```

低配置模式：

```bash
python main.py input.mp4 --preset lite
```

高质量模式：

```bash
python main.py input.mp4 --preset quality
```

保留 DeepSeek 生成的忠实直译，跳过字幕化润色：

```bash
python main.py input.mp4 --no-polish
```

质量风险默认只写入复核报告，不阻断字幕或视频输出：

```bash
python main.py input.mp4 --quality-mode warn
```

需要跳过报告或用于自动化验收时，可分别使用 `--quality-mode off` 和
`--quality-mode strict`。无论哪种模式，损坏的时间轴等技术错误仍会停止输出。

指定第二条音轨：

```bash
python main.py input.mkv --audio-stream 1
```

首次正式运行会从 Hugging Face 下载 Whisper。`--offline` 只适用于已经缓存 Whisper 的日语字幕流程：

```bash
python main.py input.mp4 --ja-only --offline
```

也可以提前准备 Whisper：

```bash
python scripts/download_models.py --preset balanced
python scripts/download_models.py --preset quality
```

重新执行全部阶段而不读取缓存：

```bash
python main.py input.mp4 --force
```

## 输出文件

```text
output/
├── video_raw_ja.srt
├── video_ja.srt
├── video_ja.ass
├── video_review.txt
├── video_raw_zh.srt
├── video_zh.srt
├── video_zh.ass
├── video_zh_sub.mp4
└── .cache/
```

日语模式的视频名为 `video_ja_sub.mp4`；中文字幕模式的视频名为
`video_zh_sub.mp4`。`raw_ja.srt` 保留 Whisper 原始结果，`ja.srt` 是经过
标点、重复项和时间轴整理的结果。

`review.txt` 会列出低识别置信度、回捞字幕、长空洞、显示时间过短、疑似孤立
单字和阅读速度过快的字幕。默认门禁模式为 `warn`：报告只提供复核定位，不会
因为语义风险而停止生成结果。

`.cache` 保存音频和各模型阶段结果。配置没有改变时，再次运行可跳过已经完成的昂贵步骤。

## 模型档位

| 档位 | ASR | 翻译/润色 | 建议环境 |
| --- | --- | --- | --- |
| Lite | Whisper Small INT8 | DeepSeek API | CPU 或低显存 |
| Balanced | Whisper Medium | DeepSeek API | 6GB+ NVIDIA GPU |
| Quality | Whisper Large-v3 | DeepSeek API | 10GB+ NVIDIA GPU |

三档只改变本地 ASR 的速度与精度，在线翻译质量保持一致。默认模型为
`deepseek-v4-flash`，并关闭思考模式以降低字幕批处理的延迟和输出漂移。

## 自定义术语和字幕样式

可以编辑 `config.yaml`：

- `asr.initial_prompt`：加入作品名称、人物名和专有名词；
- `asr.hotwords`：提高特定词语的识别倾向；
- `asr.gap_recovery`：控制 VAD 漏句的局部回捞；
- `quality_control.mode`：设置 `off`、`warn` 或 `strict`；
- `subtitle.max_chars_per_line`：每行最大字符数；
- `subtitle.font_name`：ASS 字体名称；
- `video.fonts_dir`：额外字体目录；
- `video.codec`：`h264` 或 `h265`；
- `video.crf`：画面质量，越小质量越高、文件越大。

修改 `prompts/subtitle_translate_polish.txt` 可以调整翻译与润色风格，但不要删除
`id`、`literal_zh`、`zh` 和纯 JSON 输出约束。

## 测试

```bash
python -m unittest discover -s tests -v
python scripts/self_test.py
```

第一条运行纯 Python 单元测试，第二条运行包含真实 FFmpeg 编解码的集成测试。

提交代码前请运行单元测试。贡献流程和安全漏洞报告方式见
[`CONTRIBUTING.md`](CONTRIBUTING.md) 与 [`SECURITY.md`](SECURITY.md)。

## 已知限制

- 背景音乐过强、多人重叠说话、极端情绪声线会降低识别率；
- 人名和虚构专有名词仍建议配置提示词并人工复核；
- 漏句回捞可显著改善 VAD 误删，但强音乐、重叠说话和极弱对白仍可能漏识或误识；
- 自动断句面向单行/双行普通字幕，不代替专业字幕编辑器；
- 字幕烧录必须重新编码视频；只有音频会优先直接复制；
- 原音频编码不兼容 MP4 时，程序会自动回退到 AAC；
- 当前版本不包含说话人分离；GUI 主要负责参数选择和日志显示，不内置字幕编辑器。

## v0.3.0 重点变化

- 新增字幕质量检查报告，自动定位高风险字幕；
- 新增 `--burn-subtitle`，可快速烧录人工修改后的 SRT/ASS；
- 输入路径可以是目录，并支持 `--recursive` 递归批处理；
- 新增桌面 GUI，普通用户无需手写命令；
- SRT 重新烧录自动应用随包中日字体和字幕样式；
- 扩展集成自检，覆盖重新烧录流程。

## v0.2.0 重点变化

- `--ja-only` 现在可直接生成日语硬字幕视频；
- `--subtitle-only` 统一控制是否跳过视频烧录；
- 新增 `raw_ja.srt`、日语 ASS、日语标点/去重/时间轴后处理；
- 默认 `--preset auto`，硬件推荐会真正应用；
- 中日 CJK 字体随包提供，并自动传给 FFmpeg/libass；
- 新增模型预下载脚本和日语分支集成自检；
- 默认视频质量调整为 H.264 CRF 18，音频仍优先直接复制。

## 模型许可证提醒

本项目代码采用 MIT 许可证，但模型权重拥有各自的独立许可证。

本地 Whisper 权重和在线 API 服务分别适用各自的许可与服务条款；发布或商业使用前请自行核对。旧 NLLB/Qwen 配置不再属于默认运行链路，详见 `NOTICE_MODELS.md`。
