"""SnapCheck calibration (no training: the embedding model is pretrained CLIP or the fallback).
Genuine pairs = simulated customer photo of the same product; impostor pairs = photo of a
different product. Thresholds keep false MATCH and false MISMATCH at or below target_error_rate
(config/ml.yaml). Also measures search-by-photo top-1/top-5 accuracy."""
from __future__ import annotations

import numpy as np
from PIL import Image
from sklearn.metrics import roc_auc_score

from ai.common import data_hash, save_artifact
from ai.embedding import get_embedder
from ai.images import augment
from config.loader import ml


def train() -> dict:
    from backend.folder_one_core.catalog.models import Product

    cfg = ml()["models"]["snapcheck"]
    rng = np.random.default_rng(ml()["random_seed"])
    emb = get_embedder()
    products = [p for p in Product.objects.prefetch_related("images") if p.primary_image]
    imgs = []
    for p in products:
        with p.primary_image.image.open("rb") as fh:
            imgs.append(Image.open(fh).convert("RGB"))
    E = emb.embed(imgs)
    n = len(products)
    genuine, impostor, top1, top5 = [], [], 0, 0
    for _ in range(cfg["eval_pairs"]):
        i = int(rng.integers(n))
        q = emb.embed([augment(imgs[i], rng, cfg["augment"])])[0]
        sims = E @ q
        genuine.append(float(sims[i]))
        j = int(rng.integers(n - 1))
        j = j + (j >= i)
        impostor.append(float(sims[j]))
        rank = np.argsort(-sims)
        top1 += int(rank[0] == i)
        top5 += int(i in rank[:5])
    g, im = np.array(genuine), np.array(impostor)
    err = cfg["target_error_rate"]
    a, b = float(np.quantile(im, 1 - err)), float(np.quantile(g, err))
    mismatch_t, match_t = min(a, b), max(a, b)
    metrics = {
        "method": emb.name, "is_clip": emb.is_clip, "n_products": n, "n_pairs": cfg["eval_pairs"],
        "roc_auc": float(roc_auc_score(np.r_[np.ones(len(g)), np.zeros(len(im))], np.r_[g, im])),
        "genuine_mean": float(g.mean()), "impostor_mean": float(im.mean()),
        "match_threshold": match_t, "mismatch_threshold": mismatch_t,
        "false_match_rate": float((im >= match_t).mean()), "false_mismatch_rate": float((g < mismatch_t).mean()),
        "uncertain_rate_genuine": float(((g >= mismatch_t) & (g < match_t)).mean()),
        "photo_search_top1": top1 / cfg["eval_pairs"], "photo_search_top5": top5 / cfg["eval_pairs"],
        "photo_search_top1_baseline_random": 1 / n,
    }
    keys = [f"{p.sku}:{p.primary_image.image.name}" for p in products]
    save_artifact("snapcheck", {"method": emb.name, "embeddings": dict(zip(keys, E)), "match_threshold": match_t,
                                "mismatch_threshold": mismatch_t},
                  params=cfg, metrics=metrics, data_hash_value=data_hash(E),
                  notes=("Pretrained CLIP, not trained here." if emb.is_clip else
                         "CLIP could not be loaded; lightweight fallback embedding in use."))
    return metrics
