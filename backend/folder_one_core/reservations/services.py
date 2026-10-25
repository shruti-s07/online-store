from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from backend.folder_one_core.inventory.services import active_reserved, lock_inventory
from backend.shared.errors import OutOfStock
from config.loader import business

from .models import Reservation, ReservationItem


def window() -> timedelta:
    return timedelta(minutes=business()["reservations"]["window_minutes"])


def expire_stale(user=None) -> int:
    """Mark ACTIVE reservations past their expiry as EXPIRED (job + lazy read path)."""
    qs = Reservation.objects.filter(status=Reservation.Status.ACTIVE, expires_at__lte=timezone.now())
    if user is not None:
        qs = qs.filter(user=user)
    return qs.update(status=Reservation.Status.EXPIRED)


def current_reservation(user) -> Reservation | None:
    expire_stale(user)
    return Reservation.objects.filter(user=user, status=Reservation.Status.ACTIVE).prefetch_related("items").first()


def latest_reservation(user) -> Reservation | None:
    expire_stale(user)
    return Reservation.objects.filter(user=user).prefetch_related("items").first()


@transaction.atomic
def reserve(user, lines: dict[int, int]) -> Reservation:
    """Reserve `lines` {product_id: qty} for `user`, replacing any active reservation.

    Inventory rows are locked, so concurrent reservations for the same product serialise
    and can never oversell.
    """
    Reservation.objects.filter(user=user, status=Reservation.Status.ACTIVE).update(status=Reservation.Status.RELEASED)
    inventory = lock_inventory(lines.keys())
    held = active_reserved(lines.keys())
    shortages = []
    for pid, qty in lines.items():
        inv = inventory.get(pid)
        available = (inv.on_hand if inv else 0) - held.get(pid, 0)
        if qty > available:
            shortages.append({"product_id": pid, "requested": qty, "available": max(0, available)})
    if shortages:
        raise OutOfStock("Some items are out of stock or not available in the requested quantity.",
                         shortages=shortages)
    res = Reservation.objects.create(user=user, expires_at=timezone.now() + window())
    ReservationItem.objects.bulk_create([ReservationItem(reservation=res, product_id=p, quantity=q) for p, q in lines.items()])
    return res


def release(reservation: Reservation) -> None:
    if reservation.status == Reservation.Status.ACTIVE:
        reservation.status = Reservation.Status.RELEASED
        reservation.save(update_fields=["status"])
