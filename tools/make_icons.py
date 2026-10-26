"""生成托盘与打包用的图标（resources/icon.png、resources/icon.ico）。

仓库不提交二进制图标，克隆后先运行本脚本再打包：

    python tools/make_icons.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "resources"


def draw_icon(size: int = 256) -> Image.Image:
    scale = 4
    w = size * scale
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 深色圆角底板
    d.rounded_rectangle([0, 0, w - 1, w - 1], radius=int(w * 0.22), fill=(26, 30, 38, 255))
    # 白色页面长条
    d.rounded_rectangle(
        [int(w * 0.26), int(w * 0.13), int(w * 0.74), int(w * 0.55)],
        radius=int(w * 0.05),
        fill=(255, 255, 255, 255),
    )
    # 蓝色向下箭头（轴 + 三角）
    blue = (47, 124, 246, 255)
    d.rounded_rectangle(
        [int(w * 0.44), int(w * 0.44), int(w * 0.56), int(w * 0.70)],
        radius=int(w * 0.02),
        fill=blue,
    )
    d.polygon(
        [
            (int(w * 0.30), int(w * 0.66)),
            (int(w * 0.70), int(w * 0.66)),
            (int(w * 0.50), int(w * 0.90)),
        ],
        fill=blue,
    )

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    RES.mkdir(parents=True, exist_ok=True)
    icon = draw_icon(256)
    icon.save(RES / "icon.png")
    icon.save(
        RES / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("已生成:", RES / "icon.png", RES / "icon.ico")


if __name__ == "__main__":
    main()
