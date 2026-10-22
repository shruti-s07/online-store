"""Extract training data from the store database (Django ORM -> pandas)."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
from django.utils import timezone

from backend.folder_one_core.catalog.models import Product
from backend.folder_one_core.orders.models import Order, OrderItem


def orders_frame() -> pd.DataFrame:
    rows = Order.objects.values("id", "user_id", "user__date_joined", "created_at", "status", "payment_method",
                                "address_match", "total", "fraud_confirmed")
    df = pd.DataFrame(list(rows)).rename(columns={"user__date_joined": "joined"})
    items = pd.DataFrame(list(OrderItem.objects.values("order_id", "quantity")))
    df["item_count"] = df["id"].map(items.groupby("order_id")["quantity"].sum()).fillna(0).astype(int)
    df["total"] = df["total"].astype(float)
    df = df.sort_values(["user_id", "created_at", "id"]).reset_index(drop=True)
    df["refused"] = (df["status"] == "DELIVERY_REFUSED").astype(int)
    df["past_refused"] = df.groupby("user_id")["refused"].cumsum() - df["refused"]
    df["prior_orders"] = df.groupby("user_id").cumcount()
    df["account_age_days"] = (df["created_at"] - df["joined"]).dt.total_seconds() / 86400
    df["hour"] = df["created_at"].dt.hour
    df["label"] = (df["fraud_confirmed"] | (df["status"] == "DELIVERY_REFUSED")).astype(int)
    return df.sort_values("created_at").reset_index(drop=True)


def daily_demand(end_date=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Units ordered per product per day (cancelled orders excluded), full date grid.
    Returns (demand matrix [date x sku], products frame). The last complete day is yesterday."""
    end_date = end_date or (timezone.now().date() - timedelta(days=1))
    rows = (OrderItem.objects.exclude(order__status="CANCELLED")
            .values("product__sku", "order__created_at", "quantity"))
    df = pd.DataFrame(list(rows))
    df["date"] = pd.to_datetime(df["order__created_at"]).dt.tz_convert("UTC").dt.date
    df = df[df["date"] <= end_date]
    table = df.pivot_table(index="date", columns="product__sku", values="quantity", aggfunc="sum", fill_value=0)
    idx = pd.date_range(min(table.index), end_date, freq="D").date
    products = pd.DataFrame(list(Product.objects.values("id", "sku", "name", "created_at")))
    table = table.reindex(index=idx, columns=products["sku"], fill_value=0).fillna(0)
    return table.astype(float), products


def interactions() -> pd.DataFrame:
    rows = (OrderItem.objects.exclude(order__status="CANCELLED")
            .values("order__user_id", "order_id", "order__created_at", "product__sku"))
    return pd.DataFrame(list(rows)).rename(columns={"order__user_id": "user_id", "order__created_at": "ts",
                                                    "product__sku": "sku", "order_id": "order_id"})


def product_text() -> pd.DataFrame:
    rows = Product.objects.values("sku", "name", "description", "brand", "category__name", "attributes")
    df = pd.DataFrame(list(rows))
    df["text"] = (df["name"] + " " + df["brand"] + " " + df["category__name"] + " " + df["category__name"] + " "
                  + df["description"])
    return df


def reviews_frame() -> pd.DataFrame:
    from backend.folder_two_services.reviews.models import Review
    rows = Review.objects.values("id", "title", "body", "rating", "created_at", "user__email", "product__sku")
    df = pd.DataFrame(list(rows))
    df["text"] = df["title"] + ". " + df["body"]
    df["label"] = np.select([df["rating"] >= 4, df["rating"] <= 2], ["positive", "negative"], "neutral")
    return df


def truth(name: str) -> pd.DataFrame | None:
    from ai import common
    path = common.DATA_DIR / f"truth_{name}.csv"
    return pd.read_csv(path) if path.exists() else None
