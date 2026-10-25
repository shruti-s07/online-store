import pytest

from backend.folder_one_core.inventory.models import Inventory
from backend.folder_one_core.orders.models import Order
from backend.folder_one_core.payments.models import Payment
from backend.shared.order_states import SYSTEM, TRANSITIONS, OrderStatus, allowed_targets
from backend.shared.roles import Role
from tests.conftest import client_for, make_product
from tests.core.test_cart_checkout import checkout

pytestmark = pytest.mark.django_db


def test_transition_table_is_complete():
    assert set(TRANSITIONS) == set(OrderStatus)
    assert allowed_targets("SHIPPED", Role.CUSTOMER) == []
    assert "PAID" in allowed_targets("PENDING", SYSTEM)


def place(customer, qty=2, **kw):
    p = make_product(stock=5)
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": qty}, format="json")
    return p, c, checkout(c, customer, **kw).data


def test_full_lifecycle_with_return_and_restock(customer, staff, stub_hooks):
    p, c, order = place(customer)
    s = client_for(staff)
    oid = order["id"]
    # Customers cannot ship; staff cannot skip states
    assert c.post(f"/api/orders/{oid}/transition/", {"status": "SHIPPED"}, format="json").status_code == 403
    r = s.post(f"/api/orders/{oid}/transition/", {"status": "DELIVERED"}, format="json")
    assert r.status_code == 409 and r.data["code"] == "invalid_transition"
    for st in ("PROCESSING", "SHIPPED", "DELIVERED"):
        assert s.post(f"/api/orders/{oid}/transition/", {"status": st}, format="json").data["status"] == st
    assert Inventory.objects.get(product=p).on_hand == 3
    assert c.post(f"/api/orders/{oid}/return/", {"reason": "Wrong colour"}, format="json").data["status"] == "RETURN_REQUESTED"
    s.post(f"/api/orders/{oid}/transition/", {"status": "RETURNED"}, format="json")
    assert Inventory.objects.get(product=p).on_hand == 5
    r = s.post(f"/api/orders/{oid}/transition/", {"status": "REFUNDED"}, format="json")
    assert r.data["status"] == "REFUNDED"
    assert Payment.objects.get(order_id=oid).status == "REFUNDED"
    history = [h["to_status"] for h in r.data["history"]]
    assert history == ["PENDING", "PAID", "PROCESSING", "SHIPPED", "DELIVERED", "RETURN_REQUESTED", "RETURNED", "REFUNDED"]


def test_cancel_paid_order_refunds_and_restocks(customer, stub_hooks):
    p, c, order = place(customer)
    r = c.post(f"/api/orders/{order['id']}/cancel/", {"reason": "changed mind"}, format="json")
    assert r.data["status"] == "CANCELLED"
    assert Inventory.objects.get(product=p).on_hand == 5
    assert Payment.objects.get(order_id=order["id"]).status == "REFUNDED"
    assert c.post(f"/api/orders/{order['id']}/cancel/", format="json").status_code == 409


def test_cod_delivery_records_cash_and_refusal(customer, staff, stub_hooks):
    p, c, order = place(customer, method="COD", token="")
    s = client_for(staff)
    for st in ("PROCESSING", "SHIPPED", "DELIVERY_REFUSED"):
        s.post(f"/api/orders/{order['id']}/transition/", {"status": st}, format="json")
    assert Order.objects.get(id=order["id"]).status == "DELIVERY_REFUSED"
    assert not Payment.objects.filter(order_id=order["id"]).exists()


def test_customer_cannot_see_others_orders(customer, stub_hooks):
    from tests.conftest import make_user
    _, _, order = place(customer)
    assert client_for(make_user()).get(f"/api/orders/{order['id']}/").status_code == 404
