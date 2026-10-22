"""SnapCheck (received-item photo vs listing photo) and search by photo."""
from __future__ import annotations

import numpy as np
from PIL import Image

from ai.common import load_artifact
from ai.embedding import get_embedder
from backend.folder_one_core.accounts.models import notify_back_office
from backend.folder_one_core.catalog.models import Product
from config.loader import business

_index_cache: dict = {}


def thresholds() -> dict:
    """Calibrated thresholds from training if available for the active embedder, else config."""
    emb = get_embedder()
    art = load_artifact("snapcheck")
    if art and art.get("method") == emb.name:
        return {"match": art["match_threshold"], "mismatch": art["mismatch_threshold"], "source": "calibrated"}
    cfg = business()["snapcheck"]
    return {"match": cfg["match_threshold"], "mismatch": cfg["mismatch_threshold"], "source": "config"}


def _product_image(p: Product) -> Image.Image | None:
    img = p.primary_image
    if not img:
        return None
    with img.image.open("rb") as fh:
        return Image.open(fh).convert("RGB")


def product_index() -> tuple[list[int], np.ndarray]:
    """Embeddings of every product's primary image (cached; refreshed when images change)."""
    emb = get_embedder()
    products = list(Product.objects.prefetch_related("images"))
    key = (emb.name, tuple((p.id, p.primary_image.id if p.primary_image else None) for p in products))
    if _index_cache.get("key") != key:
        art = load_artifact("snapcheck")
        stored = art["embeddings"] if art and art.get("method") == emb.name else {}
        ids, vecs, todo = [], [], []
        for p in products:
            if p.primary_image is None:
                continue
            k = f"{p.sku}:{p.primary_image.image.name}"
            if k in stored:
                ids.append(p.id); vecs.append(stored[k])
            else:
                todo.append(p)
        if todo:
            imgs = [_product_image(p) for p in todo]
            for p, v in zip(todo, emb.embed(imgs)):
                ids.append(p.id); vecs.append(v)
        _index_cache.update(key=key, ids=ids, vecs=np.stack(vecs) if vecs else np.zeros((0, 1)))
    return _index_cache["ids"], _index_cache["vecs"]


def compare(upload: Image.Image, product: Product) -> dict:
    emb = get_embedder()
    listing = _product_image(product)
    if listing is None:
        return {"similarity": None, "verdict": "UNCERTAIN", "method": emb.name, "detail": "Listing has no photo"}
    a, b = emb.embed([upload, listing])
    sim = float(np.dot(a, b))
    t = thresholds()
    verdict = "MATCH" if sim >= t["match"] else ("MISMATCH" if sim < t["mismatch"] else "UNCERTAIN")
    return {"similarity": round(sim, 4), "verdict": verdict, "method": emb.name, "thresholds": t}


def search_by_photo(upload: Image.Image, k: int | None = None) -> dict:
    emb = get_embedder()
    k = k or business()["snapcheck"]["photo_search_top_k"]
    ids, vecs = product_index()
    if not ids:
        return {"method": emb.name, "results": []}
    q = emb.embed([upload])[0]
    sims = vecs @ q
    order = np.argsort(-sims)[:k]
    products = {p.id: p for p in Product.objects.filter(id__in=[ids[i] for i in order]).select_related("category")}
    from backend.folder_one_core.inventory.services import availability_map
    avail = availability_map(products.keys())
    return {"method": emb.name, "results": [
        {"product_id": ids[i], "name": products[ids[i]].name, "price": str(products[ids[i]].price),
         "available": avail[ids[i]]["available"],
         "category": products[ids[i]].category.name, "similarity": round(float(sims[i]), 4),
         "image": products[ids[i]].primary_image.image.url if products[ids[i]].primary_image else None}
        for i in order if ids[i] in products]}


def fast_track(check) -> None:
    notify_back_office("snapcheck_mismatch", f"SnapCheck mismatch on order #{check.order_item.order_id}",
                       f"Customer photo does not match '{check.order_item.name}' (similarity {check.similarity:.2f}).",
                       snapcheck_id=check.id, order_id=check.order_item.order_id)
