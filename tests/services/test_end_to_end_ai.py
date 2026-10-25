"""End to end: seed a small synthetic world, run the full training pipeline (the same code
the nightly job runs) into a temp model dir, then use the trained models through the API."""
import pytest
from django.core.management import call_command

from ai import common
from backend.folder_one_core.accounts.models import User
from backend.folder_two_services.segmentation.models import CustomerSegment
from config.loader import env
from tests.conftest import client_for


@pytest.mark.slow
@pytest.mark.django_db
def test_seed_train_and_serve(isolated_models):
    call_command("seed_store", "--scale", "0.3")
    from ai.train import train_all
    train_all()
    for name in ("fraud", "sentiment", "forecasting", "segmentation", "recommendations", "intents", "snapcheck"):
        meta = common.load_meta(name)
        assert meta and meta["metrics"] and meta["data_hash"], name
    assert (isolated_models / "REPORT.md").read_text().count("synthetic data") >= 1
    assert CustomerSegment.objects.values("segment").distinct().count() == 4

    cust = User.objects.get(email=env("SEED_CUSTOMER_EMAIL"))
    staff = User.objects.get(email=env("SEED_STAFF_EMAIL"))
    c, s = client_for(cust), client_for(staff)
    recs = c.get("/api/recommendations/").data
    assert recs and all(r["reason"] for r in recs)
    some_product = recs[0]["product_id"]
    f = s.get(f"/api/forecasting/products/{some_product}/").data
    assert 14 <= len(f["forecast"]) <= 30
    assert s.get("/api/forecasting/restock/?all=true").status_code == 200
    assert s.get("/api/segments/summary/").data["segments"]
    assert "pros" in c.get(f"/api/products/{some_product}/review-insights/").data
    assert s.get("/api/discounts/rules/slow_movers/").status_code == 403  # admin only
