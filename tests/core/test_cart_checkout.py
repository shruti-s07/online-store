from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from backend.folder_one_core.accounts.models import Notification
from backend.folder_one_core.inventory.models import Inventory
from backend.folder_one_core.orders.models import Order
from backend.folder_one_core.payments.models import Payment
from backend.folder_one_core.reservations.models import Reservation
from backend.shared.contracts import RiskResult
from tests.conftest import client_for, make_product, make_user

pytestmark = pytest.mark.django_db


def checkout(c, user, key="k1", method="CARD", token="tok_visa"):
    addr = user.addresses.first()
    return c.post("/api/checkout/", {"shipping_address_id": addr.id, "payment_method": method, "payment_token": token},
                  format="json", HTTP_IDEMPOTENCY_KEY=key)


def test_cart_prices_on_server(customer, stub_hooks):
    p = make_product(price="19.99")
    c = client_for(customer)
    r = c.post("/api/cart/items/", {"product_id": p.id, "quantity": 2, "unit_price": "0.01"}, format="json")
    assert r.status_code == 201
    assert r.data["subtotal"] == "39.98" and r.data["total"] == "39.98"
    p.price = Decimal("10.00")
    p.save()
    assert c.get("/api/cart/").data["total"] == "20.00"


def test_cart_rejects_more_than_available(customer, stub_hooks):
    p = make_product(stock=2)
    r = client_for(customer).post("/api/cart/items/", {"product_id": p.id, "quantity": 3}, format="json")
    assert r.status_code == 409 and r.data["code"] == "out_of_stock"
    assert r.data["shortages"][0]["available"] == 2


def test_checkout_creates_paid_order_with_price_snapshot(customer, stub_hooks):
    p = make_product(stock=5, price="25.00")
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 2}, format="json")
    r = checkout(c, customer)
    assert r.status_code == 201, r.data
    assert r.data["status"] == "PAID" and r.data["total"] == "50.00"
    assert [h["to_status"] for h in r.data["history"]] == ["PENDING", "PAID"]
    assert Inventory.objects.get(product=p).on_hand == 3
    assert c.get("/api/cart/").data["lines"] == []
    p.price = Decimal("99.00")
    p.save()
    order = c.get(f"/api/orders/{r.data['id']}/").data
    assert order["items"][0]["unit_price"] == "25.00"


def test_checkout_is_idempotent(customer, stub_hooks):
    p = make_product(stock=5)
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 1}, format="json")
    a = checkout(c, customer, key="same")
    b = checkout(c, customer, key="same")
    assert a.status_code == 201 and b.status_code == 200 and a.data["id"] == b.data["id"]
    assert Order.objects.count() == 1 and Payment.objects.count() == 1
    assert checkout(c, customer, key="").data["code"] == "idempotency_key_required"


def test_declined_payment_then_retry_with_new_key(customer, stub_hooks):
    p = make_product(stock=5)
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 1}, format="json")
    r = checkout(c, customer, token="tok_declined")
    assert r.data["status"] == "PENDING" and r.data["payment_error"]["code"] == "card_declined"
    oid = r.data["id"]
    pay = lambda key, tok: c.post(f"/api/orders/{oid}/pay/", {"payment_method": "CARD", "payment_token": tok},
                                  format="json", HTTP_IDEMPOTENCY_KEY=key)
    ok = pay("retry-1", "tok_visa")
    assert ok.status_code == 201 and ok.data["order"]["status"] == "PAID"
    again = pay("retry-1", "tok_visa")
    assert again.data["payment"]["id"] == ok.data["payment"]["id"]
    assert pay("retry-1", "tok_mastercard").status_code == 422
    assert pay("retry-2", "tok_visa").status_code == 409  # already paid


def test_cod_order_is_confirmed(customer, stub_hooks):
    p = make_product()
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 1}, format="json")
    assert checkout(c, customer, method="COD", token="").data["status"] == "CONFIRMED"


def test_reservation_holds_stock_and_expires(customer, stub_hooks):
    p = make_product(stock=1)
    other = make_user()
    other.addresses.create(label="H", full_name="O", line1="x", city="Noida", postal_code="201309", country="India",
                          is_default=True)
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 1}, format="json")
    r = c.post("/api/checkout/reserve/")
    assert r.status_code == 201 and r.data["seconds_left"] > 0
    # Someone else cannot take the reserved unit
    assert client_for(other).post("/api/cart/items/", {"product_id": p.id, "quantity": 1}, format="json").status_code == 409
    # Expire it: lazily released on the next read without any job running
    Reservation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client_for(other).get(f"/api/products/{p.id}/").data["available"] == 1
    r = checkout(c, customer)
    assert r.status_code == 410 and r.data["code"] == "reservation_expired"
    assert c.get("/api/checkout/reserve/").data["status"] == "EXPIRED"


def test_checkout_out_of_stock_message(customer, stub_hooks):
    p = make_product(stock=2)
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 2}, format="json")
    Inventory.objects.filter(product=p).update(on_hand=1)
    r = checkout(c, customer)
    assert r.status_code == 409 and r.data["shortages"] == [{"product_id": p.id, "requested": 2, "available": 1}]


def test_high_risk_goes_on_hold_and_medium_requires_otp(customer, monkeypatch, stub_hooks, staff):
    level = {"v": "HIGH"}
    stub_hooks["score_order"] = lambda o: RiskResult(score=90 if level["v"] == "HIGH" else 50, level=level["v"],
                                                     reasons=("test",), model="test")
    p = make_product(stock=5)
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 1}, format="json")
    r = checkout(c, customer, key="h")
    assert r.data["status"] == "ON_HOLD" and r.data["next_action"] == "await_review"
    assert "risk_score" not in r.data  # hidden from customers
    s = client_for(staff)
    held = s.get("/api/orders/?status=ON_HOLD").data["results"][0]
    assert held["risk_score"] == 90
    assert s.get(f"/api/orders/{held['id']}/").data["allowed_transitions"] == ["PENDING", "CANCELLED"]
    r2 = s.post(f"/api/orders/{held['id']}/transition/", {"status": "PENDING", "note": "ok"}, format="json")
    assert r2.data["status"] == "PENDING"

    level["v"] = "MEDIUM"
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 1}, format="json")
    r = checkout(c, customer, key="m")
    assert r.data["status"] == "VERIFICATION_REQUIRED"
    oid = r.data["id"]
    assert c.post(f"/api/orders/{oid}/verify-otp/", {"code": "000000x"}, format="json").data["code"] == "otp_invalid"
    body = Notification.objects.filter(user=customer, kind="otp").first().body
    code = [w.strip(".") for w in body.split() if w.strip(".").isdigit()][0]
    r = c.post(f"/api/orders/{oid}/verify-otp/", {"code": code}, format="json")
    assert r.status_code == 200 and r.data["status"] == "PENDING"
