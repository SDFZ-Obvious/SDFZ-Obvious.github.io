# -*- coding: utf-8 -*-
"""Compositing engine that recreates the layer stack of 模板.psd.

Layer stack (bottom -> top), as used by the app:

    背景        fixed white canvas (never replaced)
    黑白渐变    radial white -> dark gradient, radius adjustable
    网格        perspective grid (smart object + mask)
    词云        word cloud, MULTIPLY, opacity adjustable (PSD: 29 %)
    背景/做旧   user supplied image, COLOR BURN (the "grunge" layer)
    组 2        top / bottom black bars
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

FULL_W, FULL_H = 1920, 1080
WORDCLOUD_BOX = (778.0, 776.0)
WORDCLOUD_DEFAULT_CENTER = (960.0, 540.0)
WORDCLOUD_OPACITY = 0.29          # PSD layer opacity 74/255
MASK_POWER = 3.2
DEFAULT_RADIUS = 540.0
TEXTURE_STRENGTH = 1.00


def load_image(path: str | Path) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
    return img


def cover_resize(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale + centre-crop to exactly (w, h) without distortion."""
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return Image.new("RGB", (w, h), (255, 255, 255))
    scale = max(w / src_w, h / src_h)
    nw, nh = max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale)))
    resized = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = (nh - h) // 2
    return resized.crop((left, top, left + w, top + h))


def wordcloud_rect(wc_size: tuple[int, int], centre: tuple[float, float],
                   wc_scale: float) -> tuple[float, float, float, float]:
    """Return (left, top, right, bottom) of the word cloud in canvas coords."""
    iw, ih = wc_size
    if iw <= 0 or ih <= 0:
        return (0, 0, 0, 0)
    k = min(WORDCLOUD_BOX[0] * wc_scale / iw, WORDCLOUD_BOX[1] * wc_scale / ih)
    nw, nh = iw * k, ih * k
    cx, cy = centre
    return (cx - nw / 2, cy - nh / 2, cx + nw / 2, cy + nh / 2)


def _burn_lut() -> np.ndarray:
    b = np.arange(256, dtype=np.int32)[:, None]
    s = np.arange(1, 256, dtype=np.int32)[None, :]
    lut = 255 - np.minimum(255, (255 - b) * 255 // s)
    return np.clip(lut, 0, 255).astype(np.uint8)


class Renderer:
    def __init__(self, assets_dir: str | Path):
        assets = Path(assets_dir)
        self.gradient_img = Image.open(assets / "gradient.png").convert("L")
        self.grid = Image.open(assets / "grid.png").convert("RGBA")
        self.bars = Image.open(assets / "bars.png").convert("RGBA")
        self._lut = _burn_lut()
        self._profile = self._build_profile(self.gradient_img)
        self._grad_cache: dict = {}
        self._scaled: dict = {}
        self._wc_cache: tuple | None = None

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _build_profile(img: Image.Image) -> np.ndarray:
        """Radial luminance profile of the PSD gradient (index = radius px)."""
        arr = np.asarray(img).astype(np.float32) / 255.0
        h, w = arr.shape
        yy, xx = np.ogrid[0:h, 0:w]
        r = np.sqrt((xx - w / 2.0) ** 2 + (yy - h / 2.0) ** 2).astype(np.int32)
        sums = np.bincount(r.ravel(), weights=arr.ravel())
        counts = np.bincount(r.ravel())
        prof = sums / np.maximum(counts, 1)
        # light smoothing so the lookup is stable
        k = 9
        kernel = np.ones(k, np.float32) / k
        prof = np.convolve(prof, kernel, mode="same")
        prof[: k] = prof[k]
        prof[-k:] = prof[-k - 1]
        return prof.astype(np.float32)

    def _scaled_asset(self, name: str, img: Image.Image, size: tuple[int, int]) -> Image.Image:
        key = (name, size)
        if key not in self._scaled:
            if len(self._scaled) > 24:
                self._scaled.clear()
            self._scaled[key] = img.resize(size, Image.LANCZOS)
        return self._scaled[key]

    def _gradient(self, w: int, h: int, radius: float) -> np.ndarray:
        key = (w, h, round(radius, 1))
        if key in self._grad_cache:
            return self._grad_cache[key]
        if len(self._grad_cache) > 12:
            self._grad_cache.clear()
        yy, xx = np.ogrid[0:h, 0:w]
        r = np.sqrt((xx - w / 2.0) ** 2 + (yy - h / 2.0) ** 2) * (FULL_W / w)
        rr = r * (DEFAULT_RADIUS / max(radius, 8.0))
        idx = np.clip(rr, 0, len(self._profile) - 1).astype(np.int32)
        g = self._profile[idx] * 255.0
        out = np.dstack([g, g, g]).astype(np.float32)
        self._grad_cache[key] = out
        return out

    def _wordcloud_image(self, wordcloud: Image.Image, wc_scale: float, w: int, h: int) -> Image.Image:
        s = w / FULL_W
        box_w, box_h = WORDCLOUD_BOX[0] * wc_scale * s, WORDCLOUD_BOX[1] * wc_scale * s
        iw, ih = wordcloud.size
        k = min(box_w / iw, box_h / ih)
        nw, nh = max(1, round(iw * k)), max(1, round(ih * k))
        key = (id(wordcloud), nw, nh)
        if self._wc_cache and self._wc_cache[0] == key:
            return self._wc_cache[1]
        img = wordcloud.convert("RGBA").resize((nw, nh), Image.LANCZOS)
        self._wc_cache = (key, img)
        return img

    # ------------------------------------------------------------------ render
    def render(
        self,
        texture: Image.Image | None,
        wordcloud: Image.Image | None,
        radius: float = DEFAULT_RADIUS,
        wc_center: tuple[float, float] = WORDCLOUD_DEFAULT_CENTER,
        wc_scale: float = 1.0,
        wc_opacity: float = WORDCLOUD_OPACITY,
        grayscale: bool = False,
        texture_strength: float = TEXTURE_STRENGTH,
        show_deco: bool = True,
        scale: float = 1.0,
    ) -> Image.Image:
        w = max(2, round(FULL_W * scale))
        h = max(2, round(FULL_H * scale))

        # 1-2. fixed white background + radial gradient light
        base = self._gradient(w, h, radius).copy()

        # 3. grid (below word cloud and grunge, like the PSD)
        if show_deco:
            grid = self._scaled_asset("grid", self.grid, (w, h))
            frame = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")
            frame = Image.alpha_composite(frame.convert("RGBA"), grid)
            base = np.asarray(frame.convert("RGB")).astype(np.float32)

        # 4. word cloud (multiply, adjustable opacity)
        if wordcloud is not None and wc_opacity > 0.001:
            wc = self._wordcloud_image(wordcloud, wc_scale, w, h)
            nw, nh = wc.size
            cx, cy = wc_center[0] * (w / FULL_W), wc_center[1] * (w / FULL_W)
            x0, y0 = int(round(cx - nw / 2)), int(round(cy - nh / 2))
            sx0, sy0 = max(0, -x0), max(0, -y0)
            dx0, dy0 = max(0, x0), max(0, y0)
            cw, ch = min(nw - sx0, w - dx0), min(nh - sy0, h - dy0)
            if cw > 0 and ch > 0:
                arr = np.asarray(wc.crop((sx0, sy0, sx0 + cw, sy0 + ch))).astype(np.float32)
                a = arr[..., 3:4] / 255.0
                rgb = arr[..., :3]
                region = base[dy0:dy0 + ch, dx0:dx0 + cw]
                base[dy0:dy0 + ch, dx0:dx0 + cw] = region * (
                    1.0 - a * wc_opacity * (1.0 - rgb / 255.0)
                )

        if grayscale:
            lum = base[..., 0] * 0.299 + base[..., 1] * 0.587 + base[..., 2] * 0.114
            base = np.dstack([lum, lum, lum]).astype(np.float32)

        # 5. user image -> COLOR BURN (the "grunge / 做旧" layer)
        if texture is not None and texture_strength > 0.001:
            tex = cover_resize(texture.convert("RGBA"), w, h)
            tex_arr = np.asarray(tex)
            tex_rgb = np.clip(tex_arr[..., :3].astype(np.int32), 1, 255).astype(np.uint8) - 1
            alpha = (tex_arr[..., 3:4].astype(np.float32) / 255.0) * texture_strength
            burned = self._lut[
                np.clip(base, 0, 255).astype(np.uint8), tex_rgb
            ].astype(np.float32)
            base = base * (1.0 - alpha) + burned * alpha

        out = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")

        # 6. top / bottom bars
        if show_deco:
            bars = self._scaled_asset("bars", self.bars, (w, h))
            out = Image.alpha_composite(out.convert("RGBA"), bars).convert("RGB")

        return out
