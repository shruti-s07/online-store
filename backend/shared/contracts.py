"""Data contracts passed between folder one (core) and folder two (services).

Folder one builds these plain objects; folder two must not import core models to
implement a hook, and core never imports folder two directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class CartLine:
    product_id: int
    sku: str
    name: str
    category_id: int
    unit_price: Decimal
    unit_cost: Decimal
    quantity: int

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass(frozen=True)
class CartSnapshot:
    user_id: int
    lines: tuple[CartLine, ...]
    discount_code: str | None = None

    @property
    def subtotal(self) -> Decimal:
        return sum((l.line_total for l in self.lines), Decimal("0"))

    @property
    def quantity(self) -> int:
        return sum(l.quantity for l in self.lines)


@dataclass(frozen=True)
class AppliedDiscount:
    rule_id: int
    name: str
    amount: Decimal


@dataclass(frozen=True)
class DiscountResult:
    amount: Decimal = Decimal("0")
    applied: tuple[AppliedDiscount, ...] = ()
    # Message for the customer, e.g. why a code was rejected
    message: str = ""
    code_valid: bool | None = None


@dataclass(frozen=True)
class OrderSnapshot:
    order_id: int
    user_id: int
    payment_method: str
    prepaid: bool
    total: Decimal
    item_count: int
    account_age_days: float
    address_match: bool
    past_refused_deliveries: int
    prior_orders: int
    hour_of_day: int


@dataclass(frozen=True)
class RiskResult:
    score: int  # 0..100
    level: str  # LOW / MEDIUM / HIGH
    reasons: tuple[str, ...] = ()
    model: str = ""
    extra: dict = field(default_factory=dict)
