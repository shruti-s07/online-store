import io

import pytest
from PIL import Image

from backend.folder_one_core.accounts.models import Notification
from backend.folder_one_core.cart.services import price_cart
from tests.conftest import client_for, deliver, make_product, product_with_image
from tests.core.test_cart_checkout import checkout

pytestmark = pytest.mark.django_db


@pytest.fixture
def intents_model(isolated_models, db):
    make_product(name="Voltix Wireless Earbuds", price="1799.00", stock=5)
    make_product(name="Steelcraft Electric Kettle", price="1299.00", stock=5)
    from ai.train_intents import train
    train()


def test_local_assistant_search_and_confirmed_add(customer, intents_model):
    c = client_for(customer)
    r = c.post("/api/assistant/chat/", {"message": "find earbuds under ₹2,000"}, format="json").data
    assert r["engine"] == "local intent classifier" and r["tool"] == "search_products"
    assert [x["name"] for x in r["data"]["results"]] == ["Voltix Wireless Earbuds"]
    r = c.post("/api/assistant/chat/", {"message": "add 2 voltix earbuds to my cart"}, format="json").data
    assert r["pending_action"]["tool"] == "add_to_cart" and r["pending_action"]["args"]["quantity"] == 2
    assert price_cart(customer)["lines"] == []  # nothing changed before confirmation
    done = c.post(f"/api/assistant/actions/{r['pending_action']['id']}/confirm/").data
    assert done["status"] == "CONFIRMED"
    assert price_cart(customer)["lines"][0]["quantity"] == 2
    assert c.post(f"/api/assistant/actions/{r['pending_action']['id']}/confirm/").status_code == 409


def test_cancelled_action_never_runs(customer, intents_model):
    c = client_for(customer)
    r = c.post("/api/assistant/chat/", {"message": "add the steelcraft kettle to my cart"}, format="json").data
    assert c.post(f"/api/assistant/actions/{r['pending_action']['id']}/cancel/").data["status"] == "CANCELLED"
    assert c.post(f"/api/assistant/actions/{r['pending_action']['id']}/confirm/").status_code == 409
    assert price_cart(customer)["lines"] == []


def test_analytics_whitelisted_and_role_checked(customer, staff, intents_model):
    s = client_for(staff)
    r = s.post("/api/assistant/analytics/", {"message": "top 5 products last 30 days"}, format="json").data
    assert r["tool"] == "top_products" and r["args"] == {"days": 30, "limit": 5}
    assert r["data"]["columns"] == ["SKU", "Product", "Units", "Revenue"]
    assert client_for(customer).post("/api/assistant/analytics/", {"message": "revenue"}, format="json").status_code == 403
    assert s.post("/api/assistant/chat/", {"message": "hi"}, format="json").status_code == 403
    # Someone else's pending action cannot be confirmed
    r = client_for(customer).post("/api/assistant/chat/", {"message": "add the steelcraft kettle to my cart"},
                                  format="json").data
    assert s.post(f"/api/assistant/actions/{r['pending_action']['id']}/confirm/").status_code == 404


def _png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    buf.name = "photo.png"
    return buf


def test_snapcheck_match_mismatch_and_photo_search(customer, staff, isolated_models, stub_hooks):
    import numpy as np

    from ai.images import augment, product_image
    from ai.train_snapcheck import train
    from config.loader import categories, ml
    icons = [n["icon"] for n in categories()[0]["nouns"]]
    ordered = product_with_image(icon=icons[0], color_seed=11, stock=5)
    for i in range(1, len(icons)):
        product_with_image(icon=icons[i], color_seed=100 + i, stock=5)
    train()  # calibrate thresholds for the active embedder into the temp model dir
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": ordered.id, "quantity": 1}, format="json")
    order = checkout(c, customer).data
    item_id = order["items"][0]["id"]
    assert c.post("/api/snapchecks/", {"order_item_id": item_id, "image": _png(product_image(icons[0], 11, 160))},
                  format="multipart").data["code"] == "not_delivered"
    deliver(order["id"], staff)
    rng = np.random.default_rng(1)
    photo = augment(product_image(icons[0], 11, 160), rng, ml()["models"]["snapcheck"]["augment"])
    r = c.post("/api/snapchecks/", {"order_item_id": item_id, "image": _png(photo)}, format="multipart")
    assert r.status_code == 201 and r.data["verdict"] == "MATCH" and not r.data["fast_tracked"]
    wrong = product_image(icons[5], 999, 160)
    r = c.post("/api/snapchecks/", {"order_item_id": item_id, "image": _png(wrong)}, format="multipart")
    assert r.data["verdict"] == "MISMATCH" and r.data["fast_tracked"]
    assert Notification.objects.filter(user=staff, kind="snapcheck_mismatch").exists()
    queue = client_for(staff).get("/api/snapchecks/?status=OPEN").data["results"]
    assert queue[0]["fast_tracked"]
    res = c.post("/api/search/photo/", {"image": _png(photo)}, format="multipart").data
    assert res["results"][0]["product_id"] == ordered.id


def test_jobs_release_and_notify(customer, stub_hooks):
    from datetime import timedelta

    from django.utils import timezone

    from backend.folder_one_core.reservations.models import Reservation
    from backend.folder_two_services.jobs.models import JobRun
    from backend.folder_two_services.jobs.runner import release_reservations, send_notifications
    p = make_product(stock=3)
    c = client_for(customer)
    c.post("/api/cart/items/", {"product_id": p.id, "quantity": 1}, format="json")
    c.post("/api/checkout/reserve/")
    Reservation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    run = release_reservations()
    assert run.status == "SUCCEEDED" and run.detail == {"expired": 1}
    assert Reservation.objects.get().status == "EXPIRED"
    Notification.objects.create(user=customer, kind="t", title="t", body="b")
    assert send_notifications().detail == {"sent": 1}
    assert JobRun.objects.count() == 2
