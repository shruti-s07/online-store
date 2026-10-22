"""Hybrid recommender: item-item collaborative filtering (cosine on the user-item matrix) +
content similarity (TF-IDF on product text) + popularity, weighted by config.
Evaluation: leave-last-order-out per user, Precision@K and NDCG@K vs popularity."""
from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ai.common import data_hash, save_artifact
from ai.datasets import interactions, product_text
from config.loader import business, ml


def build(inter, products) -> dict:
    skus = list(products["sku"])
    idx = {s: i for i, s in enumerate(skus)}
    users = {u: i for i, u in enumerate(sorted(inter["user_id"].unique()))}
    m = np.zeros((len(users), len(skus)))
    for u, s in zip(inter["user_id"], inter["sku"]):
        m[users[u], idx[s]] = 1.0
    cf = cosine_similarity(m.T)
    np.fill_diagonal(cf, 0)
    tf = TfidfVectorizer(max_features=ml()["models"]["recommendations"]["content_max_features"],
                         stop_words="english").fit_transform(products["text"])
    cb = cosine_similarity(tf)
    np.fill_diagonal(cb, 0)
    pop = m.sum(axis=0)
    pop = pop / pop.max() if pop.max() else pop
    return {"skus": skus, "names": list(products["name"]), "categories": list(products["category__name"]),
            "cf_sim": cf, "content_sim": cb, "popularity": pop}


def _ndcg(rec, relevant, k):
    dcg = sum(1 / np.log2(i + 2) for i, r in enumerate(rec[:k]) if r in relevant)
    idcg = sum(1 / np.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / idcg if idcg else 0.0


def evaluate(bundle, train_hist, test_items, k, weights) -> dict:
    from backend.folder_two_services.recommendations.service import score_items

    idx = {s: i for i, s in enumerate(bundle["skus"])}
    p_at_k, ndcg = [], []
    for u, held in test_items.items():
        hist = [idx[s] for s in train_hist[u]]
        score, *_ = score_items(bundle, hist, weights)
        score = score.copy()
        score[hist] = -np.inf
        rec = [bundle["skus"][i] for i in np.argsort(-score)[:k]]
        p_at_k.append(len(set(rec) & held) / k)
        ndcg.append(_ndcg(rec, held, k))
    return {"precision_at_k": float(np.mean(p_at_k)), "ndcg_at_k": float(np.mean(ndcg))}


def train() -> dict:
    cfg = ml()["models"]["recommendations"]
    k = cfg["eval_k"]
    inter = interactions()
    products = product_text()
    last_order = inter.groupby("user_id")["ts"].transform("max")
    is_test = inter["ts"] == last_order
    hist = inter[~is_test].groupby("user_id")["sku"].apply(set)
    held = inter[is_test].groupby("user_id")["sku"].apply(set)
    eligible = [u for u in held.index if u in hist.index and len(hist[u]) >= cfg["min_user_purchases"]
                and held[u] - hist[u]]
    test_items = {u: held[u] - hist[u] for u in eligible}
    bundle = build(inter[~is_test], products)
    w = business()["recommendations"]["weights"]
    variants = {"hybrid": w, "collaborative_only": {"collaborative": 1, "content": 0, "popularity": 0},
                "content_only": {"collaborative": 0, "content": 1, "popularity": 0},
                "baseline_popularity": {"collaborative": 0, "content": 0, "popularity": 1}}
    metrics = {"k": k, "n_eval_users": len(test_items)}
    for name, weights in variants.items():
        r = evaluate(bundle, hist, test_items, k, weights)
        metrics[f"precision_at_{k}_{name}"] = r["precision_at_k"]
        metrics[f"ndcg_at_{k}_{name}"] = r["ndcg_at_k"]
    final = build(inter, products)
    save_artifact("recommendations", final, params={**cfg, "weights": w}, metrics=metrics,
                  data_hash_value=data_hash(inter[["user_id", "sku"]]))
    return metrics
