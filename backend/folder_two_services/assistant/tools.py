"""Tools the assistant may call. Every tool runs as the logged-in user, with that user's
permissions; data-changing tools are never executed without an explicit confirmation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from django.db.models import Q

from backend.folder_one_core.cart import services as cart
from backend.folder_one_core.catalog.models import Product
from backend.folder_one_core.inventory.services import availability_map
from backend.folder_one_core.orders.models import Order
from backend.folder_one_core.orders.services import transition
from backend.folder_two_services.reports.functions import REPORTS, run_report
from backend.shared.errors import DomainError
from backend.shared.order_states import OrderStatus
from backend.shared.roles import BACK_OFFICE_ROLES, Role
from config.loader import business


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    roles: frozenset
    channel: str
    fn: Callable
    mutating: bool = field(default=False)

    def allowed(self, user) -> bool:
        return Role(user.role) in self.roles

    def anthropic_spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


STOPWORDS = {"show", "me", "find", "a", "an", "the", "any", "some", "do", "you", "have", "i", "am", "looking", "for",
             "need", "new", "under", "below", "dollars", "cheap", "available", "what", "items", "sell", "search",
             "products", "something", "in", "to", "my", "cart", "add", "buy", "please", "of", "this", "bag", "basket",
             "put", "want", "remove", "delete", "from", "take", "out", "anymore", "not", "dont", "with", "less", "than",
             "and", "is", "are", "it", "one", "items", "get", "where", "can", "price", "priced", "cost"}


def _product_rows(products) -> list[dict]:
    avail = availability_map([p.id for p in products])
    return [{"product_id": p.id, "name": p.name, "price": str(p.price), "category": p.category.name,
             "available": avail[p.id]["available"]} for p in products]


def search_products(user, query: str = "", max_price: float | None = None, category: str | None = None) -> dict:
    words = [w for w in query.lower().replace(",", " ").split() if w not in STOPWORDS and len(w) > 1]
    qs = Product.objects.select_related("category")
    if category:
        qs = qs.filter(Q(category__name__iexact=category) | Q(category__slug__iexact=category))
    if max_price:
        qs = qs.filter(price__lte=max_price)
    if words:
        cond = Q()
        for w in words:
            stem = w[:-1] if w.endswith("s") and len(w) > 3 else w
            cond |= Q(name__icontains=stem) | Q(brand__icontains=stem) | Q(category__name__icontains=stem)
        qs = qs.filter(cond)
        products = sorted(qs, key=lambda p: -sum((w[:-1] if w.endswith("s") else w) in p.name.lower() for w in words))
    else:
        products = list(qs.order_by("price"))
    limit = business()["assistant"]["search_result_limit"]
    return {"query": query, "results": _product_rows(products[:limit]), "total_matches": len(products)}


def get_recommendations(user) -> dict:
    from backend.folder_two_services.recommendations.service import for_user
    return {"results": for_user(user, business()["assistant"]["search_result_limit"])}


def view_cart(user) -> dict:
    return cart.price_cart(user)


def add_to_cart(user, product_id: int, quantity: int = 1) -> dict:
    cart.set_quantity(user, int(product_id), int(quantity), increment=True)
    return cart.price_cart(user)


def remove_from_cart(user, product_id: int) -> dict:
    cart.remove(user, int(product_id))
    return cart.price_cart(user)


def order_status(user, order_id: int | None = None) -> dict:
    qs = Order.objects.filter(user=user)
    if order_id:
        o = qs.filter(id=order_id).first()
        if not o:
            raise DomainError(f"I could not find order #{order_id} on your account.", code="not_found")
        orders = [o]
    else:
        orders = list(qs.order_by("-created_at")[:3])
    return {"orders": [{"order_id": o.id, "status": o.status, "total": str(o.total),
                        "placed": o.created_at.date().isoformat(),
                        "history": list(o.history.values_list("to_status", flat=True))} for o in orders]}


def cancel_order(user, order_id: int) -> dict:
    o = Order.objects.filter(user=user, id=order_id).first()
    if not o:
        raise DomainError(f"I could not find order #{order_id} on your account.", code="not_found")
    o = transition(o, OrderStatus.CANCELLED, Role.CUSTOMER, user, note="Cancelled via assistant")
    return {"order_id": o.id, "status": o.status}


CUSTOMER = frozenset({Role.CUSTOMER})
BACK = frozenset(BACK_OFFICE_ROLES)

TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("search_products", "Search the catalogue by keywords, optional maximum price and category.",
         _obj({"query": {"type": "string"}, "max_price": {"type": "number"}, "category": {"type": "string"}},
              ["query"]), CUSTOMER, "assistant", search_products),
    Tool("get_recommendations", "Personalised product recommendations for the current customer.", _obj({}),
         CUSTOMER, "assistant", get_recommendations),
    Tool("view_cart", "Show the customer's cart with server-calculated totals.", _obj({}), CUSTOMER, "assistant",
         view_cart),
    Tool("add_to_cart", "Add a product to the cart. Requires the customer's confirmation.",
         _obj({"product_id": {"type": "integer"}, "quantity": {"type": "integer", "minimum": 1}}, ["product_id"]),
         CUSTOMER, "assistant", add_to_cart, mutating=True),
    Tool("remove_from_cart", "Remove a product from the cart. Requires confirmation.",
         _obj({"product_id": {"type": "integer"}}, ["product_id"]), CUSTOMER, "assistant", remove_from_cart,
         mutating=True),
    Tool("order_status", "Status of one order (by id) or of the customer's most recent orders.",
         _obj({"order_id": {"type": "integer"}}), CUSTOMER, "assistant", order_status),
    Tool("cancel_order", "Cancel one of the customer's orders. Requires confirmation.",
         _obj({"order_id": {"type": "integer"}}, ["order_id"]), CUSTOMER, "assistant", cancel_order, mutating=True),
]}

_REPORT_PARAM_SCHEMA = {"days": {"type": "integer", "minimum": 1}, "period": {"type": "string", "enum": ["day", "week", "month"]},
                        "limit": {"type": "integer", "minimum": 1}, "category": {"type": "string"},
                        "threshold": {"type": "integer", "minimum": 0}, "status": {"type": "string"}}
for _name, _spec in REPORTS.items():
    if _name == "order_history":
        continue
    TOOLS[_name] = Tool(_name, _spec.description, _obj({p: _REPORT_PARAM_SCHEMA[p] for p in _spec.params}), BACK,
                        "analytics", (lambda n: lambda user, **kw: run_report(n, **kw))(_name))

for _n in business()["assistant"]["confirm_required_tools"]:
    if _n in TOOLS:
        TOOLS[_n].mutating = True


def tools_for(user, channel: str) -> list[Tool]:
    return [t for t in TOOLS.values() if t.channel == channel and t.allowed(user)]
