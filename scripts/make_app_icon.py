from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "assets" / "app.ico"


def main() -> None:
    canvas = Image.new("RGBA", (256, 256), "#172d38")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((18, 18, 238, 238), outline="#eef2f1", width=8)
    draw.rectangle((128, 18, 238, 238), fill="#1d7f78")
    draw.rectangle((18, 208, 238, 238), fill="#e8b44d")
    font_path = ROOT / "assets" / "fonts" / "NotoSansCJKsc-Regular.otf"
    font = ImageFont.truetype(str(font_path), 86)
    draw.text((31, 56), "字", fill="#eef2f1", font=font, stroke_width=1)
    draw.text((137, 56), "幕", fill="#eef2f1", font=font, stroke_width=1)
    canvas.save(
        TARGET,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"已生成应用图标：{TARGET}")


if __name__ == "__main__":
    main()

