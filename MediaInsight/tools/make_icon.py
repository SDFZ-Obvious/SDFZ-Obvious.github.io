"""生成应用图标 assets/icon.ico（构建前运行一次）。"""
from pathlib import Path

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=56, fill="#2a78d6")
bars = [(52, 150), (100, 110), (148, 70)]
for x, top in bars:
    d.rounded_rectangle([x, top, x + 36, 200], radius=8, fill="#ffffff")
d.line([(60, 120), (118, 82), (166, 44), (204, 60)], fill="#eda100", width=12, joint="curve")
d.ellipse([194, 50, 214, 70], fill="#eda100")
out = Path(__file__).resolve().parent.parent / "assets"
out.mkdir(exist_ok=True)
img.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(out / "icon.png")
print("icon written to", out)
