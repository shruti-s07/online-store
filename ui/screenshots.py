"""Render every screen offscreen and save PNGs into docs/screenshots/ (python store.py screenshots).

Starts the API if it is not running, drives the real UI against it as customer, staff and admin,
and creates realistic demo state through the API (e.g. a high-risk order that lands ON_HOLD).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np
import requests

from backend.shared.payment_methods import cod_method
from config.loader import ROOT, env, ml

OUT = ROOT / "docs" / "screenshots"


def api_up(base: str) -> bool:
    try:
        return requests.get(base + "/schema/", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def ensure_api():
    base = env("UI_API_BASE_URL").rstrip("/")
    if api_up(base):
        return None
    proc = subprocess.Popen([sys.executable, str(ROOT / "store.py"), "api"], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if api_up(base):
            return proc
        time.sleep(0.5)
    proc.kill()
    raise SystemExit("API did not start; run 'python store.py api' and check the database.")


class Api:
    """Plain requests helper used to prepare demo data (not part of the UI)."""

    def __init__(self, email, password):
        self.base = env("UI_API_BASE_URL").rstrip("/")
        r = requests.post(f"{self.base}/auth/login/", json={"email": email, "password": password}, timeout=30)
        r.raise_for_status()
        self.h = {"Authorization": f"Bearer {r.json()['access']}"}

    def call(self, method, path, **kw):
        r = requests.request(method, f"{self.base}/{path}", headers={**self.h, **kw.pop("headers", {})}, timeout=60, **kw)
        return r.json() if r.content else None


def prepare_demo_state():
    """A brand-new customer places a large cash-on-delivery order to a second address: real risk scoring."""
    base = env("UI_API_BASE_URL").rstrip("/")
    email = f"newbuyer{uuid.uuid4().hex[:6]}@example.com"
    pw = env("SEED_CUSTOMER_PASSWORD")
    requests.post(f"{base}/auth/register/", json={"email": email, "password": pw, "first_name": "Kabir", "last_name": "Malhotra"},
                  timeout=30)
    a = Api(email, pw)
    home = a.call("POST", "addresses/", json={"label": "Home", "full_name": "Kabir Malhotra",
                                               "line1": "House No. 118, Sector 56", "city": "Gurugram",
                                               "state": "Haryana", "postal_code": "122011",
                                               "phone": "+91 98110 23456", "country": "India"})
    other = a.call("POST", "addresses/", json={"label": "Other", "full_name": "K Malhotra",
                                                "line1": "Shop 7, Station Road", "city": "Kolkata",
                                                "state": "West Bengal", "postal_code": "700016",
                                                "phone": "+91 90070 55123", "country": "India"})
    products = a.call("GET", "products/", params={"sort": "-price", "in_stock": "true", "page_size": 3})["results"]
    for p in products:
        a.call("POST", "cart/items/", json={"product_id": p["id"], "quantity": 1})
    order = a.call("POST", "checkout/", json={"shipping_address_id": other["id"], "billing_address_id": home["id"],
                                              "payment_method": cod_method()}, headers={"Idempotency-Key": uuid.uuid4().hex})
    print(f"  demo high-risk order #{order.get('id')} -> {order.get('status')}")
    adm = Api(env("SEED_ADMIN_EMAIL"), env("SEED_ADMIN_PASSWORD"))
    adm.call("POST", "discounts/rules/suggest/")


def photo_of_product(media_path: Path) -> str:
    from PIL import Image

    from ai.images import augment
    img = Image.open(media_path).convert("RGB")
    out = augment(img, np.random.default_rng(7), ml()["models"]["snapcheck"]["augment"])
    f = Path(tempfile.gettempdir()) / f"snap_{uuid.uuid4().hex[:6]}.png"
    out.save(f)
    return str(f)


def main(record_fixtures: bool = False) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    OUT.mkdir(parents=True, exist_ok=True)
    server = ensure_api()
    try:
        prepare_demo_state()
        return run(record_fixtures)
    finally:
        if server:
            server.terminate()


def run(record_fixtures: bool = False) -> int:
    from PySide6.QtTest import QTest

    from ui.folder_a_shell.context import ctx
    from ui.folder_a_shell.worker import active_count
    from ui.main import create_app

    app, win = create_app([])
    if record_fixtures:
        from ui.folder_a_shell.api_client import RecordingApiClient
        recorder = RecordingApiClient()
        recorder.on_session_expired = ctx().api.on_session_expired
        ctx().api = recorder
    win.show()
    shots = []

    def settle(ms=250, timeout=30):
        QTest.qWait(ms)
        end = time.time() + timeout
        while active_count() and time.time() < end:
            app.processEvents()
            time.sleep(0.02)
        QTest.qWait(ms)
        while active_count() and time.time() < end:  # images requested after content arrived
            app.processEvents()
            time.sleep(0.02)
        QTest.qWait(ms)

    def shot(name, widget=None):
        settle()
        path = OUT / f"{len(shots) + 1:02d}_{name}.png"
        (widget or win).grab().save(str(path))
        shots.append(path.name)
        print("  saved", path.name)

    def dialog_shot(name, dlg, prepare=None):
        dlg.show()
        settle()
        if prepare:
            prepare(dlg)
            settle()
        shot(name, dlg)
        dlg.close()

    def login(email, password):
        ctx().api.logout()
        win.root.setCurrentWidget(win.login)
        win.login.login_form.set_value("email", email)
        win.login.login_form.set_value("password", password)
        win.login.do_login()
        settle(600)

    def page(key):
        win.open_page(key)
        settle()
        return win.pages[key]

    # ---------------------------------------------------------------- login
    ctx().api.logout()
    win.root.setCurrentWidget(win.login)
    shot("login")
    win.login.tabs.setCurrentIndex(1)
    shot("register")
    win.login.tabs.setCurrentIndex(0)

    # ---------------------------------------------------------------- customer
    login(env("SEED_CUSTOMER_EMAIL"), env("SEED_CUSTOMER_PASSWORD"))
    cat = page("catalog")
    shot("customer_catalog")
    from ui.folder_a_shell.pages_customer import CheckoutDialog, OtpDialog, ProductDialog, SnapCheckDialog
    first = cat.grid.itemAt(0).widget()
    product_id = None
    api = ctx().api
    products = api.get("products/", {"in_stock": "true", "page_size": 5})["results"]
    product_id = products[0]["id"]
    dialog_shot("product_page_reviews", ProductDialog(win, product_id))
    media = Path(env("MEDIA_ROOT"))
    media = media if media.is_absolute() else ROOT / media
    img_rel = products[1]["images"][0]["image"].split("/media/", 1)[-1]
    cat.run_photo_search(photo_of_product(media / img_rel))
    shot("customer_search_by_photo")
    api.delete("cart/")
    cart = page("cart")
    shot("cart_empty_state")
    for p in products[:2]:
        api.post("cart/items/", {"product_id": p["id"], "quantity": 1})
    api.post("cart/discount-code/", {"code": "WELCOME10"})
    cart.refresh()
    shot("cart_server_totals")

    def place_cod(dlg):
        for b in dlg.method_group.buttons():
            if b.property("method") == cod_method():
                b.setChecked(True)
    dlg = CheckoutDialog(win)
    dlg.show()
    settle()
    shot("checkout_reserved", dlg)
    place_cod(dlg)
    dlg.place_order()
    settle(600)
    shot("checkout_result", dlg)
    dlg.close()
    orders = page("orders")
    rows = api.get("orders/", {"page_size": 50})["results"]
    delivered = next((r for r in rows if r["status"] == "DELIVERED"), rows[0])
    orders.open_order(rows[0]["id"])
    shot("orders_timeline")
    orders.open_order(delivered["id"])
    settle()
    detail = api.get(f"orders/{delivered['id']}/")
    item = detail["items"][0]
    prod = api.get(f"products/{item['product']}/")
    sd = SnapCheckDialog(win, item)
    sd.show()
    settle()
    sd.submit(photo_of_product(media / prod["images"][0]["image"].split("/media/", 1)[-1]))
    shot("snapcheck_match", sd)
    other_prod = next(p for p in products if p["id"] != prod["id"])
    sd.submit(photo_of_product(media / other_prod["images"][0]["image"].split("/media/", 1)[-1]))
    shot("snapcheck_mismatch_fast_tracked", sd)
    sd.close()
    dialog_shot("otp_dialog", OtpDialog(win, rows[0]["id"]))
    asst = page("assistant")
    asst.send("find earbuds under 2000")
    settle(500)
    hp = api.get("products/", {"search": "earbuds", "max_price": 2000})["results"]
    asst.send(f"add 1 {hp[0]['name'].lower()} to my cart" if hp else "add the first product to my cart")
    settle(500)
    shot("assistant_confirm_action")
    page("profile")
    shot("profile_addresses")
    page("notifications")
    shot("notifications")
    win.toggle_theme()
    settle(500)
    page("catalog")
    shot("customer_catalog_dark")
    win.toggle_theme()
    settle()

    # ---------------------------------------------------------------- staff
    login(env("SEED_STAFF_EMAIL"), env("SEED_STAFF_PASSWORD"))
    page("dashboard")
    shot("staff_sales_dashboard")
    an = page("analytics")
    an.send("sales by category this month")
    settle(600)
    shot("staff_nl_analytics")
    page("segments")
    shot("staff_customer_segments")
    page("restock")
    shot("staff_restock_forecast")
    page("insights")
    shot("staff_ai_insights")
    q = page("order_queue")
    q.status.setCurrentIndex(q.status.findData("ON_HOLD"))
    settle()
    held = api.get("orders/", {"status": "ON_HOLD"})["results"]
    if held:
        q.open_order(held[0]["id"])
    shot("staff_order_queue_on_hold")
    q.status.setCurrentIndex(q.status.findData("PROCESSING"))
    settle()
    proc = api.get("orders/", {"status": "PROCESSING"})["results"]
    if proc:
        q.open_order(proc[0]["id"])
    shot("staff_order_queue_valid_transitions")
    q.tabs.setCurrentIndex(1)
    shot("staff_snapcheck_queue")
    pa = page("products_admin")
    pa.table.table.selectRow(0)
    settle()
    shot("staff_products")
    from ui.folder_a_shell.pages_staff import ProductDialog as EditDialog, StockDialog
    row = pa.table.rows[0]

    def invalid(d):
        d.form.set_value("cost", 99999)
        d.form.set_value("sku", "bad sku")
        d.save()
    dialog_shot("staff_product_form_validation", EditDialog(win, row, pa.categories), invalid)
    dialog_shot("staff_stock_adjustment", StockDialog(win, row))
    page("moderation")
    shot("staff_review_moderation")

    # ---------------------------------------------------------------- admin
    login(env("SEED_ADMIN_EMAIL"), env("SEED_ADMIN_PASSWORD"))
    page("discounts")
    shot("admin_discount_drafts")
    page("users")
    shot("admin_users_roles")

    # ---------------------------------------------------------------- error & session expiry
    if record_fixtures:
        api.save()
        print("  fixtures recorded in ui/fixtures/ (UI_MOCK_MODE=true replays them)")
    good = api.base
    api.base = env("SCREENSHOT_OFFLINE_API_URL")
    page("dashboard")
    shot("error_state_api_offline")
    api.base = good
    api._tokens = {"access": "expired", "refresh": "invalid"}
    win.open_page("users")
    settle(600)
    shot("session_expired_back_to_login")
    print(f"{len(shots)} screenshots in {OUT}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
