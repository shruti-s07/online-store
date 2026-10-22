"""Procedural product photos (no external assets) and photo augmentations.

Each product gets a deterministic catalogue image: the glyph of its product type (from the icon
font bundled with qtawesome) in a product-specific colour. Augmentations simulate a customer's
photo of the received item.
"""
from __future__ import annotations

import colorsys
import io
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

@lru_cache(maxsize=1)
def _icon_font_files() -> tuple[str, dict]:
    """Material Design Icons font bundled with qtawesome (no network, no external assets)."""
    import importlib.util
    import json
    from pathlib import Path

    base = Path(importlib.util.find_spec("qtawesome").origin).parent / "fonts"
    ttf = sorted(base.glob("materialdesignicons6-webfont-*.ttf"))[-1]
    charmap = json.loads(sorted(base.glob("materialdesignicons6-webfont-charmap-*.json"))[-1].read_text())
    return str(ttf), charmap


@lru_cache(maxsize=8)
def _icon_font(px: int):
    return ImageFont.truetype(_icon_font_files()[0], px)


def _hls(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def product_image(icon: str, color_seed: int, size: int) -> Image.Image:
    """Catalogue packshot: light tinted backdrop, soft floor shadow and the product glyph in a
    product-specific colour. Deterministic per (icon, color_seed)."""
    rng = np.random.default_rng(color_seed)
    hue = float(rng.random())
    bg = _hls(hue, 0.965, 0.22)
    body = _hls(hue, float(rng.uniform(0.26, 0.46)), float(rng.uniform(0.25, 0.55)))
    img = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(img)
    # Soft floor shadow
    shadow = Image.new("L", (size, size), 0)
    ImageDraw.Draw(shadow).ellipse([size * 0.24, size * 0.78, size * 0.76, size * 0.86], fill=70)
    shadow = shadow.filter(ImageFilter.GaussianBlur(size / 40))
    img.paste(Image.new("RGB", (size, size), _hls(hue, 0.80, 0.20)), (0, 0), shadow)
    glyph = chr(int(_icon_font_files()[1][icon], 16))
    font = _icon_font(int(size * 0.62))
    box = d.textbbox((0, 0), glyph, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    x, y = (size - w) / 2 - box[0], size * 0.47 - h / 2 - box[1]
    d.text((x, y), glyph, font=font, fill=body)
    return img


def augment(img: Image.Image, rng: np.random.Generator, cfg: dict) -> Image.Image:
    """Simulate a phone photo: rotation, crop, lighting, sensor noise, slight blur."""
    size = img.size[0]
    out = img.rotate(float(rng.uniform(-cfg["rotate_degrees"], cfg["rotate_degrees"])), expand=False,
                     fillcolor=img.getpixel((1, 1)))
    f = cfg["crop_fraction"]
    l, t = rng.uniform(0, f, 2) * size
    r, b = size - rng.uniform(0, f, 2) * size
    out = out.crop((int(l), int(t), int(r), int(b))).resize((size, size))
    out = ImageEnhance.Brightness(out).enhance(float(rng.uniform(*cfg["brightness_range"])))
    arr = np.asarray(out).astype(float) + rng.normal(0, cfg["noise_sd"], (size, size, 3))
    out = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))
    return out.filter(ImageFilter.GaussianBlur(radius=float(rng.uniform(0, 1.0))))


def to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
