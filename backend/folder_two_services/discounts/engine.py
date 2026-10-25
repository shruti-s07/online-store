"""Discount rule engine. Rules are rows (DiscountRule) whose `conditions` and `action` are
plain JSON interpreted here; only the whitelisted keys below are understood.

conditions (all optional, all must hold):
  min_subtotal: number           min_quantity: int
  category_ids: [int]            product_ids: [int]   (rule then applies to matching lines only)
  first_order_only: bool
action:
  {"type": "percent", "value": 10}   or   {"type": "fixed", "value": 15}
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from backend.shared.contracts import AppliedDiscount, CartSnapshot, DiscountResult
from backend.shared.money import money

from .models import DiscountRule

CONDITION_KEYS = {"min_subtotal", "min_quantity", "category_ids", "product_ids", "first_order_only"}
ACTION_TYPES = {"percent", "fixed"}


def validate_rule_data(conditions: dict, action: dict) -> list[str]:
    errors = []
    unknown = set(conditions or {}) - CONDITION_KEYS
    if unknown:
        errors.append(f"Unknown condition(s): {', '.join(sorted(unknown))}")
    if not isinstance(action, dict) or action.get("type") not in ACTION_TYPES:
        errors.append("action.type must be 'percent' or 'fixed'")
    else:
        try:
            v = Decimal(str(action.get("value")))
        except Exception:
            v = Decimal("-1")
        if v <= 0 or (action["type"] == "percent" and v > 100):
            errors.append("action.value must be > 0 (and <= 100 for percent)")
    return errors


def live_rules():
    now = timezone.now()
    return (DiscountRule.objects.filter(status=DiscountRule.Status.APPROVED)
            .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
            .order_by("-priority", "id"))


def _eligible_lines(rule: DiscountRule, cart: CartSnapshot):
    c = rule.conditions or {}
    lines = list(cart.lines)
    if c.get("category_ids"):
        lines = [l for l in lines if l.category_id in set(c["category_ids"])]
    if c.get("product_ids"):
        lines = [l for l in lines if l.product_id in set(c["product_ids"])]
    return lines


def times_used(rule_id: int) -> int:
    """Usage is derived from the discount snapshot stored on each order."""
    from backend.folder_one_core.orders.models import Order
    from django.db import connection
    if connection.vendor == "postgresql":
        return Order.objects.filter(discounts__contains=[{"rule_id": rule_id}]).exclude(status="CANCELLED").count()
    return Order.objects.filter(discounts__icontains=f'"rule_id": {rule_id}').exclude(status="CANCELLED").count()


def _conditions_hold(rule: DiscountRule, cart: CartSnapshot) -> tuple[bool, str]:
    c = rule.conditions or {}
    if rule.max_uses is not None and times_used(rule.id) >= rule.max_uses:
        return False, "has reached its usage limit"
    if "min_subtotal" in c and cart.subtotal < Decimal(str(c["min_subtotal"])):
        return False, f"requires a subtotal of at least {c['min_subtotal']}"
    if "min_quantity" in c and cart.quantity < int(c["min_quantity"]):
        return False, f"requires at least {c['min_quantity']} items"
    if c.get("first_order_only"):
        from backend.folder_one_core.orders.models import Order
        if Order.objects.filter(user_id=cart.user_id).exists():
            return False, "is only valid on a first order"
    if not _eligible_lines(rule, cart):
        return False, "does not apply to the items in your cart"
    return True, ""


def _amount(rule: DiscountRule, cart: CartSnapshot) -> Decimal:
    base = sum((l.line_total for l in _eligible_lines(rule, cart)), Decimal("0"))
    a = rule.action
    value = Decimal(str(a["value"]))
    amount = base * value / 100 if a["type"] == "percent" else min(value, base)
    return money(amount)


def apply_discounts(cart: CartSnapshot) -> DiscountResult:
    """Real implementation of the checkout hook `apply_discounts(cart)`."""
    if not cart.lines:
        return DiscountResult()
    applied: list[AppliedDiscount] = []
    total = Decimal("0")
    code_valid, message = None, ""
    code = (cart.discount_code or "").upper() or None
    rules = list(live_rules())
    if code:
        match = [r for r in rules if (r.code or "").upper() == code]
        if not match:
            code_valid, message = False, f"Code {code} is not valid or has expired."
        else:
            ok, why = _conditions_hold(match[0], cart)
            code_valid, message = ok, ("" if ok else f"Code {code} {why}.")
    remaining = cart.subtotal
    exclusive_taken = False
    for r in rules:
        if r.code and (r.code or "").upper() != code:
            continue
        ok, _ = _conditions_hold(r, cart)
        if not ok or (exclusive_taken and not r.stackable):
            continue
        amt = min(_amount(r, cart), remaining)
        if amt <= 0:
            continue
        applied.append(AppliedDiscount(rule_id=r.id, name=r.name, amount=amt))
        total += amt
        remaining -= amt
        exclusive_taken = exclusive_taken or not r.stackable
    if code_valid and not message:
        message = f"Code {code} applied."
    return DiscountResult(amount=money(total), applied=tuple(applied), message=message, code_valid=code_valid)

