"""Serving side of demand forecasting: reads the artifact written by ai/train_forecasting.py."""
from __future__ import annotations

import math
from datetime import date, timedelta

from ai.common import load_artifact, load_meta
from backend.folder_one_core.catalog.models import Product
from backend.folder_one_core.inventory.services import availability_map
from backend.folder_two_services.model_errors import ModelNotTrained
from config.loader import business


def _artifact() -> dict:
    art = load_artifact("forecasting")
    if art is None:
        raise ModelNotTrained("forecasting")
    return art


def horizon_days() -> int:
    f = business()["forecasting"]
    h = int(f["horizon_days"])
    return max(f["min_horizon_days"], min(f["max_horizon_days"], h))


def product_forecast(product_id: int) -> dict | None:
    art = _artifact()
    by_sku = art["products"]
    p = Product.all_objects.filter(id=product_id).first()
    if not p or p.sku not in by_sku:
        return None
    f = by_sku[p.sku]
    h = horizon_days()
    start = date.fromisoformat(art["forecast_start"])
    return {
        "product_id": p.id, "sku": p.sku, "name": p.name, "model": f["model"],
        "backtest": f["backtest"], "history": f["history_tail"], "history_start": f["history_tail_start"],
        "forecast": [{"date": (start + timedelta(days=i)).isoformat(), "units": round(v, 2)}
                     for i, v in enumerate(f["forecast"][:h])],
        "daily_mean": round(sum(f["forecast"][:h]) / h, 3),
        "residual_sd": f["residual_sd"],
        "trained_at": art["trained_at"],
    }


def daily_demand_map() -> dict[int, dict]:
    """{product_id: {"daily_mean", "residual_sd", "model"}} for every forecasted product."""
    art = _artifact()
    h = horizon_days()
    ids = dict(Product.objects.values_list("sku", "id"))
    out = {}
    for sku, f in art["products"].items():
        if sku in ids:
            out[ids[sku]] = {"daily_mean": sum(f["forecast"][:h]) / h, "residual_sd": f["residual_sd"],
                             "model": f["model"]}
    return out


def restock_suggestions(only_needed: bool = True) -> list[dict]:
    """reorder point = average daily demand x supplier lead time + safety stock."""
    cfg = business()["restock"]
    demand = daily_demand_map()
    products = list(Product.objects.select_related("category").filter(id__in=demand.keys()))
    avail = availability_map([p.id for p in products])
    rows = []
    for p in products:
        d = demand[p.id]
        lt = p.supplier_lead_time_days
        safety = max(cfg["safety_stock_min_units"], cfg["service_level_z"] * d["residual_sd"] * math.sqrt(lt))
        rop = d["daily_mean"] * lt + safety
        available = avail[p.id]["available"]
        order_qty = max(0, math.ceil(rop + d["daily_mean"] * cfg["review_period_days"] - available))
        needs = available <= rop
        if only_needed and not needs:
            continue
        rows.append({
            "product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category.name,
            "available": available, "avg_daily_demand": round(d["daily_mean"], 2), "lead_time_days": lt,
            "safety_stock": round(safety, 1), "reorder_point": round(rop, 1),
            "days_of_cover": round(available / d["daily_mean"], 1) if d["daily_mean"] > 0 else None,
            "suggested_order_qty": order_qty if needs else 0, "needs_reorder": needs, "model": d["model"],
        })
    rows.sort(key=lambda r: (not r["needs_reorder"], r["days_of_cover"] if r["days_of_cover"] is not None else 1e9))
    return rows


def model_summary() -> dict:
    meta = load_meta("forecasting") or {}
    return {"trained_at": meta.get("trained_at"), "metrics": meta.get("metrics", {}), "horizon_days": horizon_days()}
