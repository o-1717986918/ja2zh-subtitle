# v0.3.0 发布说明

这是面向实际日常使用的增强版本，在完整中日字幕工作流基础上加入 GUI、
批处理、质量检查和字幕快速重新烧录。

## 推荐命令

```bash
# 自动选择模型档位，生成中文字幕并烧录
python main.py input.mp4

# 使用 Large-v3，只生成并烧录日语原字幕
python main.py input.mp4 --ja-only --preset quality

# 只输出日语 SRT/ASS
python main.py input.mp4 --ja-only --subtitle-only --preset quality

# 批量处理目录
python main.py ./videos --ja-only --recursive

# 修改字幕后重新烧录，不重复识别
python main.py input.mp4 --burn-subtitle output/input_ja.srt --subtitle-language ja
```

## 验证范围

- 纯 Python 单元测试覆盖缓存、配置、批量发现、分段、字幕处理、质量检查和润色格式校验；
- FFmpeg 集成自检覆盖中文、日语和外部 SRT 重新烧录；
- 真实日语 MP4 回归验证覆盖 Large-v3 识别结果的日语 ASS 烧录。

## 仍需人工关注

Whisper 可能在背景音乐、重叠对白、人名和短促语气词上出错。程序会保留
`raw_ja.srt` 便于对照，但不会自动猜测缺失台词。正式发布字幕前仍建议抽查。
