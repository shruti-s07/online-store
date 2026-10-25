"""Persistent cart. Prices are always computed on the server from current product data."""
from django.db import transaction

from backend.folder_one_core.catalog.models import Product
from backend.folder_one_core.inventory.services import availability_map
from backend.shared import hooks
from backend.shared.contracts import CartLine, CartSnapshot
from backend.shared.errors import DomainError, OutOfStock
from backend.shared.money import money

from .models import Cart, CartItem


def get_cart(user) -> Cart:
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


def snapshot(cart: Cart, products: dict[int, Product] | None = None) -> CartSnapshot:
    items = list(cart.items.select_related("product"))
    lines = []
    for it in items:
        p = products[it.product_id] if products else it.product
        lines.append(CartLine(product_id=p.id, sku=p.sku, name=p.name, category_id=p.category_id,
                              unit_price=p.price, unit_cost=p.cost, quantity=it.quantity))
    return CartSnapshot(user_id=cart.user_id, lines=tuple(lines), discount_code=cart.discount_code or None)


def price_cart(user) -> dict:
    """Server-side pricing: current prices, live availability, discounts from the hook."""
    from backend.folder_one_core.reservations.services import latest_reservation

    cart = get_cart(user)
    items = list(cart.items.select_related("product__category").prefetch_related("product__images"))
    # Soft-deleted products are dropped from the cart rather than sold.
    removed = [it.product.name for it in items if it.product.is_deleted]
    if removed:
        cart.items.filter(product__is_deleted=True).delete()
        items = [it for it in items if not it.product.is_deleted]
    snap = snapshot(cart)
    avail = availability_map([it.product_id for it in items])
    reservation = latest_reservation(user)
    mine = {}
    if reservation and reservation.status == reservation.Status.ACTIVE:
        mine = {ri.product_id: ri.quantity for ri in reservation.items.all()}
    result = hooks.apply_discounts(snap)
    lines = []
    for it in items:
        a = avail[it.product_id]
        available_to_me = a["available"] + mine.get(it.product_id, 0)
        img = it.product.primary_image
        lines.append({
            "product_id": it.product_id, "sku": it.product.sku, "name": it.product.name,
            "category": it.product.category.name, "image": img.image.url if img else None,
            "unit_price": str(money(it.product.price)), "quantity": it.quantity,
            "line_total": str(money(it.product.price * it.quantity)),
            "available": available_to_me,
            "stock_issue": None if it.quantity <= available_to_me else (
                "Out of stock" if available_to_me == 0 else f"Only {available_to_me} left"),
        })
    subtotal = money(snap.subtotal)
    discount = min(money(result.amount), subtotal)
    return {
        "lines": lines,
        "item_count": snap.quantity,
        "subtotal": str(subtotal),
        "discount_total": str(discount),
        "total": str(money(subtotal - discount)),
        "discount_code": cart.discount_code or None,
        "discount_code_valid": result.code_valid,
        "discounts": [{"rule_id": d.rule_id, "name": d.name, "amount": str(money(d.amount))} for d in result.applied],
        "message": result.message,
        "removed_unavailable": removed,
        "has_stock_issue": any(l["stock_issue"] for l in lines),
    }


@transaction.atomic
def set_quantity(user, product_id: int, quantity: int, increment: bool = False) -> None:
    if quantity < 0:
        raise DomainError("Quantity must be positive.", code="invalid_quantity")
    product = Product.objects.filter(id=product_id).first()
    if product is None:
        raise DomainError("Product not found.", code="not_found", status_code=404)
    cart = get_cart(user)
    item = cart.items.select_for_update().filter(product=product).first()
    new_qty = (item.quantity if item and increment else 0) + quantity
    if new_qty <= 0:
        if item:
            item.delete()
        return
    available = availability_map([product.id])[product.id]["available"]
    if new_qty > available:
        raise OutOfStock(
            f"Only {available} unit(s) of {product.name} available." if available else f"{product.name} is out of stock.",
            shortages=[{"product_id": product.id, "requested": new_qty, "available": available}])
    if item:
        item.quantity = new_qty
        item.save(update_fields=["quantity"])
    else:
        CartItem.objects.create(cart=cart, product=product, quantity=new_qty)
    cart.save(update_fields=["updated_at"])


def remove(user, product_id: int) -> None:
    get_cart(user).items.filter(product_id=product_id).delete()


def set_discount_code(user, code: str | None) -> None:
    cart = get_cart(user)
    cart.discount_code = (code or "").strip().upper()
    cart.save(update_fields=["discount_code", "updated_at"])


def clear(user) -> None:
    cart = get_cart(user)
    cart.items.all().delete()
    cart.discount_code = ""
    cart.save(update_fields=["discount_code", "updated_at"])
