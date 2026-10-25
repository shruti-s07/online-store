import itertools
from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from backend.folder_one_core.accounts.models import Address, User
from backend.folder_one_core.catalog.models import Category, Product
from backend.folder_one_core.inventory.services import adjust_stock, ensure_inventory
from backend.shared import hooks
from backend.shared.roles import Role

PASSWORD = "Sup3r-Secret-pass"
_seq = itertools.count(1)


@pytest.fixture(autouse=True)
def _clear_cache(settings, tmp_path):
    cache.clear()
    settings.MEDIA_ROOT = tmp_path / "media"
    yield
    cache.clear()


@pytest.fixture
def stub_hooks(monkeypatch):
    """Use folder one's safe default hooks (core tests must not depend on folder two)."""
    stubs = {"apply_discounts": hooks.default_apply_discounts, "score_order": hooks.default_score_order}
    monkeypatch.setattr(hooks, "get_hook", lambda name: stubs[name])
    return stubs


def make_user(role=Role.CUSTOMER, email=None, **kw) -> User:
    return User.objects.create_user(email or f"user{next(_seq)}@test.local", PASSWORD, role=role.value, **kw)


def make_address(user, **kw) -> Address:
    data = dict(label="Home", full_name="Ananya Rao", line1="Flat 204, Palm Grove", line2="4th Main, Jayanagar",
                city="Bengaluru", state="Karnataka", postal_code="560011", country="India", is_default=True)
    data.update(kw)
    return Address.objects.create(user=user, **data)


def make_product(stock=10, price="20.00", cost="10.00", category=None, **kw) -> Product:
    n = next(_seq)
    category = category or Category.objects.get_or_create(name="Cat", slug="cat")[0]
    p = Product.objects.create(sku=f"SKU-{n}", name=kw.pop("name", f"Product {n}"), category=category,
                               price=Decimal(price), cost=Decimal(cost), supplier_lead_time_days=7, **kw)
    ensure_inventory(p)
    if stock:
        adjust_stock(p, stock, "INITIAL")
    return p


def client_for(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def customer(db):
    u = make_user(Role.CUSTOMER)
    make_address(u)
    return u


@pytest.fixture
def staff(db):
    return make_user(Role.STAFF)


@pytest.fixture
def admin(db):
    return make_user(Role.ADMIN)


@pytest.fixture
def isolated_models(monkeypatch, tmp_path):
    """Point model artifacts / ground truth at empty temp dirs (never touch ai/models)."""
    from ai import common
    monkeypatch.setattr(common, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(common, "DATA_DIR", tmp_path / "data")
    return tmp_path / "models"


def product_with_image(icon="cellphone", color_seed=1, **kw):
    from django.core.files.base import ContentFile

    from ai.images import product_image, to_png_bytes
    from backend.folder_one_core.catalog.models import ProductImage
    p = make_product(**kw)
    img = ProductImage(product=p, is_primary=True)
    img.image.save("main.png", ContentFile(to_png_bytes(product_image(icon, color_seed, 160))), save=True)
    return p


def deliver(order_id, staff_user):
    c = client_for(staff_user)
    for st in ("PROCESSING", "SHIPPED", "DELIVERED"):
        r = c.post(f"/api/orders/{order_id}/transition/", {"status": st}, format="json")
        assert r.status_code == 200, r.data
