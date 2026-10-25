import pytest

from backend.folder_two_services.risk import scoring
from backend.shared.contracts import OrderSnapshot
from tests.conftest import client_for, deliver, make_product, make_user
from tests.core.test_cart_checkout import checkout

pytestmark = pytest.mark.django_db


def snap(**kw):
    base = dict(order_id=1, user_id=1, payment_method="CARD", prepaid=True, total=50, item_count=1,
                account_age_days=400, address_match=True, past_refused_deliveries=0, prior_orders=10, hour_of_day=14)
    base.update(kw)
    return OrderSnapshot(**base)


def test_rule_fallback_scores_when_model_missing(isolated_models):
    low = scoring.score_order(snap())
    high = scoring.score_order(snap(payment_method="COD", prepaid=False, account_age_days=1, address_match=False,
                                    past_refused_deliveries=2))
    assert low.level == "LOW" and low.model.startswith("rules")
    assert high.score >= 70 and high.level == "HIGH"
    assert "cash on delivery" in high.reasons


def test_checkout_with_real_hook_sets_on_hold(isolated_models, staff):
    u = make_user()
    u.addresses.create(label="H", full_name="N", line1="1", city="Pune", postal_code="411038", country="India",
                       is_default=True)
    other = u.addresses.create(label="O", full_name="N", line1="2", city="Kolkata", postal_code="700091", country="India")
    p = make_product(stock=5)
    c = client_for(u)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 1}, format="json")
    r = c.post("/api/checkout/", {"shipping_address_id": other.id, "payment_method": "COD"}, format="json",
               HTTP_IDEMPOTENCY_KEY="x")
    # COD (20) + brand-new account (20) + address mismatch (25) = 65 -> MEDIUM -> OTP
    assert r.data["status"] == "VERIFICATION_REQUIRED"
    staff_view = client_for(staff).get(f"/api/orders/{r.data['id']}/").data
    assert staff_view["risk_score"] == 65 and staff_view["risk_level"] == "MEDIUM"


def test_reviews_verified_duplicates_and_moderation(customer, staff, isolated_models, stub_hooks):
    p = make_product(stock=5)
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 1}, format="json")
    order = checkout(c, customer).data
    deliver(order["id"], staff)
    r = c.post(f"/api/products/{p.id}/reviews/", {"rating": 5, "title": "Great", "body": "The build quality is great."},
               format="json")
    assert r.status_code == 201 and r.data["verified_purchase"]
    assert "fake_score" not in r.data
    assert c.post(f"/api/products/{p.id}/reviews/", {"rating": 1, "body": "again"}, format="json").status_code == 409
    # A burst of identical unverified 5-star reviews from brand-new accounts gets flagged
    for _ in range(5):
        client_for(make_user()).post(f"/api/products/{p.id}/reviews/",
                                     {"rating": 5, "body": "Best product ever!!! Highly recommend!!!"}, format="json")
    s = client_for(staff)
    flagged = s.get("/api/reviews/moderation/").data["results"]
    assert len(flagged) == 5 and all("duplicate_text" in f["fake_reasons"] for f in flagged)
    assert len(client_for(customer).get(f"/api/products/{p.id}/reviews/").data["results"]) == 1
    s.post(f"/api/reviews/moderation/{flagged[0]['id']}/moderate/", {"status": "HIDDEN"}, format="json")
    assert len(s.get("/api/reviews/moderation/").data["results"]) == 4
    insights = c.get(f"/api/products/{p.id}/review-insights/").data
    assert insights["review_count"] == 1 and insights["flagged"] == 4


def test_reports_and_exports(customer, staff, stub_hooks):
    p = make_product(stock=50, price="30.00")
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 2}, format="json")
    checkout(c, customer)
    s = client_for(staff)
    names = [r["name"] for r in s.get("/api/reports/").data]
    for n in names:
        r = s.get(f"/api/reports/{n}/")
        assert r.status_code == 200 and {"title", "columns", "rows"} <= set(r.data), n
    rev = s.get("/api/reports/revenue_summary/?days=7").data
    assert rev["rows"][0] == ["Revenue", "60.00"]
    csv = s.get("/api/reports/sales_by_category/?export=csv")
    assert csv["Content-Type"] == "text/csv" and b"Category,Revenue" in csv.content
    pdf = s.get("/api/reports/top_products/?export=pdf")
    assert pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert c.get("/api/reports/revenue_summary/").status_code == 403
    mine = c.get("/api/reports/my-orders/").data
    assert len(mine["rows"]) == 1


def test_restock_formula(staff, monkeypatch):
    import math

    from backend.folder_two_services.forecasting import service
    p = make_product(stock=10)
    p.supplier_lead_time_days = 9
    p.save()
    monkeypatch.setattr(service, "daily_demand_map", lambda: {p.id: {"daily_mean": 2.0, "residual_sd": 1.0, "model": "t"}})
    row = client_for(staff).get("/api/forecasting/restock/").data["results"][0]
    safety = max(3, 1.65 * 1.0 * math.sqrt(9))
    assert row["reorder_point"] == round(2.0 * 9 + safety, 1)
    assert row["needs_reorder"] and row["suggested_order_qty"] == math.ceil(2 * 9 + safety + 2 * 14 - 10)


def test_models_not_trained_returns_503(staff, isolated_models):
    r = client_for(staff).get("/api/forecasting/restock/")
    assert r.status_code == 503 and r.data["code"] == "model_not_trained"
