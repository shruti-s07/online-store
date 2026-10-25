"""UI tests (offscreen Qt): registry/role menus, theme, base widgets, mock-mode replay."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def app():
    from ui.main import create_app
    app, win = create_app([])
    return app, win


def test_folder_b_panels_register_without_main_window_changes(app):
    from ui.folder_a_shell import registry
    keys = {p.key for p in registry.all_pages()}
    assert {"dashboard", "discounts", "users", "moderation", "segments", "restock", "assistant", "analytics",
            "insights"} <= keys
    import inspect

    import ui.folder_a_shell.shell as shell
    src = inspect.getsource(shell)
    assert "folder_b" not in src  # the shell only reads the registry


def test_role_based_menus(app):
    from ui.folder_a_shell.registry import pages_for
    cust = {p.key for p in pages_for("CUSTOMER")}
    staff = {p.key for p in pages_for("STAFF")}
    admin = {p.key for p in pages_for("ADMIN")}
    assert {"cart", "orders", "assistant"} <= cust and not {"order_queue", "users", "discounts"} & cust
    assert {"order_queue", "dashboard", "analytics"} <= staff and not {"users", "discounts", "cart"} & staff
    assert {"users", "discounts", "order_queue"} <= admin


def test_storefront_header_for_customers_and_sidebar_for_staff(app):
    from PySide6.QtWidgets import QWidget
    _, win = app
    shop = win._build_app({"role": "CUSTOMER", "email": "priya@example.com", "first_name": "Priya"})
    assert shop.findChild(QWidget, "StoreHeader") is not None and shop.findChild(QWidget, "Sidebar") is None
    assert {"orders", "assistant", "cart"} <= set(win.nav_buttons)  # header links come from the registry
    win.nav_buttons.clear()
    hub = win._build_app({"role": "STAFF", "email": "sam@example.com", "first_name": "Sam"})
    assert hub.findChild(QWidget, "Sidebar") is not None and hub.findChild(QWidget, "StoreHeader") is None
    assert {"order_queue", "dashboard"} <= set(win.nav_buttons)


def test_status_labels_are_sentence_case(app):
    from ui.folder_a_shell.theme import Theme
    t = Theme("light")
    assert t.status_label("ON_HOLD") == "On hold" and t.status_label("RETURN_REQUESTED") == "Return requested"


def test_theme_builds_both_modes(app):
    from ui.folder_a_shell.theme import Theme
    for mode in ("light", "dark"):
        t = Theme(mode)
        css = t.stylesheet()
        assert t.c["primary"] in css and t.c["border"] in css and t.c["background"] in css
        assert t.status_color("ON_HOLD") == t.c["danger"]


def test_validated_form_and_table(app):
    from ui.folder_a_shell.widgets import Col, DataTable, Field, ValidatedForm
    form = ValidatedForm([Field("email", "Email", "email", required=True),
                          Field("price", "Price", "decimal", minimum=0.01),
                          Field("cost", "Cost", "decimal", validator=lambda v, d: "too high" if v > d["price"] else None)])
    form.set_values({"email": "nope", "price": 5, "cost": 9})
    assert form.validate() is None
    assert form.errors["email"].text() and form.errors["cost"].text() == "too high"
    form.set_values({"email": "a@b.co", "cost": 1})
    assert form.validate() == {"email": "a@b.co", "price": 5.0, "cost": 1.0}
    t = DataTable([Col("id", "ID", "id"), Col("total", "Total", "money"), Col("status", "Status", "status")])
    t.set_rows([{"id": 2, "total": "5.00", "status": "PAID"}, {"id": 10, "total": "50.00", "status": "ON_HOLD"}],
               total=45, page=1)
    t.table.sortItems(0)
    assert t.table.item(0, 0).text() == "#2"  # numeric, not lexical, sort
    assert t.next.isEnabled() and not t.prev.isEnabled()


def test_mock_mode_replays_recorded_fixtures(app, tmp_path, monkeypatch):
    import json

    from ui.folder_a_shell import api_client
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "index.json").write_text(json.dumps({"roles": {"c@x.io": {
        "user": {"email": "c@x.io", "role": "CUSTOMER"},
        "responses": {"GET cart": {"lines": [], "total": "0.00"}}}}}))
    monkeypatch.setattr(api_client, "FIXTURE_DIR", fixtures)
    c = api_client.MockApiClient()
    with pytest.raises(api_client.ApiError):
        c.login("unknown@x.io", "pw")
    assert c.login("c@x.io", "pw")["role"] == "CUSTOMER"
    assert c.get("cart/") == {"lines": [], "total": "0.00"}
    with pytest.raises(api_client.ApiError) as e:
        c.get("orders/")
    assert e.value.code == "mock_missing"


def test_catalog_in_window_product_navigation(app):
    from ui.folder_a_shell.pages_customer import CatalogPage
    cat = CatalogPage()
    assert hasattr(cat, "stack")
    assert hasattr(cat, "detail_view")
    assert hasattr(cat, "catalog_view")
    # Starts on the catalog grid
    assert cat.stack.currentWidget() == cat.catalog_view
    # Clicking a product opens the detail view in the SAME window without a popup dialog
    cat.open_product({"id": 1, "name": "Wireless Noise Cancelling Headphones"})
    assert cat.stack.currentWidget() == cat.detail_view
    assert cat.photo_btn.isHidden()
    # Clicking back returns smoothly to the catalog grid
    cat.close_product()
    assert cat.stack.currentWidget() == cat.catalog_view
    assert not cat.photo_btn.isHidden()

