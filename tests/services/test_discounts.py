from decimal import Decimal

import pytest

from backend.folder_two_services.discounts import suggest
from backend.folder_two_services.discounts.models import DiscountRule
from tests.conftest import client_for, make_product
from tests.core.test_cart_checkout import checkout

pytestmark = pytest.mark.django_db


def rule(**kw):
    data = dict(name="r", status="APPROVED", conditions={}, action={"type": "percent", "value": 10})
    data.update(kw)
    return DiscountRule.objects.create(**data)


def test_hooks_resolve_to_folder_two():
    from backend.shared import hooks
    assert hooks.get_hook("apply_discounts").__module__.endswith("discounts.engine")
    assert hooks.get_hook("score_order").__module__.endswith("risk.scoring")


def test_code_and_automatic_rules(customer, isolated_models):
    p = make_product(price="60.00", stock=10)
    rule(name="Welcome", code="WELCOME10", conditions={"min_subtotal": 50})
    rule(name="Bundle", conditions={"min_quantity": 3}, action={"type": "fixed", "value": 15})
    rule(name="Draft never applies", status="DRAFT", action={"type": "percent", "value": 90})
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 1}, format="json")
    assert c.get("/api/cart/").data["discount_total"] == "0.00"
    r = c.post("/api/cart/discount-code/", {"code": "welcome10"}, format="json")
    assert r.data["discount_total"] == "6.00" and r.data["discount_code_valid"] is True
    r = c.post("/api/cart/items/", {"product_id": p.id, "quantity": 2}, format="json")
    assert r.data["discount_total"] == "33.00"  # 10% of 180 + 15 fixed
    bad = c.post("/api/cart/discount-code/", {"code": "NOPE"}, format="json")
    assert bad.data["discount_code_valid"] is False and "not valid" in bad.data["message"]
    assert checkout(c, customer).data["code"] == "invalid_discount"
    c.post("/api/cart/discount-code/", {"code": "WELCOME10"}, format="json")
    order = checkout(c, customer, key="ok").data
    assert order["discount_total"] == "33.00" and order["total"] == "147.00"
    assert {d["name"] for d in order["discounts"]} == {"Welcome", "Bundle"}


def test_rule_validation_and_approval_flow(admin, staff):
    c = client_for(admin)
    r = c.post("/api/discounts/rules/", {"name": "x", "conditions": {"evil": 1}, "action": {"type": "percent", "value": 10}},
               format="json")
    assert r.status_code == 400
    r = c.post("/api/discounts/rules/", {"name": "x", "conditions": {"min_subtotal": 10},
                                         "action": {"type": "percent", "value": 10}}, format="json")
    assert r.status_code == 201 and r.data["status"] == "DRAFT"
    assert client_for(staff).post(f"/api/discounts/rules/{r.data['id']}/approve/").status_code == 403
    assert c.post(f"/api/discounts/rules/{r.data['id']}/approve/").data["status"] == "APPROVED"
    assert c.post(f"/api/discounts/rules/{r.data['id']}/reject/").status_code == 409


def test_slow_mover_suggestion_respects_min_margin(admin, monkeypatch):
    slow = make_product(name="Slow Lamp", price="100.00", cost="40.00", stock=200)
    thin = make_product(name="Thin Margin", price="100.00", cost="92.00", stock=200)
    fast = make_product(name="Fast Seller", price="100.00", cost="40.00", stock=30)
    demand = {slow.id: 0.5, thin.id: 0.5, fast.id: 5.0}
    monkeypatch.setattr(suggest, "daily_demand_map",
                        lambda: {k: {"daily_mean": v, "residual_sd": 0.5, "model": "test"} for k, v in demand.items()})
    rows = {r["name"]: r for r in suggest.analyse_slow_movers()}
    assert "Fast Seller" not in rows
    min_margin = 0.10
    for r in (r for r in rows.values() if r["proposed_discount"] > 0):
        price_after = Decimal(r["price"]) * Decimal(str(1 - r["proposed_discount"]))
        assert price_after >= Decimal(r["cost"]) * Decimal(str(1 + min_margin)) - Decimal("0.01")
    assert rows["Slow Lamp"]["viable"] and rows["Slow Lamp"]["proposed_discount"] > 0
    assert not rows["Thin Margin"]["viable"] and rows["Thin Margin"]["proposed_discount"] == 0
    created = client_for(admin).post("/api/discounts/rules/suggest/").data
    assert [d["conditions"]["product_ids"] for d in created] == [[slow.id]]
    assert created[0]["status"] == "DRAFT" and created[0]["source"] == "SUGGESTED"
    # idempotent: no duplicate draft for the same product
    assert client_for(admin).post("/api/discounts/rules/suggest/").data == []
