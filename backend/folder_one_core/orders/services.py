"""Order lifecycle: atomic checkout, state machine transitions, OTP verification."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from backend.folder_one_core.accounts.models import Address, notify, notify_back_office
from backend.folder_one_core.cart.services import get_cart, snapshot
from backend.folder_one_core.catalog.models import Product
from backend.folder_one_core.inventory.models import StockMovement
from backend.folder_one_core.inventory.services import active_reserved, lock_inventory
from backend.folder_one_core.reservations.models import Reservation
from backend.folder_one_core.reservations.services import expire_stale
from backend.shared import hooks
from backend.shared.contracts import OrderSnapshot
from backend.shared.errors import DomainError, InvalidTransition, OutOfStock, ReservationExpired
from backend.shared.money import money
from backend.shared.payment_methods import is_cod, is_prepaid
from backend.shared.order_states import SHIPPED_STATES, SYSTEM, OrderStatus, can_transition
from backend.shared.roles import Role
from config.loader import business

from .models import Order, OrderItem, OrderStatusHistory


# --------------------------------------------------------------------------- transitions
def actor_of(user) -> str:
    return Role(user.role) if user is not None else SYSTEM


def transition(order: Order, to_status: str, actor=SYSTEM, user=None, note: str = "") -> Order:
    """Move `order` to `to_status` if the declarative table allows `actor` to; record history
    and apply side effects (restock, refunds, cash capture, notifications)."""
    from backend.folder_one_core.payments.services import record_cash_collected, refund_all

    to_status = OrderStatus(to_status)
    current = OrderStatus(order.status)
    if not can_transition(current, to_status, actor):
        raise InvalidTransition(f"{actor} cannot move an order from {current} to {to_status}.",
                                current=current.value, requested=to_status.value)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != current:  # changed concurrently
            raise InvalidTransition("Order status changed concurrently; reload and retry.", current=order.status)
        if to_status == OrderStatus.CANCELLED and current not in SHIPPED_STATES:
            _restock(order, StockMovement.Reason.CANCEL, user)
        elif to_status == OrderStatus.RETURNED:
            _restock(order, StockMovement.Reason.RETURN, user)
        if to_status in (OrderStatus.CANCELLED, OrderStatus.REFUNDED):
            refund_all(order, note or f"Order {to_status.value.lower()}")
        if to_status == OrderStatus.DELIVERED and is_cod(order.payment_method) and current == OrderStatus.SHIPPED:
            record_cash_collected(order)
        order.status = to_status.value
        order.save(update_fields=["status", "updated_at"])
        OrderStatusHistory.objects.create(order=order, from_status=current.value, to_status=to_status.value,
                                          actor=user, actor_label=str(actor), note=note[:300])
        notify(order.user, "order_status", f"Order #{order.id}: {to_status.value.replace('_', ' ').title()}",
               note or f"Your order is now {to_status.value.replace('_', ' ').lower()}.", order_id=order.id,
               status=to_status.value)
    return order


def _restock(order: Order, reason: str, user) -> None:
    items = list(order.items.all())
    inventory = lock_inventory([i.product_id for i in items])
    for it in items:
        inv = inventory[it.product_id]
        inv.on_hand += it.quantity
        inv.save(update_fields=["on_hand", "updated_at"])
    StockMovement.objects.bulk_create([StockMovement(product_id=i.product_id, delta=i.quantity, reason=reason,
                                                     reference=f"order:{order.id}", user=user) for i in items])


def advance_after_clearance(order: Order) -> Order:
    """After the order has PENDING status and passed risk checks: COD orders are confirmed;
    prepaid orders wait for payment."""
    if order.status == OrderStatus.PENDING and is_cod(order.payment_method):
        return transition(order, OrderStatus.CONFIRMED, SYSTEM, note="Cash on delivery confirmed")
    return order


# --------------------------------------------------------------------------- OTP
def _otp_hash(order_id: int, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{order_id}:{code}".encode(), hashlib.sha256).hexdigest()


def issue_otp(order: Order) -> None:
    cfg = business()["risk"]
    code = "".join(secrets.choice("0123456789") for _ in range(cfg["otp_length"]))
    order.otp_hash = _otp_hash(order.id, code)
    order.otp_expires_at = timezone.now() + timedelta(minutes=cfg["otp_ttl_minutes"])
    order.otp_attempts = 0
    order.save(update_fields=["otp_hash", "otp_expires_at", "otp_attempts", "updated_at"])
    # Simulated SMS: delivered to the in-app notification inbox.
    notify(order.user, "otp", f"Verification code for order #{order.id}",
           f"Your verification code is {code}. It expires in {cfg['otp_ttl_minutes']} minutes.",
           order_id=order.id)


def verify_otp(order: Order, code: str) -> Order:
    cfg = business()["risk"]
    if order.status != OrderStatus.VERIFICATION_REQUIRED:
        raise DomainError("This order does not need verification.", code="not_required", status_code=409)
    if not order.otp_expires_at or order.otp_expires_at < timezone.now():
        raise DomainError("The code has expired. Request a new one.", code="otp_expired", status_code=410)
    if hmac.compare_digest(order.otp_hash, _otp_hash(order.id, code.strip())):
        order.otp_hash = ""
        order.save(update_fields=["otp_hash", "updated_at"])
        order = transition(order, OrderStatus.PENDING, SYSTEM, note="Verification code accepted")
        return advance_after_clearance(order)
    order.otp_attempts += 1
    order.save(update_fields=["otp_attempts", "updated_at"])
    if order.otp_attempts >= cfg["otp_max_attempts"]:
        transition(order, OrderStatus.ON_HOLD, SYSTEM, note="Too many wrong verification codes")
        notify_back_office("order_on_hold", f"Order #{order.id} on hold",
                           "Too many wrong verification codes.", order_id=order.id)
        raise DomainError("Too many wrong codes. The order was sent to staff review.", code="otp_locked",
                          status_code=423)
    raise DomainError(f"Wrong code. {cfg['otp_max_attempts'] - order.otp_attempts} attempt(s) left.",
                      code="otp_invalid")


# --------------------------------------------------------------------------- checkout
def _address(user, address_id) -> Address:
    addr = Address.objects.filter(user=user, id=address_id).first()
    if not addr:
        raise DomainError("Address not found.", code="invalid_address")
    return addr


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def addresses_match(a: Address, b: Address) -> bool:
    return a.id == b.id or (_norm(a.postal_code) == _norm(b.postal_code) and _norm(a.country) == _norm(b.country))


def build_risk_snapshot(order: Order) -> OrderSnapshot:
    user = order.user
    prior = Order.objects.filter(user=user, created_at__lt=order.created_at)
    return OrderSnapshot(
        order_id=order.id, user_id=user.id, payment_method=order.payment_method,
        prepaid=is_prepaid(order.payment_method),
        total=order.total, item_count=sum(i.quantity for i in order.items.all()),
        account_age_days=max(0.0, (order.created_at - user.date_joined).total_seconds() / 86400),
        address_match=order.address_match,
        past_refused_deliveries=prior.filter(status=OrderStatus.DELIVERY_REFUSED).count(),
        prior_orders=prior.count(), hour_of_day=timezone.localtime(order.created_at).hour,
    )


def reserve_cart(user) -> Reservation:
    from backend.folder_one_core.reservations.services import reserve

    cart = get_cart(user)
    lines = {it.product_id: it.quantity for it in cart.items.all()}
    if not lines:
        raise DomainError("Your cart is empty.", code="empty_cart")
    return reserve(user, lines)


def checkout(user, *, shipping_address_id: int, billing_address_id: int | None, payment_method: str,
             idempotency_key: str, payment_token: str | None = None) -> tuple[Order, dict]:
    """Create an order from the user's cart atomically, then score risk and take payment.

    Returns (order, info) where info carries `next_action` and any payment error.
    """
    cfg = business()["checkout"]
    if not idempotency_key:
        raise DomainError("Idempotency-Key header is required.", code="idempotency_key_required")
    if payment_method not in cfg["payment_methods"]:
        raise DomainError(f"Unknown payment method {payment_method}.", code="invalid_payment_method")
    existing = Order.objects.filter(user=user, checkout_key=idempotency_key).first()
    if existing:
        return existing, {"next_action": next_action(existing), "replayed": True}

    shipping = _address(user, shipping_address_id)
    billing = _address(user, billing_address_id) if billing_address_id else (
        Address.objects.filter(user=user, is_default=True).first() or shipping)

    with transaction.atomic():
        cart = get_cart(user)
        items = list(cart.items.all())
        if not items:
            raise DomainError("Your cart is empty.", code="empty_cart")
        lines = {it.product_id: it.quantity for it in items}
        inventory = lock_inventory(lines.keys())
        expire_stale(user)
        reservation = (Reservation.objects.select_for_update().filter(user=user).order_by("-created_at").first())
        if reservation is None or reservation.status in (Reservation.Status.CONSUMED, Reservation.Status.RELEASED):
            reservation = None
        elif reservation.status == Reservation.Status.EXPIRED:
            raise ReservationExpired(
                f"Your reservation expired after {business()['reservations']['window_minutes']} minutes. "
                "Review your cart and check out again.")
        mine = {ri.product_id: ri.quantity for ri in reservation.items.all()} if reservation else {}
        held_by_others = active_reserved(lines.keys(), exclude_reservation_id=reservation.id if reservation else None)
        shortages = []
        for pid, qty in lines.items():
            inv = inventory.get(pid)
            free = (inv.on_hand if inv else 0) - held_by_others.get(pid, 0)
            if qty > free:
                shortages.append({"product_id": pid, "requested": qty, "available": max(0, free)})
        if shortages:
            raise OutOfStock("Some items are no longer available in the requested quantity.", shortages=shortages)

        # Server-side re-pricing from current product rows; the order keeps a price snapshot.
        products = {p.id: p for p in Product.objects.filter(id__in=lines.keys())}
        if len(products) != len(lines):
            raise DomainError("Some products are no longer sold.", code="product_unavailable")
        snap = snapshot(cart, products)
        disc = hooks.apply_discounts(snap)
        if snap.discount_code and disc.code_valid is False:
            raise DomainError(disc.message or "Discount code is not valid.", code="invalid_discount")
        subtotal = money(snap.subtotal)
        discount_total = min(money(disc.amount), subtotal)
        order = Order.objects.create(
            user=user, status=OrderStatus.PENDING.value, payment_method=payment_method, subtotal=subtotal,
            discount_total=discount_total, total=money(subtotal - discount_total),
            discount_code=snap.discount_code or "",
            discounts=[{"rule_id": d.rule_id, "name": d.name, "amount": str(money(d.amount))} for d in disc.applied],
            shipping_address=shipping.snapshot(), billing_address=billing.snapshot(),
            address_match=addresses_match(shipping, billing), checkout_key=idempotency_key)
        OrderItem.objects.bulk_create([
            OrderItem(order=order, product=products[l.product_id], sku=l.sku, name=l.name, unit_price=l.unit_price,
                      unit_cost=l.unit_cost, quantity=l.quantity, line_total=money(l.line_total))
            for l in snap.lines])
        for pid, qty in lines.items():
            inv = inventory[pid]
            inv.on_hand -= qty
            inv.save(update_fields=["on_hand", "updated_at"])
        StockMovement.objects.bulk_create([StockMovement(product_id=pid, delta=-qty, reason=StockMovement.Reason.SALE,
                                                         reference=f"order:{order.id}", user=user)
                                           for pid, qty in lines.items()])
        if reservation:
            reservation.status = Reservation.Status.CONSUMED
            reservation.save(update_fields=["status"])
        OrderStatusHistory.objects.create(order=order, from_status="", to_status=OrderStatus.PENDING.value,
                                          actor=user, actor_label=str(Role(user.role)), note="Order placed")
        cart.items.all().delete()
        cart.discount_code = ""
        cart.save(update_fields=["discount_code", "updated_at"])

        risk = hooks.score_order(build_risk_snapshot(order))
        order.risk_score, order.risk_level = risk.score, risk.level
        order.risk_reasons, order.risk_model = list(risk.reasons), risk.model
        order.save(update_fields=["risk_score", "risk_level", "risk_reasons", "risk_model", "updated_at"])
        if risk.level == "HIGH":
            order = transition(order, OrderStatus.ON_HOLD, SYSTEM, note=f"Risk score {risk.score}: staff review")
            notify_back_office("order_on_hold", f"Order #{order.id} on hold (risk {risk.score})",
                               "; ".join(risk.reasons), order_id=order.id)
        elif risk.level == "MEDIUM":
            order = transition(order, OrderStatus.VERIFICATION_REQUIRED, SYSTEM,
                               note=f"Risk score {risk.score}: verification code sent")
            issue_otp(order)

    info: dict = {}
    order.refresh_from_db()
    if order.status == OrderStatus.PENDING:
        if is_cod(payment_method):
            order = advance_after_clearance(order)
        elif payment_token:
            from backend.folder_one_core.payments.services import pay
            payment = pay(order.id, user, f"{idempotency_key}:payment", payment_method, payment_token)
            if payment.status != payment.Status.SUCCEEDED:
                info["payment_error"] = {"code": payment.error_code, "message": payment.message}
            order.refresh_from_db()
    info["next_action"] = next_action(order)
    return order, info


def next_action(order: Order) -> str:
    return {
        OrderStatus.PENDING: "pay",
        OrderStatus.VERIFICATION_REQUIRED: "verify_otp",
        OrderStatus.ON_HOLD: "await_review",
    }.get(OrderStatus(order.status), "none")

