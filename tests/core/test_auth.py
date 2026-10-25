import pytest
from django.urls import get_resolver
from rest_framework.test import APIClient

from backend.folder_one_core.accounts.models import User
from backend.shared.roles import Role
from config.loader import business
from tests.conftest import PASSWORD, client_for, make_user

pytestmark = pytest.mark.django_db


def test_register_creates_customer_with_argon2_hash():
    c = APIClient()
    r = c.post("/api/auth/register/", {"email": "New@Example.com", "password": PASSWORD, "role": "ADMIN"}, format="json")
    assert r.status_code == 201, r.data
    u = User.objects.get(email="new@example.com")
    assert u.role == Role.CUSTOMER  # role cannot be self-assigned
    assert u.password.startswith("argon2")


def test_register_rejects_weak_password_and_duplicate():
    c = APIClient()
    assert c.post("/api/auth/register/", {"email": "a@b.com", "password": "123"}, format="json").status_code == 400
    make_user(email="dup@b.com")
    assert c.post("/api/auth/register/", {"email": "dup@b.com", "password": PASSWORD}, format="json").status_code == 400


def test_login_returns_tokens_and_user():
    make_user(email="login@test.local")
    r = APIClient().post("/api/auth/login/", {"email": "login@test.local", "password": PASSWORD}, format="json")
    assert r.status_code == 200
    assert {"access", "refresh", "user"} <= set(r.data)
    me = APIClient()
    me.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
    assert me.get("/api/auth/me/").data["email"] == "login@test.local"


def test_login_rate_limited():
    make_user(email="rl@test.local")
    limit = int(business()["auth"]["login_rate"].split("/")[0])
    c = APIClient()
    codes = [c.post("/api/auth/login/", {"email": "rl@test.local", "password": "wrong"}, format="json").status_code
             for _ in range(limit + 1)]
    assert codes[:limit] == [401] * limit
    assert codes[-1] == 429


PUBLIC = {"/api/auth/register/", "/api/auth/login/", "/api/auth/refresh/", "/api/schema/", "/api/docs/"}


def _api_paths():
    from django.urls import URLPattern, URLResolver

    def walk(patterns, prefix=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                path = prefix + str(p.pattern)
                if path.startswith("api/"):
                    yield path
    import re
    out = set()
    for raw in walk(get_resolver().url_patterns):
        path = raw.replace("^", "").replace("$", "").replace("\\.", ".")
        path = re.sub(r"\(\?P<format>[^)]*\)", "", path)
        path = re.sub(r"\(\?P<[^>]+>[^)]*\)|<[^>]+>", "1", path)
        path = path.replace("\\", "")
        if "format" in raw or "." in path.split("/")[-1]:
            continue
        out.add("/" + path)
    return sorted(out)


def test_every_api_endpoint_requires_authentication():
    c = APIClient()
    paths = _api_paths()
    assert len(paths) > 20
    for path in paths:
        if path in PUBLIC:
            continue
        for method in ("get", "post"):
            r = getattr(c, method)(path)
            assert r.status_code in (401, 405), f"{method.upper()} {path} -> {r.status_code}"


def test_role_checks():
    cust, staff = make_user(Role.CUSTOMER), make_user(Role.STAFF)
    assert client_for(cust).get("/api/admin/users/").status_code == 403
    assert client_for(staff).get("/api/admin/users/").status_code == 403
    assert client_for(cust).get("/api/inventory/").status_code == 403
    assert client_for(staff).get("/api/inventory/").status_code == 200
    assert client_for(staff).get("/api/cart/").status_code == 403
    assert client_for(make_user(Role.ADMIN)).get("/api/admin/users/").status_code == 200


def test_admin_changes_role_but_not_own(admin):
    target = make_user()
    c = client_for(admin)
    assert c.patch(f"/api/admin/users/{target.id}/", {"role": "STAFF"}, format="json").data["role"] == "STAFF"
    assert c.patch(f"/api/admin/users/{admin.id}/", {"role": "CUSTOMER"}, format="json").status_code == 400


def test_addresses_are_private(customer):
    other = make_user()
    c = client_for(customer)
    bad = c.post("/api/addresses/", {"label": "Work", "full_name": "X", "line1": "2 St", "city": "Pune",
                                      "state": "Maharashtra", "postal_code": "4110", "phone": "12345",
                                      "country": "India"}, format="json")
    assert bad.status_code == 400
    assert "PIN" in str(bad.data) and "mobile" in str(bad.data)
    r = c.post("/api/addresses/", {"label": "Work", "full_name": "X", "line1": "Office 5, Tech Park", "city": "Pune",
                                    "state": "Maharashtra", "postal_code": "411 014", "phone": "+91 98220 41234",
                                    "country": "India"}, format="json")
    assert r.status_code == 201 and r.data["postal_code"] == "411014"
    assert client_for(other).get("/api/addresses/").data == []
    assert client_for(other).get(f"/api/addresses/{r.data['id']}/").status_code == 404
