"""Whitelisted report functions. The Reports API and the natural-language analytics both call
these; nothing else (and never raw SQL) is reachable from a question.

Each function returns {"title", "columns", "rows", "chart"}.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Callable

from django.db.models import Avg, Count, DecimalField, F, Max, Sum
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from backend.folder_one_core.catalog.models import Product
from backend.folder_one_core.inventory.services import availability_map
from backend.folder_one_core.orders.models import Order, OrderItem
from backend.shared.order_states import REVENUE_STATES
from config.loader import business

REVENUE = [s.value for s in REVENUE_STATES]
TRUNC = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}


def _since(days: int):
    return timezone.now() - timedelta(days=int(days))


def _days(days):
    return int(days or business()["reports"]["default_lookback_days"])


def _limit(limit):
    return int(limit or business()["reports"]["top_n"])


def revenue_summary(days=None, **_):
    d = _days(days)
    qs = Order.objects.filter(created_at__gte=_since(d), status__in=REVENUE)
    agg = qs.aggregate(revenue=Sum("total"), orders=Count("id"), aov=Avg("total"))
    units = OrderItem.objects.filter(order__in=qs).aggregate(u=Sum("quantity"))["u"] or 0
    rev_str = f"{Decimal(str(agg['revenue'])):.2f}" if agg["revenue"] is not None else "0.00"
    rows = [["Revenue", rev_str], ["Orders", agg["orders"]],
            ["Average order value", str(round(agg["aov"] or 0, 2))], ["Units sold", units]]
    return {"title": f"Revenue summary, last {d} days", "columns": ["Metric", "Value"], "rows": rows, "chart": None}


def sales_by_period(period=None, days=None, **_):
    period = period if period in TRUNC else business()["reports"]["default_period"]
    d = _days(days)
    rows = (Order.objects.filter(created_at__gte=_since(d), status__in=REVENUE)
            .annotate(p=TRUNC[period]("created_at")).values("p")
            .annotate(revenue=Sum("total"), orders=Count("id")).order_by("p"))
    data = [[r["p"].date().isoformat(), str(r["revenue"]), r["orders"]] for r in rows]
    return {"title": f"Sales by {period}, last {d} days", "columns": [period.title(), "Revenue", "Orders"],
            "rows": data, "chart": {"type": "line", "x": 0, "y": 1}}


def sales_by_category(days=None, **_):
    d = _days(days)
    rows = (OrderItem.objects.filter(order__created_at__gte=_since(d), order__status__in=REVENUE)
            .values(cat=F("product__category__name"))
            .annotate(revenue=Sum("line_total"), units=Sum("quantity"),
                      margin=Sum(F("line_total") - F("unit_cost") * F("quantity"), output_field=DecimalField()))
            .order_by("-revenue"))
    data = [[r["cat"], str(r["revenue"]), r["units"], str(round(r["margin"], 2))] for r in rows]
    return {"title": f"Sales by category, last {d} days", "columns": ["Category", "Revenue", "Units", "Gross margin"],
            "rows": data, "chart": {"type": "bar", "x": 0, "y": 1}}


def top_products(days=None, limit=None, category=None, **_):
    d = _days(days)
    qs = OrderItem.objects.filter(order__created_at__gte=_since(d), order__status__in=REVENUE)
    if category:
        qs = qs.filter(product__category__name__iexact=category) | qs.filter(product__category__slug=category)
    rows = (qs.values("product__sku", "product__name").annotate(units=Sum("quantity"), revenue=Sum("line_total"))
            .order_by("-revenue")[: _limit(limit)])
    data = [[r["product__sku"], r["product__name"], r["units"], str(r["revenue"])] for r in rows]
    return {"title": f"Top products, last {d} days" + (f" ({category})" if category else ""),
            "columns": ["SKU", "Product", "Units", "Revenue"], "rows": data, "chart": {"type": "bar", "x": 1, "y": 3}}


def low_stock(threshold=None, **_):
    t = int(threshold if threshold is not None else business()["inventory"]["low_stock_threshold"])
    products = list(Product.objects.select_related("category"))
    avail = availability_map([p.id for p in products])
    rows = sorted([[p.sku, p.name, p.category.name, avail[p.id]["on_hand"], avail[p.id]["reserved"],
                    avail[p.id]["available"]] for p in products if avail[p.id]["available"] <= t], key=lambda r: r[5])
    return {"title": f"Low stock (available <= {t})",
            "columns": ["SKU", "Product", "Category", "On hand", "Reserved", "Available"], "rows": rows, "chart": None}


def order_status_counts(days=None, **_):
    d = _days(days)
    rows = (Order.objects.filter(created_at__gte=_since(d)).values("status").annotate(n=Count("id")).order_by("-n"))
    return {"title": f"Orders by status, last {d} days", "columns": ["Status", "Orders"],
            "rows": [[r["status"], r["n"]] for r in rows], "chart": {"type": "bar", "x": 0, "y": 1}}


def customer_report(days=None, limit=None, **_):
    d = _days(days)
    rows = (Order.objects.filter(created_at__gte=_since(d), status__in=REVENUE).values("user__email", "user_id")
            .annotate(orders=Count("id"), revenue=Sum("total"), aov=Avg("total"), last=Max("created_at"))
            .order_by("-revenue")[: _limit(limit)])
    from backend.folder_two_services.segmentation.models import CustomerSegment
    seg = dict(CustomerSegment.objects.filter(user_id__in=[r["user_id"] for r in rows]).values_list("user_id", "segment"))
    data = [[r["user__email"], r["orders"], str(r["revenue"]), str(round(r["aov"], 2)), r["last"].date().isoformat(),
             seg.get(r["user_id"], "")] for r in rows]
    return {"title": f"Top customers, last {d} days",
            "columns": ["Customer", "Orders", "Revenue", "Avg order", "Last order", "Segment"], "rows": data,
            "chart": {"type": "bar", "x": 0, "y": 2}}


def segment_summary(**_):
    from backend.folder_two_services.segmentation.models import CustomerSegment
    rows = (CustomerSegment.objects.values("segment")
            .annotate(customers=Count("id"), avg_recency=Avg("recency_days"), avg_frequency=Avg("frequency"),
                      avg_monetary=Avg("monetary")).order_by("segment"))
    data = [[r["segment"], r["customers"], round(r["avg_recency"], 1), round(r["avg_frequency"], 1),
             str(round(r["avg_monetary"], 2))] for r in rows]
    return {"title": "Customer segments", "columns": ["Segment", "Customers", "Avg recency (days)",
                                                      "Avg orders", "Avg spend"], "rows": data,
            "chart": {"type": "pie", "x": 0, "y": 1}}


def order_history(days=None, status=None, limit=None, user=None, **_):
    d = _days(days)
    qs = Order.objects.filter(created_at__gte=_since(d)).select_related("user")
    if user is not None:
        qs = qs.filter(user=user)
    if status:
        qs = qs.filter(status=status)
    qs = qs.annotate(n_items=Coalesce(Sum("items__quantity"), 0)).order_by("-created_at")[: _limit(limit) * 10]
    return {"title": f"Order history, last {d} days",
            "columns": ["Order", "Date", "Customer", "Status", "Items", "Total"],
            "rows": [[o.id, o.created_at.strftime("%Y-%m-%d %H:%M"), o.user.email, o.status, o.n_items, str(o.total)]
                     for o in qs], "chart": None}


@dataclass(frozen=True)
class ReportSpec:
    fn: Callable
    description: str
    params: tuple[str, ...]


REPORTS: dict[str, ReportSpec] = {
    "revenue_summary": ReportSpec(revenue_summary, "Total revenue, orders, average order value, units", ("days",)),
    "sales_by_period": ReportSpec(sales_by_period, "Revenue and orders per day/week/month", ("period", "days")),
    "sales_by_category": ReportSpec(sales_by_category, "Revenue, units and margin per category", ("days",)),
    "top_products": ReportSpec(top_products, "Best-selling products", ("days", "limit", "category")),
    "low_stock": ReportSpec(low_stock, "Products at or below the low-stock threshold", ("threshold",)),
    "order_status_counts": ReportSpec(order_status_counts, "Number of orders per status", ("days",)),
    "customer_report": ReportSpec(customer_report, "Top customers by revenue", ("days", "limit")),
    "segment_summary": ReportSpec(segment_summary, "Customer segments overview", ()),
    "order_history": ReportSpec(order_history, "Recent orders", ("days", "status", "limit")),
}


def run_report(name: str, **params) -> dict:
    spec = REPORTS[name]
    clean = {k: v for k, v in params.items() if k in spec.params and v not in (None, "")}
    result = spec.fn(**clean)
    result["report"] = name
    result["params"] = clean
    return result
