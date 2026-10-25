"""Staff screens: product management (form, stock, images) and the order queue."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit, QScrollArea,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget)

from backend.shared.formatting import format_datetime
from backend.shared.order_states import OrderStatus
from config.loader import business

from . import registry
from .base_page import BasePage
from .context import ctx
from .pages_customer import IMAGE_FILTER, clear_layout
from .registry import PageSpec, register_page
from .widgets import (Banner, Card, Col, ConfirmDialog, DataTable, Field, ImageLabel, StatusChip, Timeline,
                      ValidatedForm, button, hbox, label, money)
from .worker import run_async


class ProductsAdminPage(BasePage):
    title = "Products"
    empty_text = "No products found."

    def build(self):
        self.page_no, self.selected = 1, None
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, SKU or brand")
        self.search.returnPressed.connect(lambda: self.go(1, self.table.page_size))
        self.show_deleted = QCheckBox("Show deleted")
        self.show_deleted.toggled.connect(lambda: self.go(1, self.table.page_size))
        bar.addWidget(self.search, 1)
        bar.addWidget(self.show_deleted)
        self.body_lay.addLayout(bar)
        self.actions.addWidget(button("Add product", "primary", None, lambda: self.edit(None)))
        self.edit_btn = button("Edit", None, "fa5s.pen", lambda: self.edit(self.selected))
        self.stock_btn = button("Adjust stock", None, "fa5s.boxes", self.adjust)
        self.img_btn = button("Upload photo", None, "fa5s.image", self.upload)
        self.del_btn = button("Delete", "danger", "fa5s.trash-alt", self.delete)
        for b in (self.edit_btn, self.stock_btn, self.img_btn, self.del_btn):
            b.setEnabled(False)
            bar.addWidget(b)
        self.table = DataTable([Col("sku", "SKU", width=100), Col("name", "Name"),
                                Col("category_name", "Category", width=170),
                                Col("price", "Price", "money", 100), Col("cost", "Cost", "money", 100),
                                Col("on_hand", "On hand", "int", 90), Col("available", "Available", "int", 90),
                                Col("state", "Status", "status", 110)])
        self.table.page_requested.connect(self.go)
        self.table.selected.connect(self.select)
        self.table.activated.connect(self.edit)
        self.body_lay.addWidget(self.table, 1)

    def select(self, row):
        self.selected = row
        deleted = row.get("is_deleted")
        for b in (self.edit_btn, self.stock_btn, self.img_btn):
            b.setEnabled(not deleted)
        self.del_btn.setEnabled(True)
        self.del_btn.setText("Restore" if deleted else "Delete")
        self.del_btn.setProperty("variant", "success" if deleted else "danger")
        self.del_btn.style().unpolish(self.del_btn)
        self.del_btn.style().polish(self.del_btn)

    def go(self, page, size):
        self.page_no = max(1, page)
        self.refresh()

    def fetch(self):
        p = {"page": self.page_no, "page_size": self.table.page_size, "search": self.search.text().strip()}
        if self.show_deleted.isChecked():
            p["include_deleted"] = "true"
        return {"page": self.api.get("products/", p), "categories": self.api.get("categories/")}

    def is_empty(self, d):
        return d["page"]["count"] == 0

    def render(self, d):
        self.categories = d["categories"]
        rows = [{**r, "state": "HIDDEN" if r["is_deleted"] else "VISIBLE"} for r in d["page"]["results"]]
        self.table.set_rows(rows, d["page"]["count"], self.page_no)

    def edit(self, row):
        if ProductDialog(self, row, getattr(self, "categories", [])).exec():
            self.refresh()

    def adjust(self):
        if self.selected and StockDialog(self, self.selected).exec():
            self.refresh()

    def upload(self):
        path, _ = QFileDialog.getOpenFileName(self, "Product photo", "", IMAGE_FILTER)
        if path:
            run_async(lambda: self.api.upload(f"products/{self.selected['id']}/images/", path, extra={"is_primary": "true"}),
                      lambda _: self.banner.show_message("Photo uploaded.", "success"),
                      lambda e: self.banner.show_message(str(e), "error"))

    def delete(self):
        p = self.selected
        if p["is_deleted"]:
            run_async(lambda: self.api.post(f"products/{p['id']}/restore/"), lambda _: self.refresh())
        elif ConfirmDialog.ask(self, "Delete product", f"Hide '{p['name']}' from the catalogue? It can be restored later.",
                               "Delete", True):
            run_async(lambda: self.api.delete(f"products/{p['id']}/"), lambda _: self.refresh(),
                      lambda e: self.banner.show_message(str(e), "error"))


class ProductDialog(QDialog):
    def __init__(self, parent, row: dict | None, categories: list[dict]):
        super().__init__(parent)
        self.row = row
        self.setWindowTitle("Edit product" if row else "New product")
        self.setMinimumWidth(820)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.addWidget(label(self.windowTitle(), "PageTitle"))
        self.banner = Banner()
        lay.addWidget(self.banner)
        top = QHBoxLayout()
        if row:
            img = ImageLabel(QSize(140, 120))
            img.load(row["images"][0]["image"] if row.get("images") else None)
            top.addWidget(img, 0, Qt.AlignTop)
        self.form = ValidatedForm([
            Field("sku", "SKU", required=True, pattern=r"^[A-Z0-9\-]{3,40}$", message="Use 3-40 capital letters, digits or dashes."),
            Field("name", "Name", required=True), Field("brand", "Brand"),
            Field("category", "Category", "combo", required=True, choices=[(c["name"], c["id"]) for c in categories]),
            Field("price", "Price", "decimal", required=True, minimum=0.01),
            Field("cost", "Cost", "decimal", required=True, minimum=0,
                  validator=lambda v, d: "Cost must not exceed price." if v > d["price"] else None),
            Field("supplier_lead_time_days", "Supplier lead time (days)", "int", required=True, minimum=1),
            Field("description", "Description", "multiline"),
        ], columns=2)
        if row:
            self.form.set_values(row)
        else:
            self.form.set_value("supplier_lead_time_days", business()["inventory"]["default_supplier_lead_time_days"])
        top.addWidget(self.form, 1)
        lay.addLayout(top)
        lay.addLayout(hbox(None, button("Cancel", None, None, self.reject), button("Save", "primary", "fa5s.save", self.save)))

    def save(self):
        data = self.form.validate()
        if not data:
            return
        api = ctx().api
        call = (lambda: api.patch(f"products/{self.row['id']}/", data)) if self.row else (lambda: api.post("products/", data))
        run_async(call, lambda _: self.accept(),
                  lambda e: (self.form.set_server_errors(getattr(e, "data", {}).get("errors")),
                             self.banner.show_message(str(e), "error")))


class StockDialog(QDialog):
    def __init__(self, parent, row: dict):
        super().__init__(parent)
        self.row = row
        self.setWindowTitle("Adjust stock")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.addWidget(label(row["name"], "H2"))
        lay.addWidget(label(f"On hand {row.get('on_hand')} · available {row['available']}", "Muted"))
        self.banner = Banner()
        lay.addWidget(self.banner)
        self.form = ValidatedForm([
            Field("delta", "Change (+ restock / − remove)", "int", required=True,
                  validator=lambda v, d: "Change must not be zero." if v == 0 else (
                      "Cannot remove more than on hand." if row.get("on_hand") is not None and -v > row["on_hand"] else None)),
            Field("reason", "Reason", "combo", choices=[(r.title(), r) for r in ("RESTOCK", "ADJUSTMENT", "DAMAGE", "RETURN")]),
            Field("reference", "Reference (PO number, note)")])
        lay.addWidget(self.form)
        lay.addLayout(hbox(None, button("Cancel", None, None, self.reject), button("Apply", "primary", "fa5s.check", self.save)))

    def save(self):
        data = self.form.validate()
        if data:
            run_async(lambda: ctx().api.post(f"inventory/{self.row['id']}/adjust/", data), lambda _: self.accept(),
                      lambda e: self.banner.show_message(str(e), "error"))


class OrderQueuePage(BasePage):
    title = "Orders"
    empty_text = "No orders match these filters."

    def build(self):
        self.page_no, self.current = 1, None
        tabs = QTabWidget()
        self.tabs = tabs
        orders = QWidget()
        ol = QVBoxLayout(orders)
        ol.setContentsMargins(0, 8, 0, 0)
        bar = QHBoxLayout()
        self.status = QComboBox()
        self.status.addItem("All statuses", "")
        for s in OrderStatus:
            self.status.addItem(ctx().theme.status_label(s.value), s.value)
        self.risk = QComboBox()
        for t, v in (("Any risk", ""), ("High risk", "HIGH"), ("Medium risk", "MEDIUM"), ("Low risk", "LOW")):
            self.risk.addItem(t, v)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Order number or customer email")
        for w in (self.status, self.risk):
            w.currentIndexChanged.connect(lambda: self.go(1, self.table.page_size))
        self.search.returnPressed.connect(lambda: self.go(1, self.table.page_size))
        bar.addWidget(self.search, 2)
        bar.addWidget(self.status, 1)
        bar.addWidget(self.risk, 1)
        ol.addLayout(bar)
        split = QSplitter()
        self.table = DataTable([Col("id", "Order", "id", 84), Col("created_at", "Placed", "datetime", 150),
                                Col("customer_email", "Customer"), Col("status", "Status", "status", 132),
                                Col("risk_level", "Risk", "status", 96), Col("total", "Total", "money", 110)])
        self.table.page_requested.connect(self.go)
        self.table.selected.connect(lambda r: self.open_order(r["id"]))
        split.addWidget(self.table)
        self.detail = Card()
        self.dl = QVBoxLayout()
        self.detail.lay.addLayout(self.dl)
        self.dl.addWidget(label("Select an order to see the details.", "Muted"))
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.detail)
        split.addWidget(sc)
        split.setSizes([820, 400])
        ol.addWidget(split, 1)
        tabs.addTab(orders, "Orders")
        snap = QWidget()
        sl = QVBoxLayout(snap)
        sl.setContentsMargins(0, 8, 0, 0)
        self.snap_table = DataTable([Col("id", "Check", "id", 70), Col("order_id", "Order", "id", 80),
                                     Col("product_name", "Product"), Col("customer_email", "Customer"),
                                     Col("verdict", "Verdict", "status", 110), Col("similarity", "Similarity", "float", 90),
                                     Col("status", "Status", "status", 100), Col("created_at", "Uploaded", "datetime")],
                                    paginated=False)
        self.snap_table.activated.connect(self.resolve_snap)
        sl.addWidget(label("Priority mismatches are listed first. Double-click a row to resolve it.", "Muted"))
        sl.addWidget(self.snap_table, 1)
        tabs.addTab(snap, "Photo checks")
        self.body_lay.addWidget(tabs, 1)

    def go(self, page, size):
        self.page_no = max(1, page)
        self.refresh()

    def fetch(self):
        p = {"page": self.page_no, "page_size": self.table.page_size, "status": self.status.currentData(),
             "risk_level": self.risk.currentData(), "search": self.search.text().strip()}
        return {"orders": self.api.get("orders/", p), "snap": self.api.get("snapchecks/", {"status": "OPEN"})}

    def render(self, d):
        self.table.set_rows(d["orders"]["results"], d["orders"]["count"], self.page_no)
        self.snap_table.set_rows(d["snap"]["results"])
        self.tabs.setTabText(1, f"Photo checks ({d['snap']['count']})")

    def open_order(self, oid):
        run_async(lambda: self.api.get(f"orders/{oid}/"), self.show_order, lambda e: self.banner.show_message(str(e), "error"))

    def show_order(self, o):
        self.current = o
        clear_layout(self.dl)
        pm = business()["checkout"]["payment_method_labels"]
        self.dl.addLayout(hbox(label(f"Order #{o['id']}", "H2"), StatusChip(o["status"]), None))
        self.dl.addWidget(label(f"{o['customer_email']} · {pm.get(o['payment_method'], o['payment_method'])} · "
                                f"{money(o['total'])} · {format_datetime(o['created_at'])}", "Small", wrap=True))
        if o["risk_score"] is not None:
            t = ctx().theme
            col = t.status_color(o["risk_level"] or "LOW")
            risk = Card(padding=10)
            risk.setStyleSheet(f"#Card {{ border: 2px solid {col}; }}")
            risk.lay.addLayout(hbox(label("Risk", "Strong"), StatusChip(o["risk_level"]), None,
                                    label(f"{o['risk_score']} / 100", "H2")))
            reasons = ", ".join(o["risk_reasons"] or [])
            if reasons:
                risk.lay.addWidget(label(reasons[:1].upper() + reasons[1:], "Muted", wrap=True))
            risk.lay.addWidget(label(f"Scored by {o['risk_model'].replace('_', ' ')}", "Caption"))
            if o["status"] == "ON_HOLD":
                risk.lay.addWidget(label("On hold. Move it to Pending to release it, or cancel it.", wrap=True))
            self.dl.addWidget(risk)
        for it in o["items"]:
            self.dl.addLayout(hbox(label(it["name"], wrap=True), label(f"× {it['quantity']}", "Muted"), None,
                                   label(money(it["line_total"]))))
        ship = o["shipping_address"]
        place = ", ".join(x for x in (ship.get("line2"), ship.get("city"), ship.get("postal_code")) if x)
        self.dl.addWidget(label(f"Ship to {ship.get('full_name')}, {place}", "Muted", wrap=True))
        if not o["address_match"]:
            self.dl.addWidget(label("Delivery address differs from billing address", "Warn"))
        self.note = QLineEdit()
        self.note.setPlaceholderText("Add a note (optional)")
        self.dl.addWidget(self.note)
        self.fraud = QCheckBox("Confirmed fraud")
        self.fraud.setChecked(o["fraud_confirmed"])
        self.dl.addWidget(self.fraud)
        # Only the transitions the state machine allows from the current status are offered
        allowed = [s.value for s in OrderStatus if s.value in set(o["allowed_transitions"])]
        self.dl.addSpacing(4)
        self.dl.addWidget(label("Next step", "Strong"))
        if allowed:
            grid = QGridLayout()
            grid.setSpacing(6)
            for i, st in enumerate(allowed):
                variant = "danger" if st == OrderStatus.CANCELLED.value else ("primary" if i == 0 else None)
                b = button(f"Mark as {ctx().theme.status_label(st).lower()}", variant)
                b.clicked.connect(lambda _=False, st=st: self.move(st))
                grid.addWidget(b, i // 2, i % 2)
            self.dl.addLayout(grid)
        else:
            self.dl.addWidget(label(f"No further steps from {ctx().theme.status_label(o['status']).lower()}.", "Muted"))
        self.dl.addSpacing(8)
        self.dl.addWidget(label("History", "Strong"))
        self.dl.addWidget(Timeline(o["history"]))
        self.dl.addStretch()

    def move(self, status):
        o = self.current
        if status == "CANCELLED" and not ConfirmDialog.ask(self, "Cancel order", f"Cancel order #{o['id']}? Stock is "
                                                           "returned and payments refunded.", "Cancel order", True):
            return
        body = {"status": status, "note": self.note.text(), "fraud_confirmed": self.fraud.isChecked()}
        run_async(lambda: self.api.post(f"orders/{o['id']}/transition/", body),
                  lambda r: (self.show_order(r), self.refresh(), self.banner.show_message(f"Order #{r['id']} moved to {ctx().theme.status_label(r['status'])}.", "success")),
                  lambda e: self.banner.show_message(str(e), "error"))

    def resolve_snap(self, row):
        if ConfirmDialog.ask(self, "Resolve SnapCheck", f"Mark check #{row['id']} for order #{row['order_id']} as resolved?",
                             "Resolve"):
            run_async(lambda: self.api.post(f"snapchecks/{row['id']}/resolve/", {"resolution": "Reviewed by staff"}),
                      lambda _: self.refresh(), lambda e: self.banner.show_message(str(e), "error"))


register_page(PageSpec("order_queue", "Orders", "fa5s.truck", registry.BACK_OFFICE, OrderQueuePage, "Sales", 20))
register_page(PageSpec("products_admin", "Products", "fa5s.box-open", registry.BACK_OFFICE, ProductsAdminPage, "Catalogue", 50))
