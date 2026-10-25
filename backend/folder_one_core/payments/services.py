import hashlib

from django.db import IntegrityError, transaction
from django.utils import timezone

from backend.shared.errors import DomainError
from backend.shared.payment_methods import cod_method
from backend.shared.order_states import SYSTEM, OrderStatus
from config.loader import business

from .gateway import gateway
from .models import Payment


def _fingerprint(order_id, method, token) -> str:
    return hashlib.sha256(f"{order_id}|{method}|{token}".encode()).hexdigest()


def pay(order_id: int, user, idempotency_key: str, method: str, token: str) -> Payment:
    """Charge an order exactly once per idempotency key.

    Replaying the same key returns the original Payment. Reusing a key with a different
    request is rejected. The order row is locked so concurrent attempts serialise.
    """
    from backend.folder_one_core.orders.models import Order
    from backend.folder_one_core.orders.services import transition

    if not idempotency_key:
        raise DomainError("Idempotency-Key header is required.", code="idempotency_key_required")
    if method not in business()["checkout"]["prepaid_methods"]:
        raise DomainError(f"{method} is not a prepaid method.", code="invalid_payment_method")
    fp = _fingerprint(order_id, method, token)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id, user=user)
        existing = Payment.objects.filter(user=user, idempotency_key=idempotency_key).first()
        if existing:
            if existing.request_fingerprint != fp:
                raise DomainError("Idempotency key was already used for a different request.",
                                  code="idempotency_conflict", status_code=422)
            return existing
        if order.status != OrderStatus.PENDING:
            raise DomainError(f"Order is {order.status}; it cannot be paid now.", code="not_payable", status_code=409)
        result = gateway.charge(order.total, token)
        try:
            with transaction.atomic():
                payment = Payment.objects.create(
                    order=order, user=user, idempotency_key=idempotency_key, method=method, amount=order.total,
                    status=Payment.Status.SUCCEEDED if result.success else Payment.Status.FAILED,
                    gateway_ref=result.reference, error_code=result.error_code, message=result.message,
                    request_fingerprint=fp)
        except IntegrityError:
            return Payment.objects.get(user=user, idempotency_key=idempotency_key)
        if result.success:
            order.payment_method = method
            order.save(update_fields=["payment_method", "updated_at"])
            transition(order, OrderStatus.PAID, actor=SYSTEM, note=f"Payment {result.reference}")
        return payment


def refund_all(order, note: str = "") -> list[Payment]:
    refunded = []
    for p in order.payments.filter(status=Payment.Status.SUCCEEDED):
        gateway.refund(p.gateway_ref, p.amount)
        p.status, p.refunded_at, p.message = Payment.Status.REFUNDED, timezone.now(), note[:200]
        p.save(update_fields=["status", "refunded_at", "message"])
        refunded.append(p)
    return refunded


def record_cash_collected(order) -> Payment:
    return Payment.objects.create(
        order=order, user=order.user, idempotency_key=f"cod-{order.id}", method=cod_method(), amount=order.total,
        status=Payment.Status.SUCCEEDED, gateway_ref=f"cod_{order.id}", message="Cash collected on delivery",
        request_fingerprint=_fingerprint(order.id, cod_method(), ""))
