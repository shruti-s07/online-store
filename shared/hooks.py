"""Checkout hooks resolved by dotted path from config/business.yaml (checkout.hooks).

Folder one ships these safe defaults; folder two provides the real implementations.
If a configured hook cannot be imported the stub is NOT silently used: startup fails.
"""
from __future__ import annotations

from functools import lru_cache
from importlib import import_module

from backend.shared.contracts import CartSnapshot, DiscountResult, OrderSnapshot, RiskResult
from config.loader import business


def default_apply_discounts(cart: CartSnapshot) -> DiscountResult:
    """Stub: no discounts."""
    return DiscountResult(code_valid=None if not cart.discount_code else False,
                          message="Discounts are not enabled" if cart.discount_code else "")


def default_score_order(order: OrderSnapshot) -> RiskResult:
    """Stub: every order is low risk."""
    return RiskResult(score=0, level="LOW", reasons=("risk scoring disabled",), model="stub")


def import_dotted(path: str):
    module, _, attr = path.rpartition(".")
    return getattr(import_module(module), attr)


@lru_cache(maxsize=None)
def get_hook(name: str):
    return import_dotted(business()["checkout"]["hooks"][name])


def apply_discounts(cart: CartSnapshot) -> DiscountResult:
    return get_hook("apply_discounts")(cart)


def score_order(order: OrderSnapshot) -> RiskResult:
    return get_hook("score_order")(order)
