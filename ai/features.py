"""Feature definitions shared by training (ai/train_*.py) and serving (backend services)."""
from __future__ import annotations

import math

from config.loader import business

FRAUD_FEATURES = ["cod", "log_account_age_days", "address_mismatch", "past_refused", "total_per_10k",
                  "night_order", "item_count", "log_prior_orders"]


def fraud_row(*, cod: bool, account_age_days: float, address_match: bool, past_refused: int, total: float,
              hour: int, item_count: int, prior_orders: int) -> list[float]:
    return [float(cod), math.log1p(max(0.0, account_age_days)), float(not address_match), float(past_refused),
            float(total) / 10000.0, float(is_night(hour)), float(item_count), math.log1p(prior_orders)]


def is_night(hour: int) -> bool:
    start, end = business()["risk"]["night_hours"]
    return start <= hour < end
