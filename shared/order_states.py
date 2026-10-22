"""The one and only definition of order statuses and allowed transitions.

TRANSITIONS[from_status][to_status] = set of actors allowed to perform the move.
An actor is a Role or SYSTEM (checkout, payment gateway, risk engine, jobs).
"""
from enum import StrEnum

from backend.shared.roles import Role


class OrderStatus(StrEnum):
    PENDING = "PENDING"                      # created, waiting for payment
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"  # medium risk: OTP needed
    ON_HOLD = "ON_HOLD"                      # high risk: staff review
    CONFIRMED = "CONFIRMED"                  # cash on delivery accepted
    PAID = "PAID"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    DELIVERY_REFUSED = "DELIVERY_REFUSED"
    CANCELLED = "CANCELLED"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURNED = "RETURNED"
    REFUNDED = "REFUNDED"


SYSTEM = "SYSTEM"
S = OrderStatus
C, ST, AD = Role.CUSTOMER, Role.STAFF, Role.ADMIN
BACK = {ST, AD}

TRANSITIONS: dict[OrderStatus, dict[OrderStatus, set]] = {
    S.PENDING: {
        S.PAID: {SYSTEM},
        S.CONFIRMED: {SYSTEM},
        S.VERIFICATION_REQUIRED: {SYSTEM},
        S.ON_HOLD: {SYSTEM},
        S.CANCELLED: {C, ST, AD, SYSTEM},
    },
    S.VERIFICATION_REQUIRED: {
        S.PENDING: {SYSTEM},          # OTP verified
        S.ON_HOLD: {SYSTEM},          # too many wrong OTPs
        S.CANCELLED: {C, ST, AD, SYSTEM},
    },
    S.ON_HOLD: {
        S.PENDING: BACK,              # staff approved after review
        S.CANCELLED: BACK,
    },
    S.CONFIRMED: {S.PROCESSING: BACK, S.CANCELLED: {C, ST, AD}},
    S.PAID: {S.PROCESSING: BACK, S.CANCELLED: {C, ST, AD}},
    S.PROCESSING: {S.SHIPPED: BACK, S.CANCELLED: BACK},
    S.SHIPPED: {S.DELIVERED: BACK, S.DELIVERY_REFUSED: BACK},
    S.DELIVERED: {S.RETURN_REQUESTED: {C}},
    S.RETURN_REQUESTED: {S.RETURNED: BACK, S.DELIVERED: BACK},  # accept / reject return
    S.RETURNED: {S.REFUNDED: BACK},
    S.DELIVERY_REFUSED: {},
    S.CANCELLED: {},
    S.REFUNDED: {},
}

# Statuses whose stock has left the warehouse (cancelling them does not restock)
SHIPPED_STATES = frozenset({S.SHIPPED, S.DELIVERED, S.RETURN_REQUESTED})
# Statuses counted as revenue in reports
REVENUE_STATES = frozenset({S.PAID, S.CONFIRMED, S.PROCESSING, S.SHIPPED, S.DELIVERED, S.RETURN_REQUESTED})
TERMINAL_STATES = frozenset(s for s, targets in TRANSITIONS.items() if not targets)
STATUS_CHOICES = [(s.value, s.value.replace("_", " ").title()) for s in OrderStatus]


def allowed_targets(current: str, actor) -> list[str]:
    """Statuses `actor` (a Role or SYSTEM) may move an order to from `current`."""
    return [t.value for t, actors in TRANSITIONS[OrderStatus(current)].items() if actor in actors]


def can_transition(current: str, target: str, actor) -> bool:
    return actor in TRANSITIONS[OrderStatus(current)].get(OrderStatus(target), set())
