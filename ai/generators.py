"""Synthetic world generator.

Produces a reproducible e-commerce history with learnable structure plus noise:
- customer segments with different purchase rates, price affinity, category taste and churn
- weekly, monthly (per category) and festival demand peaks plus a yearly trend
- past promotions whose uplift follows a per-category price elasticity
- fraud driven by a hidden logistic risk function plus Gaussian noise
- reviews whose rating follows latent product quality and whose text sentiment follows the
  rating (with label noise), plus injected fake-review campaigns

All parameters come from config/ml.yaml and config/categories.yaml. The hidden ground truth
(segments, fraud logit, elasticities, fake flags) is returned separately and is only used to
evaluate models, never to serve predictions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from config import loader


@dataclass
class World:
    products: pd.DataFrame
    customers: pd.DataFrame
    orders: pd.DataFrame
    items: pd.DataFrame
    promotions: pd.DataFrame
    reviews: pd.DataFrame
    stock: pd.Series


def _festival_multiplier(day: date, festivals: list[dict]) -> float:
    m = 1.0
    for f in festivals:
        start = date(day.year, f["month"], f["day"])
        if start <= day < start + timedelta(days=f["days"]):
            m *= f["multiplier"]
    return m


def festival_flag(day: date, festivals: list[dict]) -> int:
    return int(_festival_multiplier(day, festivals) > 1.0)


def _retail_price(raw: float) -> float:
    """Round to an Indian shelf price: ...49 / ...99 endings (₹249, ₹1,299, ₹14,999)."""
    if raw < 1000:
        step = 50
    elif raw < 10000:
        step = 100
    else:
        step = 1000
    return float(max(step, round(raw / step) * step) - 1)


def _address(rng: np.random.Generator, places: dict) -> dict:
    """A plausible Indian address: real locality with its PIN code, synthetic flat/building/road."""
    city = places["cities"][rng.integers(len(places["cities"]))]
    locality, pin = city["localities"][rng.integers(len(city["localities"]))]
    building = places["building_names"][rng.integers(len(places["building_names"]))]
    road = places["road_names"][rng.integers(len(places["road_names"]))]
    flat = f"{rng.choice(['Flat', 'House No.'])} {int(rng.integers(1, 20))}{int(rng.integers(1, 15)):02d}"
    return {"street": f"{flat}, {building}", "street2": f"{road}, {locality}", "city": city["city"],
            "state": city["state"], "postal": pin}


def _mobile(rng: np.random.Generator, places: dict) -> str:
    first = places["mobile_first_digits"][rng.integers(len(places["mobile_first_digits"]))]
    rest = "".join(str(d) for d in rng.integers(0, 10, size=9))
    digits = first + rest
    return f"{places['phone_country_code']} {digits[:5]} {digits[5:]}"


def make_products(rng: np.random.Generator, cfg: dict, cats: list[dict]) -> pd.DataFrame:
    rows = []
    n_per = cfg["synthetic"]["products_per_category"]
    pop_sigma = cfg["synthetic"]["product_popularity_sigma"]
    for ci, cat in enumerate(cats):
        combos = [(b, a, n) for n in cat["nouns"] for b in cat["brands"] for a in cat["adjectives"]]
        picks = rng.choice(len(combos), size=n_per, replace=False)
        lo, hi = cat["price_range"]
        for k, pi in enumerate(picks):
            brand, adj, n = combos[pi]
            noun = n["name"]
            plo, phi = n.get("price", (lo, hi))
            price = _retail_price(float(np.exp(rng.uniform(np.log(plo), np.log(phi)))))
            cost = round(price * rng.uniform(*cat["cost_ratio_range"]), 2)
            rows.append({
                "sku": f"{cat['slug'][:3].upper()}-{ci + 1}{k + 1:03d}",
                "name": f"{brand} {adj} {noun}",
                "brand": brand,
                "noun": noun,
                "icon": n["icon"],
                "category_slug": cat["slug"],
                "category_index": ci,
                "price": price,
                "cost": cost,
                "lead_time": int(rng.integers(cat["lead_time_days"][0], cat["lead_time_days"][1] + 1)),
                "popularity": float(rng.lognormal(0, pop_sigma)),
                "quality": float(rng.normal(0, cfg["synthetic"]["reviews"]["quality_sd"])),
                "description": f"{adj} {noun.lower()} from {brand}. {cat['blurb']}",
                "color_seed": int(rng.integers(0, 2**31 - 1)),
            })
    df = pd.DataFrame(rows)
    df["log_price_z"] = (np.log(df["price"]) - np.log(df["price"]).mean()) / np.log(df["price"]).std()
    return df


def make_customers(rng: np.random.Generator, cfg: dict, faker, today: date, places: dict) -> pd.DataFrame:
    syn = cfg["synthetic"]
    segs = syn["segments"]
    names = list(segs)
    shares = np.array([segs[n]["share"] for n in names], dtype=float)
    shares /= shares.sum()
    n = syn["n_customers"]
    n_fraud = int(round(n * syn["fraudster_share"]))
    rows = []
    for i in range(n):
        fraudster = i >= n - n_fraud
        seg = "fraudster" if fraudster else names[rng.choice(len(names), p=shares)]
        p = syn["fraudster"] if fraudster else segs[seg]
        joined_ago = int(rng.integers(p["joined_days_ago"][0], p["joined_days_ago"][1] + 1))
        churn_ago = int(rng.integers(*p["churned_days_ago"])) if "churned_days_ago" in p else None
        first = places["first_names"][rng.integers(len(places["first_names"]))]
        last = places["last_names"][rng.integers(len(places["last_names"]))]
        home, alt = _address(rng, places), _address(rng, places)
        rows.append({
            "segment": seg,
            "fraudster": fraudster,
            "first_name": first, "last_name": last,
            "email": f"{first.lower()}.{last.lower()}{i}@example.com".replace("'", "").replace(" ", ""),
            "joined": today - timedelta(days=joined_ago),
            "churn": (today - timedelta(days=churn_ago)) if churn_ago else None,
            "rate": p["rate"],
            "rate_after_churn": p.get("rate_after_churn", p["rate"]),
            "price_affinity": p.get("price_affinity", 0.0),
            "qty_mean": p.get("qty_mean", 1.0),
            "cod_prob": p["cod_prob"],
            "mismatch_prob": p.get("address_mismatch_prob", syn["address_mismatch_prob"]),
            "night_prob": p.get("night_order_prob", syn["night_order_prob"]),
            "city": home["city"], "street": home["street"], "street2": home["street2"], "postal": home["postal"],
            "state": home["state"], "alt_city": alt["city"], "alt_street": alt["street"],
            "alt_street2": alt["street2"], "alt_state": alt["state"], "alt_postal": alt["postal"],
            "phone": _mobile(rng, places),
        })
    return pd.DataFrame(rows)


def make_promotions(rng, cfg, cats, start: date, end: date) -> pd.DataFrame:
    pc = cfg["synthetic"]["promotions"]
    rows = []
    lo_margin, hi_margin = pc["edge_margin_days"]
    span = (end - start).days - lo_margin - hi_margin
    for _ in range(pc["count"]):
        cat = cats[rng.integers(len(cats))]["slug"]
        s = start + timedelta(days=int(rng.integers(lo_margin, span)))
        dur = int(rng.integers(pc["duration_days"][0], pc["duration_days"][1] + 1))
        disc = float(rng.choice(pc["discounts"]))
        el = max(pc["min_elasticity"], pc["elasticity"][cat] + rng.normal(0, pc["elasticity_noise_sd"]))
        rows.append({"category_slug": cat, "start": s, "end": s + timedelta(days=dur - 1), "discount": disc,
                     "true_elasticity": el, "name": f"{cat.replace('-', ' ').title()} sale {int(disc * 100)}%"})
    return pd.DataFrame(rows).sort_values("start").reset_index(drop=True)


def generate_world(today: date | None = None, *, scale: float = 1.0, seed: int | None = None) -> World:
    """Build the full synthetic history ending at `today`. `scale` shrinks it for tests."""
    from faker import Faker

    cfg = loader.ml()
    cats = loader.categories()
    syn = cfg["synthetic"]
    seed = cfg["random_seed"] if seed is None else seed
    rng = np.random.default_rng(seed)
    faker = Faker("en_IN")
    Faker.seed(seed)
    today = today or datetime.now(timezone.utc).date()
    if scale != 1.0:
        cfg = {**cfg, "synthetic": {**syn, "n_customers": max(30, int(syn["n_customers"] * scale)),
                                    "products_per_category": max(3, int(syn["products_per_category"] * scale)),
                                    "base_orders_per_day": max(4, syn["base_orders_per_day"] * scale)}}
        syn = cfg["synthetic"]

    products = make_products(rng, cfg, cats)
    customers = make_customers(rng, cfg, faker, today, loader.india())
    n_days = syn["history_days"]
    # History ends yesterday so no generated order or review lies in the future
    start = today - timedelta(days=n_days)
    promotions = make_promotions(rng, cfg, cats, start, today)

    n_p = len(products)
    cat_idx = products["category_index"].to_numpy()
    season = np.array([c["season"] for c in cats])  # (n_cat, 12)
    slugs = [c["slug"] for c in cats]
    seg_names = list(syn["segments"]) + ["fraudster"]
    seg_aff = syn["segment_category_affinity"]
    # Static per-segment product weights: popularity x category taste x price affinity
    seg_weights = {}
    for seg in seg_names:
        aff = np.array([seg_aff.get(seg, {}).get(s, 1.0) for s in slugs])[cat_idx]
        pa = syn["segments"].get(seg, {}).get("price_affinity", 0.0)
        seg_weights[seg] = products["popularity"].to_numpy() * aff * np.exp(pa * products["log_price_z"].to_numpy())

    fl = syn["fraud_logit"]
    night_hours = loader.business()["risk"]["night_hours"]
    weekly = np.array(syn["weekly_profile"])
    festivals = syn["festivals"]
    taste = rng.dirichlet(np.full(len(cats), syn["customer_taste_concentration"]), size=len(customers)) * len(cats)
    joined = pd.to_datetime(customers["joined"]).dt.date.to_numpy()
    churn = customers["churn"].to_numpy()
    seg_arr = customers["segment"].to_numpy()
    refused = np.zeros(len(customers), dtype=int)
    prices = products["price"].to_numpy()
    costs = products["cost"].to_numpy()

    orders, items = [], []
    for d in range(n_days):
        day = start + timedelta(days=d)
        # Day-specific product multipliers: category season; promotions lower prices and add demand below
        day_mult = season[cat_idx, day.month - 1].copy()
        promo_disc = np.zeros(n_p)
        cat_uplift = {}
        for _, pr in promotions[(promotions["start"] <= day) & (promotions["end"] >= day)].iterrows():
            mask = products["category_slug"].to_numpy() == pr["category_slug"]
            promo_disc[mask] = pr["discount"]
            cat_uplift[pr["category_slug"]] = (1 - pr["discount"]) ** (-pr["true_elasticity"])
        lam = (syn["base_orders_per_day"] * weekly[day.weekday()] * _festival_multiplier(day, festivals)
               * (1 + syn["yearly_trend"] * d / 365.0))
        lam = rng.gamma(syn["daily_noise_shape"], lam / syn["daily_noise_shape"])
        n_orders = rng.poisson(lam)
        if n_orders == 0:
            continue
        active = joined <= day
        rate = np.where([c is not None and day >= c for c in churn], customers["rate_after_churn"], customers["rate"])
        w = np.where(active, rate, 0.0)
        if w.sum() == 0:
            continue
        buyers = [(int(b), None) for b in rng.choice(len(customers), size=n_orders, p=w / w.sum())]
        n_base = len(orders)
        def place(b, only_cat):
            c = customers.iloc[b]
            pw = seg_weights[seg_arr[b]] * day_mult * taste[b][cat_idx]
            if only_cat is not None:
                pw = pw * (products["category_slug"].to_numpy() == only_cat)
            k = 1 if only_cat is not None else 1 + rng.poisson(max(0.0, syn["items_per_order_mean"] - 1))
            chosen = rng.choice(n_p, size=min(k, int((pw > 0).sum())), replace=False, p=pw / pw.sum())
            night = rng.random() < c["night_prob"]
            hour = int(rng.integers(*night_hours)) if night else int(rng.integers(*syn["day_hours"]))
            ts = datetime(day.year, day.month, day.day, hour, int(rng.integers(0, 60)), tzinfo=timezone.utc)
            oid = len(orders)
            total = 0.0
            for pidx in chosen:
                qty = 1 + rng.poisson(max(0.0, c["qty_mean"] - 1))
                unit = round(prices[pidx] * (1 - promo_disc[pidx]), 2)
                total += unit * qty
                items.append({"order": oid, "product": int(pidx), "qty": int(qty), "unit_price": unit,
                              "unit_cost": costs[pidx]})
            cod = rng.random() < c["cod_prob"]
            mismatch = rng.random() < c["mismatch_prob"]
            age = max(0.0, (day - joined[b]).days + hour / 24)
            logit = (fl["intercept"] + fl["cod"] * cod + fl["log_account_age_days"] * np.log1p(age)
                     + fl["address_mismatch"] * mismatch + fl["past_refused"] * refused[b]
                     + fl["total_per_10k"] * total / 10000 + fl["night_order"] * night
                     + rng.normal(0, fl["noise_sd"]))
            fraud = rng.random() < 1 / (1 + np.exp(-logit))
            if fraud and cod:
                refused[b] += 1
            orders.append({"customer": int(b), "created_at": ts, "cod": bool(cod), "address_match": not mismatch,
                           "night": bool(night), "total": round(total, 2), "fraud": bool(fraud),
                           "account_age_days": age, "hour": hour, "promo": bool(promo_disc[chosen].max() > 0)})

        for b, _ in buyers:
            place(b, None)
        # Promotions add demand: extra single-category orders worth base_units x (uplift - 1)
        if cat_uplift:
            day_items = [it for it in items if it["order"] >= n_base]
            for slug, up in cat_uplift.items():
                base_units = sum(1 for it in day_items if products.iloc[it["product"]].category_slug == slug)
                extra = rng.poisson(base_units * (up - 1))
                ci = [c["slug"] for c in cats].index(slug)
                wc = w * taste[:, ci]
                if extra and wc.sum() > 0:
                    for b in rng.choice(len(customers), size=extra, p=wc / wc.sum()):
                        place(int(b), slug)

    orders = pd.DataFrame(orders)
    items = pd.DataFrame(items)
    orders["status"] = _final_statuses(rng, syn, orders, today)
    reviews = _make_reviews(rng, cfg, products, customers, orders, items, today, faker)
    stock = _end_stock(rng, syn, products, orders, items, today)
    return World(products, customers, orders, items, promotions, reviews, stock)


def _final_statuses(rng, syn, orders: pd.DataFrame, today: date) -> list[str]:
    out = []
    for o in orders.itertuples():
        age_days = (today - o.created_at.date()).days
        if o.fraud:
            out.append("DELIVERY_REFUSED" if o.cod else "REFUNDED")
        elif age_days < syn["open_order_days"]:
            stages = ["CONFIRMED" if o.cod else "PAID", "PROCESSING", "SHIPPED"]
            out.append(stages[min(len(stages) - 1, int(rng.integers(0, max(1, age_days + 1))))])
        elif rng.random() < syn["cancel_prob"]:
            out.append("CANCELLED")
        elif rng.random() < syn["return_prob"]:
            out.append("RETURNED")
        else:
            out.append("DELIVERED")
    return out


def _make_reviews(rng, cfg, products, customers, orders, items, today, faker) -> pd.DataFrame:
    rc = cfg["synthetic"]["reviews"]
    tt = loader.text_templates()
    cats = {c["slug"]: c for c in loader.categories()}
    delivered = orders.index[orders["status"].isin(["DELIVERED", "RETURNED"])]
    cand = items[items["order"].isin(delivered)]
    cand = cand.sample(frac=rc["review_prob"], random_state=int(rng.integers(1 << 30)))
    rows, seen = [], set()
    for it in cand.itertuples():
        o = orders.loc[it.order]
        key = (int(o.customer), it.product)
        if key in seen:
            continue
        seen.add(key)
        prod = products.iloc[it.product]
        rating = int(np.clip(round(rc["rating_base"] + rc["quality_weight"] * prod.quality
                                   + rng.normal(0, rc["rating_noise_sd"])), 1, 5))
        sentiment = "positive" if rating >= 4 else ("negative" if rating <= 2 else "neutral")
        text_sent = sentiment
        if rng.random() < rc["text_label_noise"]:
            text_sent = {"positive": "negative", "negative": "positive", "neutral": "positive"}[sentiment]
        title, body = review_text(rng, tt["review"], cats[prod.category_slug]["aspects"], text_sent)
        lo, hi = rc["delay_days"]
        when = o.created_at + timedelta(days=int(rng.integers(lo, hi)), hours=int(rng.integers(0, 12)))
        if when.date() >= today:
            continue
        rows.append({"product": it.product, "customer": int(o.customer), "order": int(it.order), "rating": rating,
                     "title": title, "body": body, "created_at": when, "fake": False, "sentiment": sentiment})
    # Fake-review campaigns: brand-new accounts posting near-duplicate 5-star texts in a burst
    fake = tt["fake"]
    lo, hi = rc["fake_reviews_per_campaign"]
    for _ in range(rc["fake_campaigns"]):
        prod = int(rng.integers(len(products)))
        burst_start = datetime.combine(today - timedelta(days=int(rng.integers(*rc["fake_campaign_days_ago"]))),
                                       datetime.min.time(),
                                       tzinfo=timezone.utc)
        for _ in range(int(rng.integers(lo, hi + 1))):
            body = str(rng.choice(fake["bodies"]))
            rows.append({"product": prod, "customer": None, "order": None, "rating": 5,
                         "title": str(rng.choice(fake["titles"])), "body": body,
                         "created_at": burst_start + timedelta(hours=int(rng.integers(0, rc["fake_burst_hours"]))),
                         "fake": True,
                         "sentiment": "positive",
                         "fake_email": f"{faker.user_name()}{int(rng.integers(1e6))}@mailinator.example"})
    return pd.DataFrame(rows)


def review_text(rng, tpl: dict, aspects: list[str], sentiment: str) -> tuple[str, str]:
    a1, a2 = rng.choice(aspects, 2, replace=False)
    pos, neg = tpl["positive_adjectives"], tpl["negative_adjectives"]
    if sentiment == "positive":
        body = (f"The {a1} is {rng.choice(pos)} and the {a2} is {rng.choice(pos)}. "
                f"{rng.choice(tpl['positive_sentences'])}")
        title = rng.choice(tpl["positive_titles"])
    elif sentiment == "negative":
        body = (f"The {a1} is {rng.choice(neg)} and the {a2} feels {rng.choice(neg)}. "
                f"{rng.choice(tpl['negative_sentences'])}")
        title = rng.choice(tpl["negative_titles"])
    else:
        body = (f"The {a1} is {rng.choice(pos)} but the {a2} is {rng.choice(neg)}. "
                f"{rng.choice(tpl['neutral_sentences'])}")
        title = rng.choice(tpl["neutral_titles"])
    return str(title), body


def _end_stock(rng, syn, products, orders, items, today) -> pd.Series:
    ref = syn["stock_reference_days"]
    recent = orders.index[orders["created_at"].dt.date > today - timedelta(days=ref)]
    daily = items[items["order"].isin(recent)].groupby("product")["qty"].sum() / float(ref)
    daily = daily.reindex(range(len(products)), fill_value=0.0)
    days = rng.uniform(*syn["stock_days_range"], size=len(products))
    # Overstock some of the least popular products: these become slow movers
    n_over = int(round(len(products) * syn["overstock_share"]))
    slow = np.argsort(products["popularity"].to_numpy())[: n_over * syn["overstock_pool_factor"]]
    over = rng.choice(slow, size=n_over, replace=False)
    days[over] = rng.uniform(*syn["overstock_days_range"], size=n_over)
    stock = np.ceil(np.maximum(daily.to_numpy(), syn["min_daily_demand_for_stock"]) * days).astype(int)
    return pd.Series(stock, name="on_hand")
