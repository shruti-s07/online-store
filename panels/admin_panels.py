"""Admin panels: users & roles, discount manager, sales dashboard, review moderation.
Each panel registers itself into the shell's sidebar (no edits to the main window)."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit,
                               QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from backend.shared.formatting import group_number
from backend.shared.roles import Role
from ui.folder_a_shell import registry
from ui.folder_a_shell.base_page import BasePage
from ui.folder_a_shell.context import ctx
from ui.folder_a_shell.pages_customer import clear_layout
from ui.folder_a_shell.registry import PageSpec, register_page
from ui.folder_a_shell.widgets import (Banner, Card, Col, ConfirmDialog, DataTable, Field, StatCard, StatusChip,
                                       ValidatedForm, button, hbox, label, money)
from ui.folder_a_shell.worker import run_async

from .charts import Chart


def export_report(parent, banner, name: str, params: dict, fmt: str):
    path, _ = QFileDialog.getSaveFileName(parent, f"Export {name}", f"{name}.{fmt}", f"{fmt.upper()} (*.{fmt})")
    if not path:
        return

    def save(data):
        with open(path, "wb") as fh:
            fh.write(data)
        banner.show_message(f"Saved {path}", "success")
    run_async(lambda: ctx().api.download(f"reports/{name}/", {**params, "export": fmt}), save,
              lambda e: banner.show_message(str(e), "error"))


# ============================================================================ users
class UsersPage(BasePage):
    title = "Users and roles"

    def build(self):
        self.page_no, self.sel = 1, None
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by email")
        self.search.returnPressed.connect(lambda: self.go(1, 0))
        self.role_filter = QComboBox()
        self.role_filter.addItem("All roles", "")
        for r in Role:
            self.role_filter.addItem(r.value.title(), r.value)
        self.role_filter.currentIndexChanged.connect(lambda: self.go(1, 0))
        bar.addWidget(self.search, 2)
        bar.addWidget(self.role_filter, 1)
        self.body_lay.addLayout(bar)
        row = QHBoxLayout()
        self.table = DataTable([Col("id", "ID", "id", 60), Col("email", "Email"), Col("first_name", "First name"),
                                Col("last_name", "Last name"), Col("role", "Role", "status", 110),
                                Col("active", "Active", "status", 100), Col("date_joined", "Joined", "date")])
        self.table.page_requested.connect(self.go)
        self.table.selected.connect(self.select)
        row.addWidget(self.table, 3)
        edit = Card()
        edit.setFixedWidth(300)
        edit.lay.addWidget(label("Edit user", "H2"))
        self.who = label("Select a user", "Muted", wrap=True)
        edit.lay.addWidget(self.who)
        self.role = QComboBox()
        for r in Role:
            self.role.addItem(r.value.title(), r.value)
        self.active = QCheckBox("Account active")
        edit.lay.addWidget(label("Role"))
        edit.lay.addWidget(self.role)
        edit.lay.addWidget(self.active)
        self.save_btn = button("Save changes", "primary", "fa5s.save", self.save)
        self.save_btn.setEnabled(False)
        edit.lay.addWidget(self.save_btn)
        edit.lay.addStretch()
        row.addWidget(edit)
        self.body_lay.addLayout(row, 1)

    def go(self, page, _size):
        self.page_no = max(1, page)
        self.refresh()

    def fetch(self):
        return self.api.get("admin/users/", {"page": self.page_no, "page_size": self.table.page_size,
                                             "search": self.search.text().strip(), "role": self.role_filter.currentData()})

    def render(self, d):
        rows = [{**r, "active": "VISIBLE" if r["is_active"] else "HIDDEN"} for r in d["results"]]
        self.table.set_rows(rows, d["count"], self.page_no)

    def select(self, r):
        self.sel = r
        self.who.setText(r["email"])
        self.role.setCurrentIndex(self.role.findData(r["role"]))
        self.active.setChecked(r["is_active"])
        self.save_btn.setEnabled(True)

    def save(self):
        body = {"role": self.role.currentData(), "is_active": self.active.isChecked()}
        if ConfirmDialog.ask(self, "Change user", f"Set {self.sel['email']} to {body['role']}"
                             f"{'' if body['is_active'] else ' (deactivated)'}?", "Save"):
            run_async(lambda: self.api.patch(f"admin/users/{self.sel['id']}/", body),
                      lambda _: (self.banner.show_message("User updated.", "success"), self.refresh()),
                      lambda e: self.banner.show_message(str(e), "error"))


# ============================================================================ discounts
class DiscountsPage(BasePage):
    title = "Discounts"
    scrollable = False

    def build(self):
        self.actions.addWidget(button("Find slow movers", "accent", "fa5s.search-dollar", self.suggest))
        self.actions.addWidget(button("New rule", "primary", "fa5s.plus", self.new_rule))
        self.tabs = QTabWidget()
        drafts = QWidget()
        dl = QVBoxLayout(drafts)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        host = QWidget()
        self.drafts = QGridLayout(host)
        self.drafts.setSpacing(ctx().theme.cfg["spacing_px"])
        sc.setWidget(host)
        dl.addWidget(sc)
        self.tabs.addTab(drafts, "Drafts to review")
        self.rules = DataTable([Col("id", "ID", "id", 60), Col("name", "Name"), Col("code", "Code", width=110),
                                Col("action_text", "Discount", width=110), Col("status", "Status", "status", 110),
                                Col("source", "Source", width=100), Col("times_used", "Used", "int", 70),
                                Col("ends_at", "Ends", "date", 110)], paginated=False)
        self.tabs.addTab(self.rules, "All rules")
        self.body_lay.addWidget(self.tabs, 1)

    def fetch(self):
        from config.loader import business
        return self.api.get("discounts/rules/", {"page_size": business()["api"]["max_page_size"]})

    def render(self, d):
        rules = d["results"]
        for r in rules:
            a = r["action"]
            r["action_text"] = f"{a['value']}%" if a["type"] == "percent" else money(a["value"])
        self.rules.set_rows(rules)
        clear_layout(self.drafts)
        drafts = [r for r in rules if r["status"] == "DRAFT"]
        self.tabs.setTabText(0, f"Drafts to review ({len(drafts)})")
        if not drafts:
            self.drafts.addWidget(label("No drafts to review. Use Find slow movers to check stock.", "Muted"), 0, 0)
        for i, r in enumerate(drafts):
            self.drafts.addWidget(self._draft_card(r), i // 2, i % 2)

    def _draft_card(self, r):
        c = Card()
        c.lay.addLayout(hbox(label(r["name"], "H2", wrap=True), None, StatusChip(r["status"])))
        x = r.get("rationale") or {}
        if x:
            el = x.get("elasticity", {})
            grid = QGridLayout()
            facts = [("In stock", group_number(x.get("stock") or 0)), ("Sells per day", x.get("forecast_daily")),
                     ("Days of stock", x.get("days_of_cover")),
                     ("Days of stock after", x.get("expected_days_of_cover_after")),
                     ("Price", money(x.get("price"))), ("New price", money(x.get("new_price"))),
                     ("Cost", money(x.get("cost"))), ("Max discount", f"{x.get('margin_cap', 0):.0%}"),
                     ("Price elasticity", f"{el.get('elasticity')} ({el.get('n_promotions')} past sales)")]
            for i, (k, v) in enumerate(facts):
                grid.addWidget(label(k, "Muted"), i // 3 * 2, i % 3)
                grid.addWidget(label(str(v)), i // 3 * 2 + 1, i % 3)
            c.lay.addLayout(grid)
            c.lay.addWidget(label(f"Estimated from the {el.get('method', '')}", "Caption", wrap=True))
        c.lay.addLayout(hbox(None, button("Reject", "danger", None, lambda: self.decide(r, "reject")),
                             button("Approve", "primary", None, lambda: self.decide(r, "approve"))))
        return c

    def decide(self, r, what):
        if ConfirmDialog.ask(self, f"{what.title()} discount", f"{what.title()} “{r['name']}”?", what.title(),
                             danger=what == "reject"):
            run_async(lambda: self.api.post(f"discounts/rules/{r['id']}/{what}/", {}),
                      lambda _: (self.banner.show_message(f"Rule {what}d.", "success"), self.refresh()),
                      lambda e: self.banner.show_message(str(e), "error"))

    def suggest(self):
        run_async(lambda: self.api.post("discounts/rules/suggest/"),
                  lambda created: (self.banner.show_message(f"{len(created)} new draft(s) created.", "info"), self.refresh()),
                  lambda e: self.banner.show_message(str(e), "error"))

    def new_rule(self):
        if RuleDialog(self).exec():
            self.refresh()


class RuleDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("New discount rule")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.addWidget(label("New discount rule", "PageTitle"))
        lay.addWidget(label("New rules start as drafts and must be approved.", "Muted"))
        self.banner = Banner()
        lay.addWidget(self.banner)
        self.form = ValidatedForm([
            Field("name", "Name", required=True), Field("code", "Code (empty = automatic)", pattern=r"^[A-Za-z0-9]{3,20}$",
                                                         message="3-20 letters or digits."),
            Field("type", "Type", "combo", choices=[("Percent off", "percent"), ("Fixed amount off", "fixed")]),
            Field("value", "Value", "decimal", required=True, minimum=0.01,
                  validator=lambda v, d: "Percent must be ≤ 100." if d["type"] == "percent" and v > 100 else None),
            Field("min_subtotal", "Minimum subtotal", "decimal", minimum=0),
            Field("min_quantity", "Minimum items", "int", minimum=0)], columns=2)
        lay.addWidget(self.form)
        lay.addLayout(hbox(None, button("Cancel", None, None, self.reject), button("Create draft", "primary", "fa5s.save", self.save)))

    def save(self):
        d = self.form.validate()
        if not d:
            return
        cond = {k: d[k] for k in ("min_subtotal", "min_quantity") if d[k]}
        body = {"name": d["name"], "code": d["code"] or None, "conditions": cond,
                "action": {"type": d["type"], "value": d["value"]}}
        run_async(lambda: ctx().api.post("discounts/rules/", body), lambda _: self.accept(),
                  lambda e: self.banner.show_message(str(e), "error"))


# ============================================================================ dashboard
class DashboardPage(BasePage):
    title = "Dashboard"
    scrollable = True

    def build(self):
        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        from config.loader import business
        self.days.setValue(business()["reports"]["default_lookback_days"])
        self.days.setPrefix("Last ")
        self.days.setSuffix(" days")
        self.period = QComboBox()
        for p in ("day", "week", "month"):
            self.period.addItem({"day": "Daily", "week": "Weekly", "month": "Monthly"}[p], p)
        self.actions.addWidget(self.days)
        self.actions.addWidget(self.period)
        self.actions.addWidget(button("Refresh", None, None, self.refresh))
        self.stats = QHBoxLayout()
        self.body_lay.addLayout(self.stats)
        g = QGridLayout()
        g.setSpacing(ctx().theme.cfg["spacing_px"])
        self.trend, self.cats, self.status, self.top = Chart(3.2), Chart(3.2), Chart(3.0), Chart(3.0)
        for i, (chart, name) in enumerate(((self.trend, "sales_by_period"), (self.cats, "sales_by_category"),
                                           (self.status, "order_status_counts"), (self.top, "top_products"))):
            card = Card()
            card.lay.addWidget(chart)
            card.lay.addLayout(hbox(None, button("Export CSV", "ghost", None, lambda _=False, n=name: self.export(n, "csv")),
                                    button("Export PDF", "ghost", None, lambda _=False, n=name: self.export(n, "pdf"))))
            g.addWidget(card, i // 2, i % 2)
        self.body_lay.addLayout(g)

    def params(self):
        return {"days": self.days.value(), "period": self.period.currentData()}

    def export(self, name, fmt):
        export_report(self, self.banner, name, self.params(), fmt)

    def fetch(self):
        p = self.params()
        get = lambda n: self.api.get(f"reports/{n}/", p)
        return {n: get(n) for n in ("revenue_summary", "sales_by_period", "sales_by_category", "order_status_counts",
                                     "top_products")}

    def render(self, d):
        clear_layout(self.stats)
        rows = dict((r[0], r[1]) for r in d["revenue_summary"]["rows"])
        rupees = lambda v: money(round(float(v)))  # noqa: E731 - KPI tiles show whole rupees
        for title, key, fmt in (("Revenue", "Revenue", rupees), ("Orders", "Orders", group_number),
                                ("Average order value", "Average order value", rupees),
                                ("Units sold", "Units sold", group_number)):
            self.stats.addWidget(StatCard(title, fmt(rows.get(key, 0))))
        sp = d["sales_by_period"]
        self.trend.line(sp["title"], [r[0] for r in sp["rows"]], {"Revenue": [float(r[1]) for r in sp["rows"]]}, money=True)
        sc = d["sales_by_category"]
        self.cats.bar(sc["title"], [r[0] for r in sc["rows"]], [float(r[1]) for r in sc["rows"]], horizontal=True, money=True)
        st = d["order_status_counts"]
        self.status.bar(st["title"], [ctx().theme.status_label(r[0]) for r in st["rows"]], [r[1] for r in st["rows"]])
        tp = d["top_products"]
        self.top.bar(tp["title"], [r[1][:26] for r in tp["rows"]], [float(r[3]) for r in tp["rows"]], horizontal=True,
                     money=True)


# ============================================================================ review moderation
class ModerationPage(BasePage):
    title = "Reviews"
    subtitle = "Flagged reviews are listed first."
    empty_text = "No reviews in this queue."
    empty_icon = "fa5s.comment-slash"

    def build(self):
        self.page_no, self.sel = 1, None
        bar = QHBoxLayout()
        self.status = QComboBox()
        for s in ("FLAGGED", "VISIBLE", "HIDDEN", "ALL"):
            self.status.addItem(s.title(), s)
        self.status.currentIndexChanged.connect(lambda: self.go(1, 0))
        bar.addWidget(label("Show", "Muted"))
        bar.addWidget(self.status)
        bar.addStretch()
        self.approve = button("Publish", "primary", None, lambda: self.moderate("VISIBLE"))
        self.hide = button("Hide", "danger", "fa5s.eye-slash", lambda: self.moderate("HIDDEN"))
        for b in (self.approve, self.hide):
            b.setEnabled(False)
            bar.addWidget(b)
        self.body_lay.addLayout(bar)
        self.table = DataTable([Col("id", "ID", "id", 60), Col("product_name", "Product"), Col("rating", "Rating", "int", 70),
                                Col("body", "Review"), Col("fake_score", "Spam score", "float", 100),
                                Col("reasons", "Signals"), Col("sentiment", "Sentiment", width=90),
                                Col("status", "Status", "status", 100)])
        self.table.page_requested.connect(self.go)
        self.table.selected.connect(self.select)
        self.body_lay.addWidget(self.table, 1)

    def go(self, page, _):
        self.page_no = max(1, page)
        self.refresh()

    def fetch(self):
        return self.api.get("reviews/moderation/", {"status": self.status.currentData(), "page": self.page_no,
                                                    "page_size": self.table.page_size})

    def is_empty(self, d):
        return d["count"] == 0

    def render(self, d):
        rows = [{**r, "reasons": ", ".join(x.replace("_", " ") for x in r["fake_reasons"])} for r in d["results"]]
        self.table.set_rows(rows, d["count"], self.page_no)

    def select(self, r):
        self.sel = r
        self.approve.setEnabled(r["status"] != "VISIBLE")
        self.hide.setEnabled(r["status"] != "HIDDEN")

    def moderate(self, status):
        run_async(lambda: self.api.post(f"reviews/moderation/{self.sel['id']}/moderate/", {"status": status}),
                  lambda _: (self.banner.show_message(f"Review #{self.sel['id']} is now {ctx().theme.status_label(status).lower()}.", "success"), self.refresh()),
                  lambda e: self.banner.show_message(str(e), "error"))


register_page(PageSpec("dashboard", "Dashboard", "fa5s.chart-line", registry.BACK_OFFICE, DashboardPage, "Overview", 5))
register_page(PageSpec("moderation", "Reviews", "fa5s.comments", registry.BACK_OFFICE, ModerationPage, "Catalogue", 54))
register_page(PageSpec("discounts", "Discounts", "fa5s.tags", registry.ADMIN, DiscountsPage, "Sales", 25))
register_page(PageSpec("users", "Users and roles", "fa5s.users-cog", registry.ADMIN, UsersPage, "Admin", 80))
