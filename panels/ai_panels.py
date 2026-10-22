"""AI panels: customer segments, restock suggestions, shopping assistant chat, natural-language
analytics, AI insights. Each registers itself into the shell's sidebar."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QScrollArea, QSplitter, QVBoxLayout, QWidget

from backend.shared.formatting import MONEY_COLUMNS, format_datetime, group_number
from config.loader import business
from ui.folder_a_shell import registry
from ui.folder_a_shell.base_page import BasePage
from ui.folder_a_shell.context import ctx
from ui.folder_a_shell.pages_customer import clear_layout
from ui.folder_a_shell.registry import PageSpec, register_page
from ui.folder_a_shell.widgets import (Card, Col, ConfirmDialog, DataTable, StatCard, StatusChip, button, hbox, icon,
                                       label, money)
from ui.folder_a_shell.worker import run_async

from .charts import Chart

SEGMENT_STYLE = {"loyal": ("fa5s.heart", "primary"), "big_spenders": ("fa5s.gem", "accent"),
                 "new": ("fa5s.seedling", "success"), "at_risk": ("fa5s.exclamation-triangle", "warning")}


class SegmentsPage(BasePage):
    title = "Customer segments"
    empty_text = "No segments yet. Run python store.py train."

    def build(self):
        self.cards = QHBoxLayout()
        self.body_lay.addLayout(self.cards)
        row = QSplitter()
        self.chart = Chart(3.2)
        c = Card()
        c.lay.addWidget(self.chart)
        row.addWidget(c)
        self.table = DataTable([Col("email", "Customer"),
                                Col("segment", "Segment", width=120, fmt=lambda v: str(v).replace("_", " ").capitalize()),
                                Col("recency_days", "Days since order", "int", 130), Col("frequency", "Orders", "int", 70),
                                Col("monetary", "Spend", "money", 130, fmt=lambda v: money(round(float(v)))), Col("tenure_days", "Days as customer", "int", 130)])
        self.table.page_requested.connect(self.load_customers)
        row.addWidget(self.table)
        row.setSizes([380, 700])
        self.body_lay.addWidget(row, 1)
        self.segment = ""

    def fetch(self):
        return {"summary": self.api.get("segments/summary/"),
                "customers": self.api.get("segments/customers/", {"segment": self.segment, "page_size": self.table.page_size})}

    def is_empty(self, d):
        return not d["summary"]["segments"]

    def render(self, d):
        clear_layout(self.cards)
        segs = d["summary"]["segments"]
        for s in segs:
            ic, col = SEGMENT_STYLE.get(s["segment"], ("fa5s.users", "info"))
            card = StatCard(ctx().theme.status_label(s["segment"].upper()), group_number(s["customers"]), ic, col,
                            f"Avg spend {money(round(s['monetary']))} · {s['frequency']:.0f} orders · "
                            f"last order {s['recency_days']:.0f} days ago")
            card.setProperty("clickable", "true")
            card.clicked.connect(lambda name=s["segment"]: self.filter(name))
            self.cards.addWidget(card)
        self.chart.pie("Customers per segment", [ctx().theme.status_label(s["segment"].upper()) for s in segs],
                       [s["customers"] for s in segs])
        self.table.set_rows(d["customers"]["results"], d["customers"]["count"], 1)
        meta = d["summary"]["model"]
        if meta.get("metrics"):
            self.banner.show_message(f"{group_number(d['summary']['customers_without_orders'])} customers haven't "
                                     "ordered yet. Click a segment to filter the list.", "info")

    def filter(self, name):
        self.segment = "" if self.segment == name else name
        self.load_customers(1, self.table.page_size)

    def load_customers(self, page, size):
        run_async(lambda: self.api.get("segments/customers/", {"segment": self.segment, "page": max(1, page), "page_size": size}),
                  lambda d: self.table.set_rows(d["results"], d["count"], max(1, page)),
                  lambda e: self.banner.show_message(str(e), "error"))


class RestockPage(BasePage):
    title = "Restock"
    empty_text = "Nothing needs restocking right now."
    empty_icon = "fa5s.check-circle"

    def build(self):
        split = QSplitter(Qt.Vertical)
        one_dp = lambda v: f"{float(v):.1f}"  # noqa: E731
        self.table = DataTable([Col("sku", "SKU", width=90), Col("name", "Product"),
                                Col("available", "In stock", "int", 80),
                                Col("avg_daily_demand", "Sells per day", "float", 100, fmt=one_dp),
                                Col("lead_time_days", "Lead time", "int", 80),
                                Col("safety_stock", "Safety stock", "float", 100, fmt=one_dp),
                                Col("reorder_point", "Reorder at", "float", 90, fmt=one_dp),
                                Col("days_of_cover", "Days of stock", "float", 100, fmt=one_dp),
                                Col("suggested_order_qty", "Order", "int", 70),
                                Col("model", "Forecast model", width=130,
                                    fmt=lambda v: str(v).replace("_", " ").capitalize())],
                               paginated=False)
        self.table.selected.connect(self.show_forecast)
        split.addWidget(self.table)
        c = Card()
        self.chart = Chart(2.6)
        self.chart.empty("Demand forecast", "Select a product to see its history and forecast")
        c.lay.addWidget(self.chart)
        split.addWidget(c)
        split.setSizes([420, 300])
        self.body_lay.addWidget(split, 1)

    def fetch(self):
        return self.api.get("forecasting/restock/")

    def is_empty(self, d):
        return not d["results"]

    def render(self, d):
        self.table.set_rows(d["results"])
        n = len(d["results"])
        self.banner.show_message(f"{n} {'product needs' if n == 1 else 'products need'} restocking. "
                                 f"Forecasts cover the next {d['horizon_days']} days.", "warning" if n else "success")
        if d["results"]:
            self.show_forecast(d["results"][0])

    def show_forecast(self, row):
        def done(f):
            hist, fc = f["history"], [p["units"] for p in f["forecast"]]
            x = list(range(-len(hist), 0)) + list(range(len(fc)))
            self.chart.line(f"{f['name']} — {f['model'].replace('_', ' ')} (backtest WAPE "
                            f"{f['backtest']['evaluation_wape']:.2f})", [str(v) for v in x],
                            {"History": hist, "Forecast": [None] * len(hist) + fc}, dashed={"Forecast"})
        run_async(lambda: self.api.get(f"forecasting/products/{row['product_id']}/"), done,
                  lambda e: self.chart.empty("Demand forecast", str(e)))


class ChatPanel(BasePage):
    """Shared chat UI for the shopping assistant (customers) and NL analytics (staff)."""

    endpoint = "assistant/chat/"
    channel = "assistant"
    examples: list[str] = []
    placeholder = "Type a question"

    def build(self):
        self.engine = label("", "Caption")
        self.actions.addWidget(self.engine)
        # Engine/intent details help staff judge answers; customers don't need them
        self.engine.setVisible(self.channel != "assistant")
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        host = QWidget()
        self.msgs = QVBoxLayout(host)
        self.msgs.setSpacing(10)
        self.msgs.addStretch()
        sc.setWidget(host)
        self.scroll = sc
        self.body_lay.addWidget(sc, 1)
        ex = QHBoxLayout()
        for e in self.examples:
            ex.addWidget(button(e, "secondary", None, lambda _=False, t=e: self.send(t)))
        ex.addStretch()
        self.body_lay.addLayout(ex)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(self.placeholder)
        self.input.returnPressed.connect(lambda: self.send(self.input.text()))
        row.addWidget(self.input, 1)
        self.send_btn = button("Send", "primary", "fa5s.paper-plane", lambda: self.send(self.input.text()))
        row.addWidget(self.send_btn)
        self.body_lay.addLayout(row)

    def fetch(self):
        return {"status": self.api.get("assistant/status/"),
                "history": self.api.get("assistant/history/", {"channel": self.channel})}

    def render(self, d):
        self.engine.setText(f"Engine: {d['status']['engine']}")
        while self.msgs.count() > 1:
            item = self.msgs.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        if not d["history"]:
            self.bubble("bot", self.greeting)
        for m in d["history"]:
            self.bubble("user" if m["role"] == "user" else "bot", m["content"])

    def bubble(self, who, text, extra: QWidget | None = None):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        b = label(text, "ChatBubbleUser" if who == "user" else "ChatBubbleBot", wrap=True)
        b.setTextInteractionFlags(Qt.TextSelectableByMouse)
        b.setMaximumWidth(720)
        longest = max((len(line) for line in text.splitlines()), default=0)
        b.setMinimumWidth(min(640, 40 + 8 * longest))
        col = QVBoxLayout()
        col.addWidget(b)
        if extra:
            col.addWidget(extra)
        if who == "user":
            row.addStretch()
            row.addLayout(col)
        else:
            ic = label()
            ic.setPixmap(icon("fa5s.robot", "primary").pixmap(22, 22))
            row.addWidget(ic, 0, Qt.AlignTop)
            row.addLayout(col)
            row.addStretch()
        self.msgs.addWidget(w)
        QTimer.singleShot(50, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    def send(self, text):
        text = text.strip()
        if not text:
            return
        self.input.clear()
        self.bubble("user", text)
        self.send_btn.setEnabled(False)
        run_async(lambda: self.api.post(self.endpoint, {"message": text}), self.on_reply,
                  lambda e: self.bubble("bot", f"⚠ {e}"), lambda on: self.send_btn.setEnabled(not on))

    def on_reply(self, r):
        self.engine.setText(f"Engine: {r['engine']}" + (f" · intent {r['intent']} ({r['confidence']:.0%})"
                                                        if r.get("intent") else ""))
        self.bubble("bot", r["reply"], self.extra_for(r))

    def extra_for(self, r):
        a = r.get("pending_action")
        if not a:
            return None
        c = Card(padding=10)
        c.lay.addWidget(label("Please confirm", "Strong"))
        c.lay.addWidget(label(a["summary"], wrap=True))
        status = label("", "Muted")
        confirm = button("Confirm", "primary", "fa5s.check")
        cancel = button("Cancel", None, "fa5s.times")

        def finish(text):
            status.setText(text)
            confirm.setEnabled(False)
            cancel.setEnabled(False)

        def do_confirm():
            if ConfirmDialog.ask(self, "Confirm action", a["summary"] + "?", "Confirm"):
                run_async(lambda: self.api.post(f"assistant/actions/{a['id']}/confirm/"),
                          lambda res: (finish(f"Done ✓ ({res['status'].lower()})"
                                              + (f": {res['result'].get('error')}" if res["status"] == "FAILED" else "")),
                                       ctx().bus.cart_changed.emit()),
                          lambda e: finish(f"⚠ {e}"))
        confirm.clicked.connect(do_confirm)
        cancel.clicked.connect(lambda: run_async(lambda: self.api.post(f"assistant/actions/{a['id']}/cancel/"),
                                                 lambda _: finish("Cancelled — nothing was changed."),
                                                 lambda e: finish(f"⚠ {e}")))
        c.lay.addLayout(hbox(cancel, confirm, None))
        c.lay.addWidget(status)
        return c


class AssistantPage(ChatPanel):
    title = "Assistant"
    subtitle = "Changes to your cart or orders always ask you to confirm."
    endpoint = "assistant/chat/"
    channel = "assistant"
    greeting = "I can find products, suggest items, update your cart and check your orders."
    examples = ["earbuds under 2000", "what do you recommend", "where is my order", "what is in my cart"]
    placeholder = "Ask about products, your cart or an order"


class AnalyticsPage(ChatPanel):
    title = "Ask the data"
    endpoint = "assistant/analytics/"
    channel = "analytics"
    greeting = "Ask about revenue, categories, top products, stock, orders or customer segments."
    placeholder = "For example: revenue last 30 days"
    examples = ["revenue last 30 days", "sales by category this month", "top 5 products", "what is running low"]

    def extra_for(self, r):
        data = r.get("data")
        if not data or not data.get("rows"):
            return super().extra_for(r)
        c = Card(padding=10)
        cols = [Col(str(i), h, "money" if h in MONEY_COLUMNS else "text") for i, h in enumerate(data["columns"])]
        t = DataTable(cols, paginated=False)
        t.set_rows([{str(i): v for i, v in enumerate(row)} for row in data["rows"]])
        t.setMinimumHeight(min(320, 60 + 40 * len(data["rows"])))
        chart_spec = data.get("chart")
        if chart_spec and len(data["rows"]) > 1:
            ch = Chart(2.6)
            x = [str(row[chart_spec["x"]]) for row in data["rows"]]
            y = [float(row[chart_spec["y"]]) for row in data["rows"]]
            is_money = data["columns"][chart_spec["y"]] in MONEY_COLUMNS
            {"line": lambda: ch.line(data["title"], x, {data["columns"][chart_spec["y"]]: y}, money=is_money),
             "bar": lambda: ch.bar(data["title"], [s[:24] for s in x], y, horizontal=True, money=is_money),
             "pie": lambda: ch.pie(data["title"], x, y)}[chart_spec["type"]]()
            c.lay.addWidget(ch)
        c.lay.addWidget(label(data["title"], "Strong"))
        c.lay.addWidget(t)
        c.setMinimumWidth(720)
        return c


class InsightsPage(BasePage):
    title = "Model health"
    subtitle = "Scores are measured on synthetic data."
    scrollable = True

    HEADLINES = {
        "fraud": [("Average precision", "avg_precision_model", "avg_precision_baseline_rules"),
                  ("ROC AUC", "roc_auc_model", "roc_auc_baseline_rules")],
        "sentiment": [("Accuracy", "accuracy_model", "accuracy_baseline_majority"),
                      ("Macro F1", "macro_f1_model", "macro_f1_baseline_majority")],
        "forecasting": [("WAPE (lower is better)", "wape_best_per_product", "wape_moving_average")],
        "segmentation": [("Silhouette", "silhouette_kmeans", "silhouette_baseline_rules")],
        "recommendations": [("NDCG@10", "ndcg_at_10_hybrid", "ndcg_at_10_baseline_popularity"),
                            ("Precision@10", "precision_at_10_hybrid", "precision_at_10_baseline_popularity")],
        "intents": [("Accuracy (unseen phrasing)", "accuracy_model_channel_aware", "accuracy_baseline_keywords")],
        "snapcheck": [("ROC AUC", "roc_auc", None), ("Photo search top-1", "photo_search_top1", "photo_search_top1_baseline_random")],
    }

    def build(self):
        if ctx().role == "ADMIN":
            self.actions.addWidget(button("Retrain now", "accent", "fa5s.brain", self.retrain))
        self.top = QHBoxLayout()
        self.body_lay.addLayout(self.top)
        self.grid = QGridLayout()
        self.grid.setSpacing(ctx().theme.cfg["spacing_px"])
        self.body_lay.addLayout(self.grid)
        self.body_lay.addWidget(label("Orders on hold", "H2"))
        self.held = DataTable([Col("id", "Order", "id", 80), Col("customer", "Customer"), Col("risk_score", "Score", "int", 70),
                               Col("reasons", "Signals"), Col("total", "Total", "money")], paginated=False)
        self.held.setMinimumHeight(200)
        self.body_lay.addWidget(self.held)
        self.body_lay.addWidget(label("Background jobs", "H2"))
        self.jobs = DataTable([Col("name", "Job"), Col("status", "Status", "status", 110), Col("started_at", "Started", "datetime"),
                               Col("finished_at", "Finished", "datetime"), Col("detail_text", "Result")], paginated=False)
        self.jobs.setMinimumHeight(240)
        self.body_lay.addWidget(self.jobs)

    def fetch(self):
        return {"models": self.api.get("ai/models/"), "risk": self.api.get("risk/overview/"),
                "jobs": self.api.get("jobs/runs/", {"page_size": business()["api"]["page_size"]})}

    def render(self, d):
        m = d["models"]
        clear_layout(self.top)
        self.top.addWidget(StatCard("Assistant engine", m["assistant_engine"], "fa5s.robot", "primary"))
        clip = "CLIP" in m["image_embedding"] and "fallback" not in m["image_embedding"]
        emb = StatCard("Photo matching", "CLIP" if clip else "Built-in fallback", "fa5s.camera",
                       "success" if clip else "warning", m["image_embedding"])
        emb.setToolTip(m["image_embedding"])
        self.top.addWidget(emb)
        lv = d["risk"]["by_level"]
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        self.top.addWidget(StatCard("Risk-scored orders", group_number(sum(lv.values())), "fa5s.shield-alt", "danger",
                                    " · ".join(f"{ctx().theme.status_label(k)} {group_number(v)}"
                                               for k, v in sorted(lv.items(), key=lambda kv: order.get(kv[0], 9)))))
        clear_layout(self.grid)
        for i, (name, rows) in enumerate(self.HEADLINES.items()):
            meta = m["models"].get(name)
            c = Card()
            c.lay.addLayout(hbox(label(name.title(), "H2"), None, StatusChip("APPROVED" if meta else "DRAFT")))
            if not meta:
                c.lay.addWidget(label("Not trained yet — run python store.py train", "Muted", wrap=True))
            else:
                for title, a, b in rows:
                    mv, bv = meta["metrics"].get(a), meta["metrics"].get(b) if b else None
                    txt = f"{mv:.3f}" if isinstance(mv, (int, float)) else "—"
                    if isinstance(bv, (int, float)):
                        txt += f"   vs baseline {bv:.3f}"
                    c.lay.addWidget(label(title, "Muted"))
                    c.lay.addWidget(label(txt, "H2"))
                c.lay.addWidget(label(f"Trained {format_datetime(meta['trained_at'])}", "Caption", wrap=True))
            self.grid.addWidget(c, i // 3, i % 3)
        self.held.set_rows([{**o, "reasons": ", ".join(o["reasons"] or [])} for o in d["risk"]["on_hold"]])
        self.jobs.set_rows([{**j, "detail_text": ", ".join(f"{k}: {v}" for k, v in (j["detail"] or {}).items()
                                                           if k not in ("trace",))[:120]} for j in d["jobs"]["results"]])
        self.banner.clear()

    def retrain(self):
        if ConfirmDialog.ask(self, "Retrain models", "Run the nightly training job now? It takes about a minute.", "Retrain"):
            run_async(lambda: self.api.post("jobs/nightly_training/run/"),
                      lambda r: self.banner.show_message("Training started. Refresh this page in about a minute.", "info"),
                      lambda e: self.banner.show_message(str(e), "error"))


register_page(PageSpec("assistant", "Assistant", "fa5s.robot", registry.CUSTOMER, AssistantPage, "Store", 40))
register_page(PageSpec("analytics", "Ask the data", "fa5s.comment-dots", registry.BACK_OFFICE, AnalyticsPage, "Overview", 6))
register_page(PageSpec("segments", "Customer segments", "fa5s.users", registry.BACK_OFFICE, SegmentsPage, "Insights", 60))
register_page(PageSpec("restock", "Restock", "fa5s.warehouse", registry.BACK_OFFICE, RestockPage, "Catalogue", 52))
register_page(PageSpec("insights", "Model health", "fa5s.brain", registry.BACK_OFFICE, InsightsPage, "Insights", 62))
