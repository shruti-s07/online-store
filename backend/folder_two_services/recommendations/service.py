"""Hybrid recommendations: item-item collaborative filtering + content similarity + popularity.
Weights come from config/business.yaml (recommendations.weights)."""
from __future__ import annotations

import numpy as np

from ai.common import load_artifact
from backend.folder_one_core.catalog.models import Product
from backend.folder_one_core.inventory.services import availability_map
from backend.folder_one_core.orders.models import OrderItem
from backend.folder_two_services.model_errors import ModelNotTrained
from config.loader import business


def _bundle():
    b = load_artifact("recommendations")
    if b is None:
        raise ModelNotTrained("recommendations")
    return b


def score_items(bundle, history_idx: list[int], weights: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Returns (score, cf_part, content_part, pop_part) for every item index."""
    n = len(bundle["skus"])
    pop = bundle["popularity"]
    if history_idx:
        cf = bundle["cf_sim"][history_idx].mean(axis=0)
        cb = bundle["content_sim"][history_idx].mean(axis=0)
    else:
        cf, cb = np.zeros(n), np.zeros(n)
    parts = (weights["collaborative"] * cf, weights["content"] * cb, weights["popularity"] * pop)
    return parts[0] + parts[1] + parts[2], *parts


def _reason(bundle, idx, history_idx, parts, names, cats) -> str:
    cf, cb, pop = (p[idx] for p in parts)
    if history_idx and cf >= max(cb, pop) and cf > 0:
        anchor = max(history_idx, key=lambda h: bundle["cf_sim"][h, idx])
        return f"Customers who bought {names[anchor]} also bought this"
    if history_idx and cb >= pop and cb > 0:
        anchor = max(history_idx, key=lambda h: bundle["content_sim"][h, idx])
        return f"Similar to {names[anchor]} you bought"
    return f"Popular in {cats[idx]}"


def for_user(user, k: int | None = None) -> list[dict]:
    bundle = _bundle()
    k = k or business()["recommendations"]["top_k"]
    weights = business()["recommendations"]["weights"]
    index = {s: i for i, s in enumerate(bundle["skus"])}
    bought = set(OrderItem.objects.filter(order__user=user).values_list("product__sku", flat=True))
    history_idx = [index[s] for s in bought if s in index]
    score, *parts = score_items(bundle, history_idx, weights)
    products = {p.sku: p for p in Product.objects.select_related("category").filter(sku__in=bundle["skus"])}
    avail = availability_map([p.id for p in products.values()])
    names = bundle["names"]
    cats = bundle["categories"]
    out = []
    for i in np.argsort(-score):
        sku = bundle["skus"][i]
        p = products.get(sku)
        if p is None or sku in bought or avail[p.id]["available"] <= 0:
            continue
        out.append({"product_id": p.id, "sku": sku, "name": p.name, "price": str(p.price),
                    "category": p.category.name, "score": round(float(score[i]), 4),
                    "image": p.primary_image.image.url if p.primary_image else None,
                    "reason": _reason(bundle, i, history_idx, parts, names, cats)})
        if len(out) >= k:
            break
    return out


def similar_products(product_id: int, k: int | None = None) -> list[dict]:
    bundle = _bundle()
    k = k or business()["recommendations"]["top_k"]
    p = Product.objects.filter(id=product_id).first()
    index = {s: i for i, s in enumerate(bundle["skus"])}
    if not p or p.sku not in index:
        return []
    w = business()["recommendations"]["weights"]
    i = index[p.sku]
    score = w["collaborative"] * bundle["cf_sim"][i] + w["content"] * bundle["content_sim"][i]
    score[i] = -np.inf
    products = {x.sku: x for x in Product.objects.filter(sku__in=bundle["skus"])}
    out = []
    for j in np.argsort(-score)[: k * 2]:
        q = products.get(bundle["skus"][j])
        if q is None:
            continue
        reason = (f"Often bought together with {p.name}" if bundle["cf_sim"][i, j] * w["collaborative"]
                  >= bundle["content_sim"][i, j] * w["content"] else f"Similar to {p.name}")
        out.append({"product_id": q.id, "sku": q.sku, "name": q.name, "price": str(q.price),
                    "score": round(float(score[j]), 4), "reason": reason,
                    "image": q.primary_image.image.url if q.primary_image else None})
        if len(out) >= k:
            break
    return out
