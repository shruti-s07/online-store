"""Discount suggestions for slow movers.

1. Slow mover = high stock, low forecast demand, many days of cover (thresholds in config).
2. Price sensitivity (elasticity) per category is estimated from past promotions in the DB:
   uplift = units/day during the promotion vs. the baseline_days before it,
   elasticity = ln(uplift) / -ln(1 - discount); the median over promotions is used.
3. The discount needed to bring days of cover to the target is
   d = 1 - (target_daily / forecast_daily) ** (-1 / elasticity), capped so that the price never
   falls below cost * (1 + min_margin), rounded down to the configured step.
4. The proposal is saved as a DRAFT rule; an Admin approves or rejects it.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from backend.folder_one_core.catalog.models import Category, Product
from backend.folder_one_core.inventory.services import availability_map
from backend.folder_one_core.orders.models import OrderItem
from backend.folder_two_services.forecasting.service import daily_demand_map
from config.loader import business

from .models import DiscountRule, PastPromotion



def _units(category_id: int, start, end) -> float:
    lo = datetime.combine(start, time.min, tzinfo=dt_timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=dt_timezone.utc)
    total = (OrderItem.objects.filter(product__category_id=category_id, order__created_at__gte=lo,
                                      order__created_at__lt=hi)
             .exclude(order__status="CANCELLED").aggregate(u=Sum("quantity"))["u"]) or 0
    return float(total)


def estimate_elasticity(category: Category) -> dict:
    cfg = business()["discounts"]
    promos = list(PastPromotion.objects.filter(category=category))
    other = list(PastPromotion.objects.filter(category=category).values_list("starts_on", "ends_on"))
    estimates = []
    for pr in promos:
        days = (pr.ends_on - pr.starts_on).days + 1
        b_end = pr.starts_on - timedelta(days=1)
        baseline_days = cfg["baseline_days"]
        b_start = b_end - timedelta(days=baseline_days - 1)
        if any(s <= b_end and e >= b_start for s, e in other if (s, e) != (pr.starts_on, pr.ends_on)):
            continue  # baseline window contaminated by another promotion
        base = _units(category.id, b_start, b_end) / baseline_days
        promo = _units(category.id, pr.starts_on, pr.ends_on) / days
        d = float(pr.discount_pct)
        if base > 0 and promo > 0 and 0 < d < 1:
            estimates.append(math.log(promo / base) / -math.log(1 - d))
    if len(estimates) >= cfg["min_promotions_for_estimate"]:
        return {"elasticity": round(max(0.1, statistics.median(estimates)), 3), "n_promotions": len(estimates),
                "method": "median of past promotions"}
    return {"elasticity": cfg["default_price_elasticity"], "n_promotions": len(estimates),
            "method": "configured default (not enough past promotions)"}


def max_discount_for_margin(price: Decimal, cost: Decimal) -> float:
    m = business()["discounts"]["min_margin"]
    return max(0.0, 1 - float(cost) * (1 + m) / float(price))


def analyse_slow_movers() -> list[dict]:
    cfg = business()["discounts"]
    sm = cfg["slow_mover"]
    demand = daily_demand_map()
    products = list(Product.objects.select_related("category").filter(id__in=demand.keys()))
    avail = availability_map([p.id for p in products])
    elasticity = {}
    rows = []
    for p in products:
        daily = max(demand[p.id]["daily_mean"], 1e-3)
        stock = avail[p.id]["on_hand"]
        cover = stock / daily
        if not (stock >= sm["min_stock"] and cover >= sm["min_days_of_cover"] and daily <= sm["max_daily_demand"]):
            continue
        if p.category_id not in elasticity:
            elasticity[p.category_id] = estimate_elasticity(p.category)
        el = elasticity[p.category_id]
        target_daily = stock / cfg["target_days_of_cover"]
        needed = 1 - (target_daily / daily) ** (-1 / el["elasticity"]) if target_daily > daily else 0.0
        margin_cap = max_discount_for_margin(p.price, p.cost)
        step = cfg["discount_step"]
        proposed = math.floor(min(needed, margin_cap, cfg["max_discount"]) / step + 1e-9) * step
        uplift = (1 - proposed) ** (-el["elasticity"]) if proposed > 0 else 1.0
        rows.append({
            "product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category.name,
            "price": str(p.price), "cost": str(p.cost), "stock": stock, "forecast_daily": round(daily, 3),
            "days_of_cover": round(cover, 1), "elasticity": el, "needed_discount": round(needed, 3),
            "margin_cap": round(margin_cap, 3), "proposed_discount": round(proposed, 2),
            "expected_daily_after": round(daily * uplift, 3),
            "expected_days_of_cover_after": round(stock / (daily * uplift), 1),
            "new_price": str((p.price * Decimal(str(1 - proposed))).quantize(Decimal("0.01"))),
            "viable": proposed >= cfg["min_discount"],
            "reason": "" if proposed >= cfg["min_discount"] else (
                "minimum margin leaves no room for a discount" if margin_cap < cfg["min_discount"]
                else "demand response too small"),
        })
    rows.sort(key=lambda r: -r["days_of_cover"])
    return rows


def create_drafts(user=None) -> list[DiscountRule]:
    cfg = business()["discounts"]
    created = []
    existing = set()
    for r in DiscountRule.objects.filter(source=DiscountRule.Source.SUGGESTED,
                                         status__in=[DiscountRule.Status.DRAFT, DiscountRule.Status.APPROVED]):
        if r.ends_at is None or r.ends_at > timezone.now():
            existing.update(r.conditions.get("product_ids", []))
    for row in analyse_slow_movers():
        if not row["viable"] or row["product_id"] in existing:
            continue
        pct = round(row["proposed_discount"] * 100)
        created.append(DiscountRule.objects.create(
            name=f"Clearance {pct}%: {row['name']}", code=None, conditions={"product_ids": [row["product_id"]]},
            action={"type": "percent", "value": pct}, status=DiscountRule.Status.DRAFT,
            source=DiscountRule.Source.SUGGESTED, ends_at=timezone.now() + timedelta(days=cfg["suggestion_valid_days"]),
            rationale=row, created_by=user))
    return created
