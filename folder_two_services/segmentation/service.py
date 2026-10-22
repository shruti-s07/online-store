"""RFM + K-Means customer segmentation (serving + assignment)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from django.db import transaction
from django.db.models import Count, Max, Min, Sum
from django.utils import timezone

from ai.common import load_artifact
from backend.folder_one_core.accounts.models import User
from backend.folder_one_core.orders.models import Order
from backend.folder_two_services.model_errors import ModelNotTrained
from backend.shared.order_states import REVENUE_STATES
from backend.shared.roles import Role

from .models import CustomerSegment

RFM_COLUMNS = ["recency_days", "frequency", "monetary", "tenure_days", "avg_order_value"]
REVENUE = [s.value for s in REVENUE_STATES] + ["REFUNDED", "RETURNED", "RETURN_REQUESTED"]


def rfm_frame(as_of=None) -> pd.DataFrame:
    """One row per customer with at least one order. Tenure = days since first order."""
    as_of = as_of or timezone.now()
    rows = (Order.objects.filter(user__role=Role.CUSTOMER, status__in=REVENUE).values("user_id")
            .annotate(last=Max("created_at"), first=Min("created_at"), frequency=Count("id"), monetary=Sum("total")))
    df = pd.DataFrame(list(rows))
    if df.empty:
        return pd.DataFrame(columns=["user_id", *RFM_COLUMNS])
    df["recency_days"] = (as_of - df["last"]).dt.total_seconds() / 86400
    df["tenure_days"] = (as_of - df["first"]).dt.total_seconds() / 86400
    df["monetary"] = df["monetary"].astype(float)
    df["avg_order_value"] = df["monetary"] / df["frequency"]
    return df[["user_id", *RFM_COLUMNS]]


def transform(df: pd.DataFrame) -> np.ndarray:
    """Log-scale the skewed RFM features (same transform used in training)."""
    x = df[RFM_COLUMNS].astype(float).to_numpy().copy()
    return np.log1p(np.clip(x, 0, None))


def assign_segments() -> dict:
    bundle = load_artifact("segmentation")
    if bundle is None:
        raise ModelNotTrained("segmentation")
    df = rfm_frame()
    if df.empty:
        return {}
    z = bundle["scaler"].transform(transform(df))
    clusters = bundle["kmeans"].predict(z)
    labels = [bundle["cluster_labels"][int(c)] for c in clusters]
    now = timezone.now()
    with transaction.atomic():
        CustomerSegment.objects.all().delete()
        CustomerSegment.objects.bulk_create([
            CustomerSegment(user_id=int(r.user_id), segment=l, cluster=int(c), recency_days=float(r.recency_days),
                            frequency=int(r.frequency), monetary=round(float(r.monetary), 2),
                            tenure_days=float(r.tenure_days), computed_at=now)
            for r, l, c in zip(df.itertuples(), labels, clusters)], batch_size=2000)
    return pd.Series(labels).value_counts().to_dict()


def customers_without_orders() -> int:
    return User.objects.filter(role=Role.CUSTOMER).exclude(id__in=CustomerSegment.objects.values("user_id")).count()
