"""Image embeddings for SnapCheck and search-by-photo.

Preferred: a pretrained CLIP model (open_clip, weights from the Hugging Face hub). It is NOT
trained here. If open_clip/torch are not installed, CLIP is disabled in .env, or the weights
cannot be downloaded, a lightweight hand-crafted embedding is used instead:
  HSV colour histogram + gradient-orientation histogram (4x4 cells) + 16x16 grey thumbnail.
The active method is reported by every API response and in ai/models/REPORT.md.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
from PIL import Image

from config.loader import env, env_bool, ml

log = logging.getLogger(__name__)


class FallbackEmbedder:
    name = "fallback: colour histogram + gradient orientations + thumbnail (CLIP unavailable)"
    is_clip = False

    def _one(self, img: Image.Image) -> np.ndarray:
        img = img.convert("RGB").resize((64, 64))
        hsv = np.asarray(img.convert("HSV"), dtype=float)
        hist, _ = np.histogramdd(hsv.reshape(-1, 3), bins=(8, 4, 4), range=((0, 256), (0, 256), (0, 256)))
        color = hist.ravel()
        grey = np.asarray(img.convert("L"), dtype=float)
        gy, gx = np.gradient(grey)
        mag, ang = np.hypot(gx, gy), (np.arctan2(gy, gx) % np.pi)
        cells = []
        for i in range(4):
            for j in range(4):
                sl = (slice(i * 16, (i + 1) * 16), slice(j * 16, (j + 1) * 16))
                h, _ = np.histogram(ang[sl], bins=8, range=(0, np.pi), weights=mag[sl])
                cells.append(h)
        grad = np.concatenate(cells)
        thumb = np.asarray(img.convert("L").resize((16, 16)), dtype=float).ravel()
        thumb = thumb - thumb.mean()
        parts = [np.sqrt(color), np.sqrt(grad), thumb]
        parts = [p / (np.linalg.norm(p) + 1e-9) for p in parts]
        w = ml()["models"]["snapcheck"]["fallback_block_weights"]
        v = np.concatenate([p * wi for p, wi in zip(parts, w)])
        return v / (np.linalg.norm(v) + 1e-9)

    def embed(self, images: list[Image.Image]) -> np.ndarray:
        return np.stack([self._one(i) for i in images])


class ClipEmbedder:
    is_clip = True

    def __init__(self, model_name: str, pretrained: str):
        import open_clip  # noqa: F401  (optional dependency, requirements-clip.txt)
        import torch

        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
        self.model.eval()
        self.name = f"CLIP {model_name} ({pretrained})"

    def embed(self, images: list[Image.Image]) -> np.ndarray:
        with self.torch.no_grad():
            batch = self.torch.stack([self.preprocess(i.convert("RGB")) for i in images])
            feats = self.model.encode_image(batch).float().numpy()
        return feats / np.linalg.norm(feats, axis=1, keepdims=True)


@lru_cache(maxsize=1)
def get_embedder():
    if env_bool("CLIP_ENABLED", False):
        try:
            return ClipEmbedder(env("CLIP_MODEL_NAME"), env("CLIP_PRETRAINED"))
        except Exception as exc:  # missing package, no network, blocked hub...
            log.warning("CLIP unavailable (%s); using the lightweight fallback embedding.", exc)
    return FallbackEmbedder()
