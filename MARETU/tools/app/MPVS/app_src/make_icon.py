# -*- coding: utf-8 -*-
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

OUT = Path(r"C:\Users\Obvious\Documents\deepseek-harness\default-workspace\app_src\assets")
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# rounded dark tile
pad = 60
d.rounded_rectangle((pad, pad, S - pad, S - pad), radius=200, fill=(11, 12, 16, 255))
# accent bar / mark
d.rounded_rectangle((pad + 40, pad + 40, pad + 120, S - pad - 40), radius=40, fill=(255, 59, 92, 255))

font = None
for name in ("arialbd.ttf", "segoeuib.ttf", "segoeuib.ttf"):
    try:
        font = ImageFont.truetype(name, 430)
        break
    except OSError:
        continue
if font is None:
    font = ImageFont.load_default()

text = "M"
bbox = d.textbbox((0, 0), text, font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
tx = pad + 120 + (S - 2 * pad - 120 - tw) / 2
ty = (S - th) / 2 - bbox[1]
d.text((tx, ty), text, font=font, fill=(245, 246, 250, 255))

img.save(OUT / "icon.png")
img.resize((256, 256), Image.LANCZOS).save(
    OUT / "icon.ico", format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("icon written")
