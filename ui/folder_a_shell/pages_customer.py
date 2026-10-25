"""Customer screens: catalogue, product page, cart, checkout, orders, SnapCheck, profile, notifications."""
from __future__ import annotations

import uuid

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QLineEdit, QRadioButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget)

from backend.shared.formatting import format_date, format_datetime, group_number
from backend.shared.payment_methods import is_prepaid
from config.loader import business, india

from . import registry
from .base_page import BasePage
from .context import ctx
from .registry import PageSpec, register_page
from .widgets import (Banner, Card, Col, ConfirmDialog, DataTable, Field, ImageLabel, StatePane, StatusChip, Timeline,
                      ValidatedForm, button, divider, hbox, icon, label, money, rating_badge, show_error, show_info)
from .worker import run_async

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"


def clear_layout(lay):
    while lay.count():
        item = lay.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


# ============================================================================ catalogue
class ProductCard(Card):
    """Brand, name, rating, price and stock note, then one action, as in the Figma card."""

    def __init__(self, p: dict, on_open, on_add, extra: str = ""):
        super().__init__(clickable=True, padding=0)
        self.setFixedWidth(232)
        self.lay.setSpacing(0)
        img = ImageLabel(QSize(230, 150))
        img.load((p.get("images") or [{}])[0].get("image") if p.get("images") else p.get("image"))
        img.setStyleSheet("border-bottom-left-radius:0; border-bottom-right-radius:0;")
        self.lay.addWidget(img)
        body = QVBoxLayout()
        body.setContentsMargins(14, 12, 14, 14)
        body.setSpacing(4)
        if p.get("brand"):
            body.addWidget(label(p["brand"], "Caption"))
        name = label(p["name"], "Strong", wrap=True)
        name.setFixedHeight(name.fontMetrics().lineSpacing() * 2 + 2)
        name.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        body.addWidget(name)
        if p.get("rating_count"):
            body.addLayout(hbox(rating_badge(p["rating_avg"]),
                                label(f"{group_number(p['rating_count'])} ratings", "Small"), None, spacing=6))
        elif extra:
            body.addWidget(label(extra, "Small"))
        else:
            body.addWidget(label("No ratings yet", "Small"))
        body.addWidget(label(money(p["price"]), "Price"))
        avail = p.get("available")
        note = label(" ", "Small")
        if avail is not None and avail <= 0:
            note = label("Out of stock", "Bad")
        elif avail is not None and avail <= business()["inventory"]["low_stock_threshold"]:
            note = label(f"Only {avail} left", "Warn")
        body.addWidget(note)
        body.addSpacing(6)
        if avail is not None and avail <= 0:
            add = button("Out of stock", "secondary")
            add.setEnabled(False)
        else:
            add = button("Add to cart", "secondary", None, lambda: on_add(p))
        if ctx().role != "CUSTOMER":
            add.setEnabled(False)
            add.setToolTip("Only customer accounts can buy")
        body.addWidget(add)
        self.lay.addLayout(body)
        self.clicked.connect(lambda: on_open(p))


def add_to_cart(parent, product_id: int, qty: int = 1, banner: Banner | None = None):
    def done(cart):
        ctx().bus.cart_changed.emit()
        msg = f"Added to cart · {cart['item_count']} item(s), total {money(cart['total'])}"
        banner.show_message(msg, "success") if banner else show_info(parent, "Cart", msg)

    def err(e):
        msg = str(e)
        if getattr(e, "code", "") == "out_of_stock":
            msg = f"Sorry — {msg}"
        banner.show_message(msg, "error") if banner else show_error(parent, e)
    run_async(lambda: ctx().api.post("cart/items/", {"product_id": product_id, "quantity": qty}), done, err)


class CatalogPage(BasePage):
    title = "All products"
    empty_text = "No products match these filters."
    empty_icon = "mdi6.magnify"

    def build(self):
        self.page_no = 1
        self.photo_results = None
        self.actions.addWidget(button("Search by photo", None, None, self.photo_search))
        row = QHBoxLayout()
        row.setSpacing(24)
        # Filter rail
        rail_host = QWidget()
        rail_host.setFixedWidth(220)
        rail = QVBoxLayout(rail_host)
        rail.setContentsMargins(0, 0, 0, 0)
        rail.setSpacing(8)

        def section(text):
            rail.addSpacing(10)
            rail.addWidget(label(text.upper(), "Overline"))

        self.search = QLineEdit()
        self.search.setPlaceholderText("Product or brand")
        self.search.returnPressed.connect(self.reload)
        self.search.setClearButtonEnabled(True)
        section("Search")
        rail.addWidget(self.search)
        section("Category")
        self.category = QComboBox()
        self.category.addItem("All categories", "")
        rail.addWidget(self.category)
        section("Price")
        sym = business()["currency_symbol"]
        self.min_price = QSpinBox()
        self.max_price = QSpinBox()
        for w, text in ((self.min_price, "Min"), (self.max_price, "Max")):
            w.setRange(0, 10_000_000)
            w.setSingleStep(500)
            w.setPrefix(f"{sym} ")
            w.setSpecialValueText(text)
            w.setGroupSeparatorShown(True)
            w.editingFinished.connect(self.reload)
        rail.addLayout(hbox(self.min_price, self.max_price))
        section("Availability")
        self.in_stock = QCheckBox("In stock only")
        rail.addWidget(self.in_stock)
        section("Sort by")
        self.sort = QComboBox()
        for text, v in (("Name", "name"), ("Price: low to high", "price"), ("Price: high to low", "-price"),
                        ("Newest first", "newest"), ("Customer rating", "rating")):
            self.sort.addItem(text, v)
        rail.addWidget(self.sort)
        rail.addStretch()
        for w in (self.category, self.sort):
            w.currentIndexChanged.connect(self.reload)
        self.in_stock.toggled.connect(self.reload)
        row.addWidget(rail_host, 0, Qt.AlignTop)
        # Results
        results = QVBoxLayout()
        results.setSpacing(12)
        self.count_lbl = label("", "Muted")
        results.addWidget(self.count_lbl)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(ctx().theme.cfg["spacing_px"])
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.grid_host)
        results.addWidget(sc, 1)
        pager = QHBoxLayout()
        self.page_info = label("", "Muted")
        self.prev = button("Previous", None, None, lambda: self.go(self.page_no - 1))
        self.next = button("Next", None, None, lambda: self.go(self.page_no + 1))
        pager.addWidget(self.page_info)
        pager.addStretch()
        pager.addWidget(self.prev)
        pager.addWidget(self.next)
        results.addLayout(pager)
        row.addLayout(results, 1)
        self.body_lay.addLayout(row, 1)
        self.categories_loaded = False

    def set_payload(self, payload):
        if isinstance(payload, dict) and "search" in payload:
            self.search.setText(payload["search"])
            self.photo_results = None
            self.page_no = 1

    def go(self, n):
        self.page_no = max(1, n)
        self.refresh()

    def reload(self):
        self.photo_results = None
        self.page_no = 1
        self.refresh()

    def params(self):
        p = {"page": self.page_no, "search": self.search.text().strip(), "category": self.category.currentData(),
             "sort": self.sort.currentData(), "page_size": business()["api"]["page_size"]}
        if self.min_price.value() > 0:
            p["min_price"] = self.min_price.value()
        if self.max_price.value() > 0:
            p["max_price"] = self.max_price.value()
        if self.in_stock.isChecked():
            p["in_stock"] = "true"
        return p

    def fetch(self):
        cats = None if self.categories_loaded else self.api.get("categories/")
        if self.photo_results is not None:
            return {"photo": self.photo_results, "categories": cats}
        return {"products": self.api.get("products/", self.params()), "categories": cats}

    def is_empty(self, data):
        return not (data.get("photo", {}).get("results") if "photo" in data else data["products"]["results"])

    def render(self, data):
        if data.get("categories"):
            for c in data["categories"]:
                self.category.addItem(c["name"], c["slug"])
            self.categories_loaded = True
        clear_layout(self.grid)
        if "photo" in data:
            res = data["photo"]
            self.set_title("Similar to your photo")
            self.banner.show_message("Closest matches to your photo.", "info")
            items = [{**r, "id": r["product_id"], "category_name": r["category"]} for r in res["results"]]
            extras = [f"{r['similarity']:.0%} visual match" for r in res["results"]]
            self.count_lbl.setText(f"{len(items)} matches")
            self.page_info.setText("")
            self.prev.setEnabled(False)
            self.next.setEnabled(False)
        else:
            self.banner.clear()
            page = data["products"]
            items, extras = page["results"], [""] * len(page["results"])
            size = business()["api"]["page_size"]
            pages = max(1, -(-page["count"] // size))
            q = self.search.text().strip()
            self.set_title(f"Results for “{q}”" if q else (self.category.currentText()
                           if self.category.currentData() else "All products"))
            start = (self.page_no - 1) * size + 1 if items else 0
            self.count_lbl.setText(f"Showing {start}–{start + len(items) - 1 if items else 0} of "
                                   f"{group_number(page['count'])}")
            self.page_info.setText(f"Page {self.page_no} of {pages}")
            self.prev.setEnabled(bool(page["previous"]))
            self.next.setEnabled(bool(page["next"]))
        cols = ctx().theme.cfg["catalog_columns"]
        for i, (p, extra) in enumerate(zip(items, extras)):
            self.grid.addWidget(ProductCard(p, self.open_product, lambda prod: add_to_cart(self, prod["id"], 1, self.banner),
                                            extra), i // cols, i % cols)

    def open_product(self, p):
        ProductDialog(self, p["id"]).exec()

    def photo_search(self):
        path, _ = QFileDialog.getOpenFileName(self, "Search by photo", "", IMAGE_FILTER)
        if path:
            self.run_photo_search(path)

    def run_photo_search(self, path: str):
        self.state.show_loading()

        def done(res):
            self.photo_results = res
            self.refresh()
        run_async(lambda: self.api.upload("search/photo/", path), done, self.state.show_error)


class ProductDialog(QDialog):
    def __init__(self, parent, product_id: int):
        super().__init__(parent)
        self.product_id = product_id
        self.setWindowTitle("Product")
        self.resize(1000, 760)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        self.content = QWidget()
        self.cl = QVBoxLayout(self.content)
        self.cl.setContentsMargins(0, 0, 0, 0)
        self.state = StatePane(self.content)
        self.state.retry.connect(self.load)
        lay.addWidget(self.state)
        self.load()

    def load(self):
        self.state.show_loading()
        api = ctx().api

        def fetch():
            out = {"p": api.get(f"products/{self.product_id}/"),
                   "reviews": api.get(f"products/{self.product_id}/reviews/"),
                   "insights": api.get(f"products/{self.product_id}/review-insights/")}
            try:
                out["similar"] = api.get(f"products/{self.product_id}/similar/")
            except Exception as e:  # recommender not trained: show why, keep the page usable
                out["similar_error"] = str(e)
            return out
        run_async(fetch, self.render, self.state.show_error)

    def render(self, d):
        self.state.show_content()
        clear_layout(self.cl)
        p = d["p"]
        self.setWindowTitle(p["name"])
        top = QHBoxLayout()
        top.setSpacing(28)
        img = ImageLabel(QSize(340, 300))
        img.load(p["images"][0]["image"] if p["images"] else None)
        top.addWidget(img, 0, Qt.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(6)
        if p.get("brand"):
            info.addWidget(label(p["brand"], "Brand"))
        info.addWidget(label(p["name"], "PageTitle", wrap=True))
        ins = d["insights"]
        if ins["average_rating"]:
            info.addLayout(hbox(rating_badge(ins["average_rating"]),
                                label(f"{group_number(ins['review_count'])} reviews", "Small"), None, spacing=6))
        else:
            info.addWidget(label("No reviews yet", "Small"))
        info.addSpacing(6)
        info.addWidget(divider())
        info.addSpacing(6)
        info.addWidget(label(money(p["price"]), "PriceLarge"))
        info.addWidget(label("Inclusive of all taxes", "Caption"))
        info.addSpacing(4)
        low = business()["inventory"]["low_stock_threshold"]
        if p["available"] <= 0:
            stock = label("Out of stock", "Bad")
        elif p["available"] <= low:
            stock = label(f"Only {p['available']} left", "Warn")
        else:
            stock = label("In stock", "Good")
        methods = business()["checkout"]["payment_methods"]
        cod = business()["checkout"]["cash_on_delivery_method"]
        info.addLayout(hbox(stock, label("· Cash on delivery available", "Muted") if cod in methods else None, None,
                            spacing=6))
        if ctx().role != "CUSTOMER":
            info.addWidget(label(f"SKU {p['sku']} · {p['category_name']}", "Caption"))
        self.banner = Banner()
        info.addWidget(self.banner)
        desc = label(p["description"], wrap=True)
        desc.setObjectName("Muted")
        info.addWidget(desc)
        buy = QHBoxLayout()
        buy.setSpacing(10)
        qty = QSpinBox()
        qty.setRange(1, max(1, p["available"]))
        qty.setPrefix("Qty ")
        add = button("Add to cart", "primary", None, lambda: add_to_cart(self, p["id"], qty.value(), self.banner))
        add.setMinimumWidth(180)
        add.setEnabled(p["available"] > 0)
        if ctx().role != "CUSTOMER":
            add.setEnabled(False)
            add.setToolTip("Only customer accounts can buy")
        buy.addWidget(qty)
        buy.addWidget(add)
        buy.addStretch()
        info.addSpacing(8)
        info.addLayout(buy)
        info.addStretch()
        top.addLayout(info, 1)
        self.cl.addLayout(top)
        self.cl.addSpacing(12)
        tabs = QTabWidget()
        tabs.addTab(self._reviews_tab(d), f"Reviews ({group_number(ins['review_count'])})")
        if ctx().role == "CUSTOMER":
            tabs.addTab(self._write_tab(), "Write a review")
        tabs.addTab(self._similar_tab(d), "Similar products")
        self.cl.addWidget(tabs, 1)

    def _reviews_tab(self, d):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(16)
        ins = d["insights"]
        left = Card()
        left.setFixedWidth(280)
        if ins["average_rating"]:
            left.lay.addLayout(hbox(label(f"{ins['average_rating']:.1f}", "StatValue"), label("out of 5", "Muted"), None))
        total = sum(ins["sentiment"].values()) or 1
        for k, text in (("positive", "Positive"), ("neutral", "Neutral"), ("negative", "Negative")):
            if ins["sentiment"].get(k):
                left.lay.addLayout(hbox(label(text, "Muted"), None, label(f"{ins['sentiment'][k] / total:.0%}")))
        left.lay.addSpacing(6)
        left.lay.addWidget(label("What buyers mention", "Strong"))
        tags = [(x["aspect"].capitalize(), "TagGood") for x in ins["pros"] if x["mentions"]] + \
               [(x["aspect"].capitalize(), "TagBad") for x in ins["cons"] if x["mentions"]]
        if not tags:
            left.lay.addWidget(label("Not enough reviews yet.", "Muted"))
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (text, obj) in enumerate(tags):
            grid.addWidget(label(text, obj), i // 2, i % 2, Qt.AlignLeft)
        left.lay.addLayout(grid)
        left.lay.addStretch()
        lay.addWidget(left)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        host = QWidget()
        hl = QVBoxLayout(host)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        reviews = d["reviews"]["results"]
        if not reviews:
            hl.addWidget(label("No reviews yet.", "Muted"))
        for r in reviews:
            c = Card(padding=14)
            c.lay.setSpacing(4)
            c.lay.addLayout(hbox(label(f"{r['rating']} ★", "RatingBadge"), label(r["title"] or "", "Strong"), None))
            c.lay.addWidget(label(r["body"], wrap=True))
            meta = [r["author"], format_date(r["created_at"])] + (["Verified purchase"] if r["verified_purchase"] else [])
            c.lay.addWidget(label(" · ".join(meta), "Caption"))
            hl.addWidget(c)
        hl.addStretch()
        sc.setWidget(host)
        lay.addWidget(sc, 1)
        return w

    def _write_tab(self):
        form = Card()
        self.rev_form = ValidatedForm([
            Field("rating", "Rating", "combo", required=True,
                  choices=[(f"{n} ★", n) for n in range(5, 0, -1)]), Field("title", "Headline"),
            Field("body", "Review", "multiline", required=True, placeholder="What did you like or dislike?")])
        self.rev_form.set_value("rating", 5)
        form.lay.addWidget(self.rev_form)
        form.lay.addLayout(hbox(None, button("Submit review", "primary", None, self.post_review)))
        form.lay.addStretch()
        return form

    def post_review(self):
        data = self.rev_form.validate()
        if not data:
            return
        run_async(lambda: ctx().api.post(f"products/{self.product_id}/reviews/", data), lambda _: self.load(),
                  lambda e: show_error(self, e))

    def _similar_tab(self, d):
        w = QWidget()
        lay = QHBoxLayout(w)
        if "similar_error" in d:
            lay.addWidget(label(d["similar_error"], "Muted", wrap=True))
            return w
        for s in d["similar"][:4]:
            c = ProductCard({**s, "id": s["product_id"], "category_name": ""},
                            lambda p: ProductDialog(self, p["id"]).exec(),
                            lambda p: add_to_cart(self, p["id"], 1, self.banner), s["reason"])
            lay.addWidget(c)
        lay.addStretch()
        return w


# ============================================================================ cart & checkout
class CartPage(BasePage):
    title = "Cart"
    empty_text = "Your cart is empty."
    empty_icon = "fa5s.shopping-cart"

    def build(self):
        row = QHBoxLayout()
        row.setSpacing(20)
        self.lines_card = Card()
        self.lines_title = label("Items", "H2")
        self.lines_card.lay.addWidget(self.lines_title)
        self.lines_lay = QVBoxLayout()
        self.lines_lay.setSpacing(12)
        self.lines_card.lay.addLayout(self.lines_lay)
        self.lines_card.lay.addStretch()
        row.addWidget(self.lines_card, 3, Qt.AlignTop)
        side = Card()
        side.setFixedWidth(360)
        side.lay.addWidget(label("Order summary", "H2"))
        self.summary = QVBoxLayout()
        self.summary.setSpacing(8)
        side.lay.addLayout(self.summary)
        code_row = QHBoxLayout()
        self.code = QLineEdit()
        self.code.setPlaceholderText("Coupon code")
        code_row.addWidget(self.code)
        code_row.addWidget(button("Apply", None, None, self.apply_code))
        side.lay.addLayout(code_row)
        self.code_msg = label("", "Good", wrap=True)
        side.lay.addWidget(self.code_msg)
        self.checkout_btn = button("Proceed to checkout", "primary", None, self.checkout)
        side.lay.addWidget(self.checkout_btn)
        self.reservation = label("", "Caption", wrap=True)
        side.lay.addWidget(self.reservation)
        row.addWidget(side, 0, Qt.AlignTop)
        self.body_lay.addLayout(row)
        self.body_lay.addStretch()
        self.state.empty_action.setText("Continue shopping")
        ctx().bus.cart_changed.connect(lambda: self.isVisible() and self.refresh())

    def fetch(self):
        return {"cart": self.api.get("cart/"), "reservation": self.api.get("checkout/reserve/")}

    def is_empty(self, data):
        return not data["cart"]["lines"]

    def refresh(self):
        super().refresh()

    def render(self, data):
        cart, res = data["cart"], data["reservation"]
        if not cart["lines"]:
            self.state.show_empty("Your cart is empty.", "Continue shopping", lambda: ctx().bus.navigate.emit("catalog", None))
            return
        clear_layout(self.lines_lay)
        self.lines_title.setText(f"Items ({cart['item_count']})")
        for i, l in enumerate(cart["lines"]):
            if i:
                self.lines_lay.addWidget(divider())
            r = QHBoxLayout()
            r.setSpacing(16)
            img = ImageLabel(QSize(88, 66))
            img.load(l["image"])
            r.addWidget(img, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addWidget(label(l["name"], "Strong", wrap=True))
            col.addWidget(label(f"{money(l['unit_price'])} each", "Small"))
            if l["stock_issue"]:
                col.addWidget(label(l["stock_issue"], "Bad", wrap=True))
            q = QSpinBox()
            q.setRange(0, max(l["quantity"], l["available"]))
            q.setValue(l["quantity"])
            q.setPrefix("Qty ")
            q.setFixedWidth(96)
            q.editingFinished.connect(lambda pid=l["product_id"], w=q: self.set_qty(pid, w.value()))
            col.addLayout(hbox(q, button("Remove", "ghost", None, lambda _=False, pid=l["product_id"]: self.set_qty(pid, 0)),
                               None))
            r.addLayout(col, 1)
            r.addWidget(label(money(l["line_total"]), "Strong"), 0, Qt.AlignTop)
            self.lines_lay.addLayout(r)
        clear_layout(self.summary)
        self.summary.addLayout(hbox(label(f"Items ({cart['item_count']})", "Muted"), None, label(money(cart["subtotal"]))))
        saved = 0
        for dsc in cart["discounts"]:
            saved += float(dsc["amount"])
            self.summary.addLayout(hbox(label(dsc["name"], "Muted"), None, label(f"−{money(dsc['amount'])}", "Good")))
        self.summary.addWidget(divider())
        self.summary.addLayout(hbox(label("Total", "Strong"), None, label(money(cart["total"]), "Price")))
        self.summary.addWidget(label("Inclusive of all taxes", "Caption"))
        self.code.setText(cart["discount_code"] or "")
        self.code_msg.setText(cart["message"] or (f"You save {money(saved)} on this order" if saved else ""))
        self.code_msg.setVisible(bool(self.code_msg.text()))
        if cart["removed_unavailable"]:
            self.banner.show_message("Removed items no longer sold: " + ", ".join(cart["removed_unavailable"]), "warning")
        elif cart["has_stock_issue"]:
            self.banner.show_message("Some items are out of stock. Update the quantities to continue.", "error")
        else:
            self.banner.clear()
        if res.get("status") == "EXPIRED":
            self.reservation.setText("Your earlier hold expired, so the items went back on sale.")
        elif res.get("status") == "ACTIVE":
            self.reservation.setText(f"Items held for you for {res['seconds_left'] // 60}:{res['seconds_left'] % 60:02d}")
        else:
            self.reservation.setText(f"We hold your items for {business()['reservations']['window_minutes']} minutes "
                                     "once you start checkout.")
        self.checkout_btn.setEnabled(not cart["has_stock_issue"])

    def set_qty(self, pid, qty):
        call = (lambda: self.api.delete(f"cart/items/{pid}/")) if qty == 0 else \
            (lambda: self.api.patch(f"cart/items/{pid}/", {"quantity": qty}))
        run_async(call, lambda _: self.refresh(), lambda e: self.banner.show_message(str(e), "error"))

    def apply_code(self):
        run_async(lambda: self.api.post("cart/discount-code/", {"code": self.code.text()}), lambda _: self.refresh(),
                  lambda e: self.banner.show_message(str(e), "error"))

    def checkout(self):
        dlg = CheckoutDialog(self)
        dlg.exec()
        self.refresh()


class CheckoutDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Checkout")
        self.setMinimumWidth(600)
        self.key = str(uuid.uuid4())  # one idempotency key per checkout attempt
        self.order = None
        co = business()["checkout"]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)
        lay.addWidget(label("Checkout", "PageTitle"))
        self.timer_lbl = label("Holding your items…", "Small")
        lay.addWidget(self.timer_lbl)
        self.banner = Banner()
        lay.addWidget(self.banner)
        lay.addSpacing(6)
        lay.addWidget(label("Delivery address", "H2"))
        self.ship = QComboBox()
        lay.addWidget(self.ship)
        self.same = QCheckBox("Billing address is the same")
        self.same.setChecked(True)
        self.bill = QComboBox()
        self.bill.setVisible(False)
        self.same.toggled.connect(lambda on: self.bill.setVisible(not on))
        lay.addWidget(self.same)
        lay.addWidget(self.bill)
        lay.addSpacing(6)
        lay.addWidget(label("Payment method", "H2"))
        self.method_group = QButtonGroup(self)
        for m in co["payment_methods"]:
            box = QVBoxLayout()
            box.setSpacing(0)
            rb = QRadioButton(co["payment_method_labels"].get(m, m))
            rb.setProperty("method", m)
            self.method_group.addButton(rb)
            box.addWidget(rb)
            hint = co.get("payment_method_hints", {}).get(m)
            if hint:
                h = label(hint, "Caption")
                h.setContentsMargins(26, 0, 0, 0)
                box.addWidget(h)
            lay.addLayout(box)
            rb.setChecked(m == co["payment_methods"][0])
        self.token = QComboBox()
        outcome_text = {"success": "Payment succeeds", "declined": "Card declined",
                        "insufficient_funds": "Insufficient funds"}
        for outcome, toks in business()["payments"]["sandbox_tokens"].items():
            for t in toks:
                self.token.addItem(f"{outcome_text.get(outcome, outcome.replace('_', ' ').capitalize())} ({t})", t)
        self.token_row = QWidget()
        tr = QHBoxLayout(self.token_row)
        tr.setContentsMargins(0, 4, 0, 0)
        tr.addWidget(label("Test payment outcome", "Small"))
        tr.addWidget(self.token, 1)
        lay.addWidget(self.token_row)
        self.method_group.buttonToggled.connect(lambda *_: self.token_row.setVisible(is_prepaid(self.method())))
        lay.addSpacing(8)
        lay.addWidget(divider())
        self.total = label("", "Price")
        lay.addLayout(hbox(label("Total", "Strong"), None, self.total))
        lay.addWidget(label("Inclusive of all taxes", "Caption"))
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("Back to cart", None, None, self.reject))
        self.place = button("Place order", "primary", None, self.place_order)
        self.place.setEnabled(False)
        row.addWidget(self.place)
        lay.addSpacing(6)
        lay.addLayout(row)
        self.countdown = QTimer(self)
        self.countdown.timeout.connect(self.tick)
        self.seconds_left = 0
        self.start()

    def method(self):
        b = self.method_group.checkedButton()
        return b.property("method") if b else None

    def start(self):
        api = ctx().api

        def fetch():
            return {"addresses": api.get("addresses/"), "reservation": api.post("checkout/reserve/"),
                    "cart": api.get("cart/")}

        def done(d):
            for a in d["addresses"]:
                text = f"{a['full_name']}, {a['line1']}, {a['city']} {a['postal_code']}"
                self.ship.addItem(text, a["id"])
                self.bill.addItem(text, a["id"])
            self.total.setText(money(d["cart"]["total"]))
            self.place.setText(f"Place order · {money(d['cart']['total'])}")
            if not d["addresses"]:
                self.banner.show_message("Add a delivery address under Account first.", "warning")
                return
            self.seconds_left = d["reservation"]["seconds_left"]
            self.countdown.start(1000)
            self.tick()
            self.place.setEnabled(True)

        def err(e):
            if getattr(e, "code", "") == "out_of_stock":
                items = ", ".join(f"product #{s['product_id']}: {s['available']} available" for s in e.data.get("shortages", []))
                self.banner.show_message(f"Some items just sold out ({items}). Update your cart.", "error")
            else:
                self.banner.show_message(str(e), "error")
            self.timer_lbl.setText("")
        run_async(fetch, done, err)

    def tick(self):
        self.seconds_left -= 1
        if self.seconds_left <= 0:
            self.countdown.stop()
            self.timer_lbl.setText("Your hold on these items expired. Go back to the cart and check out again.")
            self.timer_lbl.setObjectName("Bad")
            self.timer_lbl.style().polish(self.timer_lbl)
            return
        self.timer_lbl.setText(f"Items held for you for {self.seconds_left // 60}:{self.seconds_left % 60:02d}")

    def place_order(self):
        body = {"shipping_address_id": self.ship.currentData(), "payment_method": self.method(),
                "billing_address_id": None if self.same.isChecked() else self.bill.currentData()}
        if is_prepaid(self.method()):
            body["payment_token"] = self.token.currentData()
        self.place.setEnabled(False)

        def done(order):
            self.order = order
            self.countdown.stop()
            self.timer_lbl.setText("")
            act = order.get("next_action")
            if order.get("payment_error"):
                self.banner.show_message(f"Order #{order['id']} was created but the payment failed: "
                                         f"{order['payment_error']['message']} You can pay again from Orders.", "error")
            elif act == "verify_otp":
                self.banner.show_message("Please confirm this order with the code we sent to your notifications.", "warning")
                OtpDialog(self, order["id"]).exec()
            elif act == "await_review":
                self.banner.show_message(f"Order #{order['id']} is placed. We're doing a quick check before it ships.",
                                         "warning")
            else:
                self.banner.show_message(f"Order #{order['id']} placed. "
                                         f"Status: {ctx().theme.status_label(order['status'])}.", "success")
            ctx().bus.cart_changed.emit()

        def err(e):
            code = getattr(e, "code", "")
            if code == "reservation_expired":
                self.banner.show_message("Your hold on these items expired. Go back to the cart and check out again.",
                                         "error")
            elif code == "out_of_stock":
                self.banner.show_message("Some items sold out while you were checking out. Update your cart.", "error")
            else:
                self.banner.show_message(str(e), "error")
                self.place.setEnabled(True)
        run_async(lambda: ctx().api.post("checkout/", body, headers={"Idempotency-Key": self.key}), done, err)


class OtpDialog(QDialog):
    def __init__(self, parent, order_id: int):
        super().__init__(parent)
        self.order_id = order_id
        self.setWindowTitle("Verify your order")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.addWidget(label("Confirm your order", "H2"))
        lay.addWidget(label("Enter the code we sent to your notifications.", "Muted", wrap=True))
        self.banner = Banner()
        lay.addWidget(self.banner)
        self.code = QLineEdit()
        self.code.setPlaceholderText("6-digit code")
        lay.addWidget(self.code)
        lay.addLayout(hbox(button("Resend code", "ghost", None, self.resend), None,
                           button("Confirm", "primary", None, self.verify)))

    def verify(self):
        run_async(lambda: ctx().api.post(f"orders/{self.order_id}/verify-otp/", {"code": self.code.text()}),
                  lambda o: (show_info(self, "Order confirmed", f"Order #{o['id']} is confirmed."),
                             self.accept()),
                  lambda e: self.banner.show_message(str(e), "error"))

    def resend(self):
        run_async(lambda: ctx().api.post(f"orders/{self.order_id}/resend-otp/"),
                  lambda r: self.banner.show_message(r["detail"], "info"), lambda e: self.banner.show_message(str(e), "error"))


# ============================================================================ orders
class OrdersPage(BasePage):
    title = "Your orders"
    empty_text = "You have no orders yet."
    empty_icon = "fa5s.receipt"

    def build(self):
        self.page_no, self.page_size = 1, None
        split = QSplitter()
        self.table = DataTable([Col("id", "Order", "id", 90), Col("created_at", "Placed", "date", 120),
                                Col("status", "Status", "status", 170), Col("item_count", "Items", "int", 70),
                                Col("total", "Total", "money")])
        self.table.page_requested.connect(self.go)
        self.table.selected.connect(lambda r: self.open_order(r["id"]))
        split.addWidget(self.table)
        self.detail = Card()
        self.detail_body = QVBoxLayout()
        self.detail.lay.addLayout(self.detail_body)
        self.detail_body.addWidget(label("Select an order to see the details.", "Muted"))
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.detail)
        split.addWidget(sc)
        split.setSizes([520, 560])
        self.body_lay.addWidget(split, 1)

    def go(self, page, size):
        self.page_no, self.page_size = max(1, page), size
        self.refresh()

    def fetch(self):
        return self.api.get("orders/", {"page": self.page_no, "page_size": self.page_size or self.table.page_size})

    def is_empty(self, data):
        return data["count"] == 0

    def render(self, data):
        self.table.set_rows(data["results"], data["count"], self.page_no)

    def set_payload(self, order_id):
        self.pending_open = order_id

    def open_order(self, order_id):
        run_async(lambda: self.api.get(f"orders/{order_id}/"), self.show_order, lambda e: self.banner.show_message(str(e), "error"))

    def show_order(self, o):
        clear_layout(self.detail_body)
        labels = business()["checkout"]["payment_method_labels"]
        self.detail_body.addLayout(hbox(label(f"Order #{o['id']}", "H2"), StatusChip(o["status"]), None))
        self.detail_body.addWidget(label(f"Placed {format_datetime(o['created_at'])} · "
                                         f"{labels.get(o['payment_method'], o['payment_method'])}", "Small"))
        self.detail_body.addSpacing(6)
        for it in o["items"]:
            row = hbox(label(f"{it['name']}", "Strong"), label(f"× {it['quantity']}", "Muted"), None,
                       label(money(it["line_total"])))
            if o["status"] == "DELIVERED":
                row.addWidget(button("Check item photo", "secondary", None,
                                     lambda _=False, i=it: SnapCheckDialog(self, i).exec()))
            self.detail_body.addLayout(row)
        self.detail_body.addWidget(divider())
        if float(o["discount_total"]):
            self.detail_body.addLayout(hbox(label("Discount", "Muted"), None, label(f"−{money(o['discount_total'])}", "Good")))
        self.detail_body.addLayout(hbox(label("Total", "Strong"), None, label(money(o["total"]), "Price")))
        ship = o["shipping_address"]
        lines = [ship.get("full_name"), ship.get("line1"), ship.get("line2"),
                 " ".join(x for x in (ship.get("city"), ship.get("postal_code")) if x), ship.get("phone")]
        self.detail_body.addSpacing(6)
        self.detail_body.addWidget(label("Delivery address", "Strong"))
        self.detail_body.addWidget(label("\n".join(x for x in lines if x), "Muted", wrap=True))
        actions = QHBoxLayout()
        allowed = o["allowed_transitions"]
        if o["status"] == "PENDING" and is_prepaid(o["payment_method"]):
            actions.addWidget(button("Pay now", "primary", None, lambda: self.pay(o)))
        if o["status"] == "VERIFICATION_REQUIRED":
            actions.addWidget(button("Enter code", "primary", None,
                                     lambda: (OtpDialog(self, o["id"]).exec(), self.open_order(o["id"]), self.refresh())))
        if o["status"] == "ON_HOLD":
            self.detail_body.addWidget(label("We're doing a quick check on this order and will update you soon.",
                                             "Muted", wrap=True))
        if "RETURN_REQUESTED" in allowed:
            actions.addWidget(button("Return items", "secondary", None, lambda: self.request_return(o)))
        if "CANCELLED" in allowed:
            actions.addWidget(button("Cancel order", "danger", None, lambda: self.cancel(o)))
        actions.addStretch()
        self.detail_body.addSpacing(6)
        self.detail_body.addLayout(actions)
        self.detail_body.addSpacing(10)
        self.detail_body.addWidget(label("Order history", "Strong"))
        self.detail_body.addWidget(Timeline(o["history"]))
        self.detail_body.addStretch()

    def pay(self, o):
        token = business()["payments"]["sandbox_tokens"]["success"][0]
        key = str(uuid.uuid4())
        run_async(lambda: self.api.post(f"orders/{o['id']}/pay/", {"payment_method": o["payment_method"], "payment_token": token},
                                        headers={"Idempotency-Key": key}),
                  lambda r: (self.banner.show_message("Payment received.", "success"), self.refresh(),
                             self.open_order(o["id"])),
                  lambda e: self.banner.show_message(f"Payment didn't go through: {e}", "error"))

    def cancel(self, o):
        if ConfirmDialog.ask(self, "Cancel order", f"Cancel order #{o['id']}? Any amount paid is refunded to the original "
                             "payment method.", "Cancel order", True):
            run_async(lambda: self.api.post(f"orders/{o['id']}/cancel/", {"reason": "Cancelled by customer"}),
                      lambda r: (self.refresh(), self.show_order(r)), lambda e: self.banner.show_message(str(e), "error"))

    def request_return(self, o):
        if ConfirmDialog.ask(self, "Return items", f"Request a return for order #{o['id']}?", "Request return"):
            run_async(lambda: self.api.post(f"orders/{o['id']}/return/", {"reason": "Requested in app"}),
                      lambda r: (self.refresh(), self.show_order(r)), lambda e: self.banner.show_message(str(e), "error"))


class SnapCheckDialog(QDialog):
    def __init__(self, parent, item: dict):
        super().__init__(parent)
        self.item = item
        self.setWindowTitle("Check item photo")
        self.setMinimumSize(560, 340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.addWidget(label("Check your delivery", "H2"))
        lay.addWidget(label(f"Upload a photo of the {item['name']} you received. We'll compare it with the "
                            "product photo.", "Muted", wrap=True))
        self.banner = Banner()
        lay.addWidget(self.banner)
        self.result = QVBoxLayout()
        lay.addLayout(self.result)
        lay.addLayout(hbox(None, button("Close", None, None, self.reject),
                           button("Upload photo", "primary", None, self.choose)))

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "Photo of the received item", "", IMAGE_FILTER)
        if path:
            self.submit(path)

    def submit(self, path: str):
        self.banner.show_message("Comparing photos…", "info")

        def done(r):
            kind = {"MATCH": "success", "UNCERTAIN": "warning", "MISMATCH": "error"}[r["verdict"]]
            msg = {"MATCH": "This matches the item you ordered.",
                   "UNCERTAIN": "We couldn't confirm a match. Our team may contact you.",
                   "MISMATCH": "This doesn't look like the item you ordered. We've passed it to our team as a priority."}
            self.banner.show_message(msg[r["verdict"]], kind)
            clear_layout(self.result)
            self.result.addLayout(hbox(StatusChip(r["verdict"]), label(f"{r['similarity']:.0%} similar", "Strong"), None))
        run_async(lambda: ctx().api.upload("snapchecks/", path, extra={"order_item_id": self.item["id"]}), done,
                  lambda e: self.banner.show_message(str(e), "error"))


# ============================================================================ profile & notifications
class ProfilePage(BasePage):
    title = "Your account"
    scrollable = True

    def build(self):
        row = QHBoxLayout()
        row.setSpacing(20)
        card = Card()
        card.lay.addWidget(label("Your details", "H2"))
        self.form = ValidatedForm([Field("first_name", "First name", required=True), Field("last_name", "Last name"),
                                   Field("phone", "Mobile number", pattern=india()["mobile_pattern"],
                                         message="Enter a valid 10-digit mobile number.", placeholder="+91 98765 43210")])
        card.lay.addWidget(self.form)
        card.lay.addLayout(hbox(button("Save changes", "primary", None, self.save), None))
        card.lay.addSpacing(10)
        card.lay.addWidget(label("Password", "H2"))
        self.pw = ValidatedForm([Field("old_password", "Current password", "password", required=True),
                                 Field("new_password", "New password", "password", required=True,
                                       validator=lambda v, d: None if len(v) >= 8 else "Use at least 8 characters.")])
        card.lay.addWidget(self.pw)
        card.lay.addLayout(hbox(button("Change password", None, None, self.change_pw), None))
        card.lay.addStretch()
        row.addWidget(card, 1)
        addr = Card()
        addr.lay.addLayout(hbox(label("Saved addresses", "H2"), None,
                                button("Add address", "secondary", None, lambda: self.edit_address(None))))
        self.addr_list = QVBoxLayout()
        addr.lay.addLayout(self.addr_list)
        addr.lay.addStretch()
        row.addWidget(addr, 1)
        self.body_lay.addLayout(row)

    def fetch(self):
        return {"me": self.api.get("auth/me/"), "addresses": self.api.get("addresses/")}

    def render(self, d):
        self.form.set_values(d["me"])
        clear_layout(self.addr_list)
        if not d["addresses"]:
            self.addr_list.addWidget(label("No saved addresses yet.", "Muted"))
        for a in d["addresses"]:
            c = Card(padding=14)
            c.lay.setSpacing(2)
            head = hbox(label(a["full_name"], "Strong"), label(a["label"], "Tag"),
                        label("Default", "Tag") if a["is_default"] else None, None,
                        button("Edit", "ghost", None, lambda _=False, a=a: self.edit_address(a)),
                        button("Delete", "ghost", None, lambda _=False, a=a: self.delete_address(a)))
            c.lay.addLayout(head)
            place = ", ".join(x for x in (a["city"], a["state"]) if x)
            lines = [a["line1"], a["line2"], f"{place} {a['postal_code']}".strip(), a["phone"]]
            c.lay.addWidget(label("\n".join(x for x in lines if x), "Muted", wrap=True))
            self.addr_list.addWidget(c)

    def save(self):
        data = self.form.validate()
        if data:
            run_async(lambda: self.api.patch("auth/me/", data), lambda _: self.banner.show_message("Profile saved.", "success"),
                      lambda e: (self.form.set_server_errors(getattr(e, "data", {}).get("errors")), self.banner.show_message(str(e), "error")))

    def change_pw(self):
        data = self.pw.validate()
        if data:
            run_async(lambda: self.api.post("auth/change-password/", data),
                      lambda _: self.banner.show_message("Password updated.", "success"),
                      lambda e: (self.pw.set_server_errors(getattr(e, "data", {}).get("errors")), self.banner.show_message(str(e), "error")))

    def edit_address(self, a):
        dlg = AddressDialog(self, a)
        if dlg.exec():
            self.refresh()

    def delete_address(self, a):
        if ConfirmDialog.ask(self, "Delete address", f"Delete this address ({a['label']})?", "Delete", True):
            run_async(lambda: self.api.delete(f"addresses/{a['id']}/"), lambda _: self.refresh(),
                      lambda e: self.banner.show_message(str(e), "error"))


class AddressDialog(QDialog):
    """Indian address form: PIN code, state list and mobile number are checked here and again by the API."""

    def __init__(self, parent, a: dict | None):
        super().__init__(parent)
        self.a = a
        places = india()
        self.setWindowTitle("Edit address" if a else "Add address")
        self.setMinimumWidth(600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)
        lay.addWidget(label("Edit address" if a else "Add a new address", "H2"))
        self.banner = Banner()
        lay.addWidget(self.banner)
        states = [("Select state", "")] + [(x, x) for x in places["states_and_union_territories"]]
        self.form = ValidatedForm([
            Field("full_name", "Full name", required=True), Field("phone", "Mobile number", required=True,
                                                                 pattern=places["mobile_pattern"],
                                                                 message="Enter a valid 10-digit mobile number.",
                                                                 placeholder="+91 98765 43210"),
            Field("line1", "Flat, house no., building", required=True, placeholder="Flat 302, Gulmohar Heights"),
            Field("line2", "Area, street, locality", placeholder="80 Feet Road, Koramangala"),
            Field("postal_code", "PIN code", required=True, pattern=places["pin_code_pattern"],
                  message="Enter a valid 6-digit PIN code.", placeholder="560034"),
            Field("city", "Town or city", required=True),
            Field("state", "State", "combo", required=True, choices=states),
            Field("label", "Address type", "combo", required=True,
                  choices=[("Home", "Home"), ("Work", "Work"), ("Other", "Other")]),
        ], columns=2)
        lay.addWidget(self.form)
        self.default = QCheckBox("Make this my default address")
        lay.addWidget(self.default)
        if a:
            self.form.set_values(a)
            self.default.setChecked(a["is_default"])
        lay.addSpacing(6)
        lay.addLayout(hbox(None, button("Cancel", None, None, self.reject), button("Save address", "primary", None, self.save)))

    def save(self):
        data = self.form.validate()
        if not data:
            return
        data["postal_code"] = data["postal_code"].replace(" ", "")
        data["country"] = india()["country"]
        data["is_default"] = self.default.isChecked()
        api = ctx().api
        call = (lambda: api.patch(f"addresses/{self.a['id']}/", data)) if self.a else (lambda: api.post("addresses/", data))
        run_async(call, lambda _: self.accept(), lambda e: (self.form.set_server_errors(getattr(e, "data", {}).get("errors")),
                                                          self.banner.show_message(str(e), "error")))


class NotificationsPage(BasePage):
    title = "Notifications"
    empty_text = "You're all caught up."
    empty_icon = "fa5s.bell-slash"
    scrollable = True

    def build(self):
        self.list = QVBoxLayout()
        self.body_lay.addLayout(self.list)
        self.body_lay.addStretch()

    def fetch(self):
        return self.api.get("notifications/", {"page_size": business()["api"]["page_size"]})

    def is_empty(self, d):
        return not d["results"]

    def render(self, d):
        clear_layout(self.list)
        icons = {"otp": "fa5s.key", "order_status": "fa5s.truck", "order_on_hold": "fa5s.pause-circle",
                 "low_stock": "fa5s.boxes", "snapcheck_mismatch": "fa5s.camera", "discount_drafts": "fa5s.tags"}
        for n in d["results"]:
            c = Card(padding=12)
            ic = label()
            ic.setPixmap(icon(icons.get(n["kind"], "fa5s.bell"), "primary" if n["status"] != "READ" else "subtle").pixmap(18, 18))
            body = QVBoxLayout()
            body.setSpacing(2)
            body.addWidget(label(n["title"], "Strong"))
            body.addWidget(label(n["body"], "Muted", wrap=True))
            body.addWidget(label(format_datetime(n["created_at"]), "Caption"))
            row = QHBoxLayout()
            row.addWidget(ic, 0, Qt.AlignTop)
            row.addLayout(body, 1)
            if n["status"] != "READ":
                row.addWidget(button("Mark as read", "ghost", None,
                                     lambda _=False, nid=n["id"]: run_async(lambda: self.api.post(f"notifications/{nid}/read/"),
                                                                           lambda _: self.refresh())), 0, Qt.AlignTop)
            c.lay.addLayout(row)
            self.list.addWidget(c)


register_page(PageSpec("catalog", "Storefront", "fa5s.store", registry.ALL, CatalogPage, "Store", 10))
register_page(PageSpec("cart", "Cart", "fa5s.shopping-cart", registry.CUSTOMER, CartPage, "Store", 20))
register_page(PageSpec("orders", "Orders", "fa5s.receipt", registry.CUSTOMER, OrdersPage, "Store", 30))
register_page(PageSpec("profile", "Profile", "fa5s.user", registry.ALL, ProfilePage, "Account", 900))
register_page(PageSpec("notifications", "Notifications", "fa5s.bell", registry.ALL, NotificationsPage, "Account", 910))
