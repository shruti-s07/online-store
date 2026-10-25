from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from backend.shared.errors import DomainError

from .models import Inventory, StockMovement


def ensure_inventory(product) -> Inventory:
    inv, _ = Inventory.objects.get_or_create(product=product)
    return inv


def active_reserved(product_ids, exclude_reservation_id=None) -> dict[int, int]:
    """Units held by reservations that are ACTIVE and not yet expired (lazy expiry)."""
    from backend.folder_one_core.reservations.models import Reservation, ReservationItem

    qs = ReservationItem.objects.filter(
        product_id__in=list(product_ids),
        reservation__status=Reservation.Status.ACTIVE,
        reservation__expires_at__gt=timezone.now(),
    )
    if exclude_reservation_id:
        qs = qs.exclude(reservation_id=exclude_reservation_id)
    return {r["product_id"]: r["q"] for r in qs.values("product_id").annotate(q=Sum("quantity"))}


def availability_map(product_ids) -> dict[int, dict]:
    product_ids = list(product_ids)
    on_hand = dict(Inventory.objects.filter(product_id__in=product_ids).values_list("product_id", "on_hand"))
    reserved = active_reserved(product_ids)
    return {
        pid: {"on_hand": on_hand.get(pid, 0), "reserved": reserved.get(pid, 0),
              "available": max(0, on_hand.get(pid, 0) - reserved.get(pid, 0))}
        for pid in product_ids
    }


def lock_inventory(product_ids) -> dict[int, Inventory]:
    """Row-lock inventory rows in a stable order to avoid deadlocks. Call inside atomic()."""
    rows = Inventory.objects.select_for_update().filter(product_id__in=sorted(set(product_ids))).order_by("product_id")
    return {r.product_id: r for r in rows}


@transaction.atomic
def adjust_stock(product, delta: int, reason: str, user=None, reference: str = "") -> Inventory:
    ensure_inventory(product)
    inv = lock_inventory([product.id])[product.id]
    if inv.on_hand + delta < 0:
        raise DomainError(f"Cannot remove {-delta} units; only {inv.on_hand} on hand.", code="negative_stock")
    inv.on_hand += delta
    inv.save(update_fields=["on_hand", "updated_at"])
    StockMovement.objects.create(product=product, delta=delta, reason=reason, user=user, reference=reference)
    return inv
