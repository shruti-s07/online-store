import pytest

from backend.folder_one_core.catalog.models import Category, Product
from tests.conftest import client_for, make_product

pytestmark = pytest.mark.django_db


def test_staff_creates_product_with_validation(staff, customer):
    cat = Category.objects.create(name="Gadgets", slug="gadgets")
    payload = {"sku": "G-1", "name": "Gizmo", "category": cat.id, "price": "50.00", "cost": "60.00",
               "supplier_lead_time_days": 5}
    c = client_for(staff)
    r = c.post("/api/products/", payload, format="json")
    assert r.status_code == 400 and "cost" in r.data["errors"]
    payload["cost"] = "30.00"
    r = c.post("/api/products/", payload, format="json")
    assert r.status_code == 201
    assert r.data["available"] == 0
    assert client_for(customer).post("/api/products/", payload, format="json").status_code == 403


def test_customer_does_not_see_cost(customer):
    p = make_product()
    data = client_for(customer).get(f"/api/products/{p.id}/").data
    assert "cost" not in data and data["available"] == 10


def test_soft_delete_and_restore(staff, customer):
    p = make_product()
    c = client_for(staff)
    assert c.delete(f"/api/products/{p.id}/").status_code == 204
    assert Product.all_objects.get(id=p.id).is_deleted
    assert client_for(customer).get(f"/api/products/{p.id}/").status_code == 404
    ids = [x["id"] for x in c.get("/api/products/?include_deleted=true&page_size=100").data["results"]]
    assert p.id in ids
    assert c.post(f"/api/products/{p.id}/restore/").status_code == 200
    assert client_for(customer).get(f"/api/products/{p.id}/").status_code == 200


def test_search_filter_and_pagination(customer):
    cat = Category.objects.create(name="Books", slug="books")
    make_product(name="Blue Novel", category=cat, price="12.00", cost="5.00")
    make_product(name="Red Lamp", price="90.00")
    make_product(name="Empty Thing", stock=0)
    c = client_for(customer)
    r = c.get("/api/products/?search=novel")
    assert [x["name"] for x in r.data["results"]] == ["Blue Novel"]
    assert c.get("/api/products/?category=books").data["count"] == 1
    assert c.get("/api/products/?max_price=50").data["count"] == 2
    assert "Empty Thing" not in [x["name"] for x in c.get("/api/products/?in_stock=true").data["results"]]
    assert c.get("/api/products/?page_size=1").data["next"] is not None


def test_stock_adjustment(staff):
    p = make_product(stock=5)
    c = client_for(staff)
    r = c.post(f"/api/inventory/{p.id}/adjust/", {"delta": 7, "reason": "RESTOCK"}, format="json")
    assert r.data["on_hand"] == 12
    r = c.post(f"/api/inventory/{p.id}/adjust/", {"delta": -50, "reason": "DAMAGE"}, format="json")
    assert r.status_code == 400 and r.data["code"] == "negative_stock"
    assert len(c.get(f"/api/inventory/{p.id}/movements/").data) == 2


def test_image_upload(staff):
    import io
    from PIL import Image
    p = make_product()
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(buf, "PNG")
    buf.seek(0)
    buf.name = "x.png"
    r = client_for(staff).post(f"/api/products/{p.id}/images/", {"image": buf}, format="multipart")
    assert r.status_code == 201 and r.data["is_primary"]
    bad = io.BytesIO(b"not an image")
    bad.name = "x.png"
    assert client_for(staff).post(f"/api/products/{p.id}/images/", {"image": bad}, format="multipart").status_code == 400
