"""Assistant / analytics engine.

With LLM_API_KEY set: Claude with tool calling (manual tool-use loop); the server executes
every tool as the logged-in user and turns data-changing calls into pending actions.
Without a key: the locally trained intent classifier picks one tool and the reply is built
from that tool's real result.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.utils import timezone

from backend.shared.errors import DomainError
from config.loader import business, env, intents as intents_cfg

from . import nlu
from .models import ChatMessage, PendingAction
from .tools import TOOLS, tools_for
from backend.shared.formatting import MONEY_COLUMNS, format_money, group_number

log = logging.getLogger(__name__)


def llm_enabled() -> bool:
    return bool(env("LLM_API_KEY", ""))


def engine_name() -> str:
    return f"llm:{env('LLM_MODEL')}" if llm_enabled() else "local intent classifier"


def _jsonable(data):
    return json.loads(json.dumps(data, default=str))


def propose(user, tool_name: str, args: dict, summary: str) -> PendingAction:
    ttl = business()["assistant"]["pending_action_ttl_minutes"]
    return PendingAction.objects.create(user=user, tool=tool_name, args=args, summary=summary[:300],
                                        expires_at=timezone.now() + timedelta(minutes=ttl))


def run_tool(user, name: str, args: dict) -> dict:
    tool = TOOLS.get(name)
    if tool is None or not tool.allowed(user):
        raise DomainError(f"Tool {name} is not available to you.", code="tool_forbidden", status_code=403)
    return _jsonable(tool.fn(user, **args))


def confirm(user, action_id: int) -> dict:
    action = PendingAction.objects.filter(id=action_id, user=user).first()
    if not action:
        raise DomainError("Action not found.", code="not_found", status_code=404)
    if action.status != PendingAction.Status.PENDING:
        raise DomainError(f"Action is already {action.status.lower()}.", code="already_decided", status_code=409)
    if action.expires_at < timezone.now():
        action.status = PendingAction.Status.EXPIRED
        action.save(update_fields=["status"])
        raise DomainError("This action expired. Ask the assistant again.", code="action_expired", status_code=410)
    try:
        result = run_tool(user, action.tool, action.args)
        action.status, action.result = PendingAction.Status.CONFIRMED, result
    except DomainError as exc:
        action.status, action.result = PendingAction.Status.FAILED, {"error": str(exc.detail)}
    action.save(update_fields=["status", "result"])
    return {"action_id": action.id, "status": action.status, "result": action.result, "summary": action.summary}


def cancel(user, action_id: int) -> dict:
    n = PendingAction.objects.filter(id=action_id, user=user, status=PendingAction.Status.PENDING).update(
        status=PendingAction.Status.CANCELLED)
    if not n:
        raise DomainError("No pending action with this id.", code="not_found", status_code=404)
    return {"action_id": action_id, "status": "CANCELLED"}


def _action_payload(a: PendingAction | None):
    return a and {"id": a.id, "tool": a.tool, "args": a.args, "summary": a.summary, "expires_at": a.expires_at}


# ---------------------------------------------------------------------------- local fallback
HELP = {
    "assistant": "I can search products, recommend items, show your cart, add or remove items (after you confirm), "
                 "and check or cancel orders. Try: \"earbuds under 2000\".",
    "analytics": "Ask about revenue, sales trends, categories, top products, low stock, order statuses, customers "
                 "or segments. Try: \"top 5 products last 30 days\".",
}


def _describe(tool: str, data: dict) -> str:
    if tool == "search_products":
        if not data["results"]:
            return "I couldn't find matching products."
        lines = [f"• {r['name']} — {format_money(r['price'])} ({'in stock' if r['available'] else 'out of stock'})"
                 for r in data["results"]]
        n = data["total_matches"]
        return (f"I found {n} {'match' if n == 1 else 'matches'}:\n") + "\n".join(lines)
    if tool == "get_recommendations":
        if not data["results"]:
            return "I have no recommendations right now."
        return "You might like:\n" + "\n".join(f"• {r['name']} — {format_money(r['price'])} ({r['reason']})" for r in data["results"])
    if tool == "view_cart":
        if not data["lines"]:
            return "Your cart is empty."
        return (f"Your cart has {data['item_count']} item(s): "
                + ", ".join(f"{l['quantity']}× {l['name']}" for l in data["lines"])
                + f". Total {format_money(data['total'])} (discount {format_money(data['discount_total'])}).")
    if tool == "order_status":
        if not data["orders"]:
            return "You have no orders yet."
        return "\n".join(f"• Order #{o['order_id']} ({o['placed']}): {o['status'].replace('_', ' ').title()}, {format_money(o['total'])}"
                         for o in data["orders"])
    # analytics: summarise the table
    rows = data.get("rows", [])
    if not rows:
        return f"{data.get('title', 'Report')}: no data for this period."
    cols = data.get("columns") or []
    preview = "\n".join("• " + " · ".join(_cell(cols[i] if i < len(cols) else "", c) for i, c in enumerate(r))
                         for r in rows[:8])
    more = f"\n…and {len(rows) - 8} more rows." if len(rows) > 8 else ""
    return f"{data['title']}:\n{preview}{more}"


def _cell(column: str, value) -> str:
    """Readable report cell: money columns as ₹1,23,456, other numbers with digit grouping."""
    if column in MONEY_COLUMNS:
        return format_money(round(float(value)))
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value).replace("_", " ").capitalize() if str(value).isupper() else str(value)
    return group_number(num) if num == int(num) else f"{num:,.1f}"



def _get_context_product(user, channel: str):
    """Retrieve the most recently discussed product from conversation history."""
    from backend.folder_one_core.catalog.models import Product
    recent = ChatMessage.objects.filter(user=user, channel=channel, role="assistant").order_by("-created_at")[:6]
    for msg in recent:
        meta = msg.meta or {}
        if meta.get("last_product_id"):
            p = Product.objects.filter(id=meta["last_product_id"]).first()
            if p:
                return p
        if meta.get("product_ids"):
            p = Product.objects.filter(id=meta["product_ids"][0]).first()
            if p:
                return p
    return None


def _local(user, channel: str, text: str) -> dict:
    if channel == "assistant":
        from .knowledge import get_faq_answer
        faq = get_faq_answer(text)
        if faq:
            return {"engine": engine_name(), "intent": "store_info", "confidence": 1.0, "tool": None,
                    "data": None, "pending_action": None, "reply": faq}

    intent, conf = nlu.classify(text, channel)
    if intent is None:
        raise DomainError("The assistant model has not been trained yet. Run: python store.py train",
                          code="model_not_trained", status_code=503)
    cfg = intents_cfg()["intents"][intent]
    out = {"engine": engine_name(), "intent": intent, "confidence": round(conf, 3), "tool": cfg["tool"],
           "data": None, "pending_action": None}
    if conf < business()["assistant"]["min_intent_confidence"]:
        out["reply"] = "Sorry, I'm not sure what you mean. " + HELP[channel]
        return out
    if cfg["tool"] is None:
        out["reply"] = HELP[channel]
        return out
    if cfg["channel"] not in (channel, "both"):
        out["reply"] = ("That's a question for the analytics box." if channel == "assistant"
                        else "That's a shopping request; use the assistant chat.")
        return out
    tool = TOOLS[cfg["tool"]]
    if not tool.allowed(user):
        out["reply"] = "You don't have permission to do that."
        return out
    slots = nlu.extract_slots(text)
    args = {k: v for k, v in slots.items() if k in tool.schema["properties"]}
    if tool.name == "search_products":
        args["query"] = text
    if tool.name in ("add_to_cart", "remove_from_cart"):
        product, candidates = nlu.match_product(text)
        if product is None:
            ctx_p = _get_context_product(user, channel)
            if ctx_p and any(w in text.lower().split() for w in ("it", "this", "that", "item", "product", "cart", "basket", "buy", "add", "take", "one")):
                product = ctx_p
        if product is None:
            out["reply"] = ("Which product do you mean? " + ", ".join(p.name for p in candidates)
                            if candidates else "I couldn't tell which product you mean. Try its name.")
            return out
        args = {"product_id": product.id}
        if tool.name == "add_to_cart":
            args["quantity"] = slots.get("quantity", 1)
        summary = (f"Add {args.get('quantity', 1)} × {product.name} ({format_money(product.price)}) to your cart"
                   if tool.name == "add_to_cart" else f"Remove {product.name} from your cart")
    elif tool.name == "cancel_order":
        if "order_id" not in args:
            from backend.folder_one_core.orders.models import Order
            last = Order.objects.filter(user=user).order_by("-created_at").first()
            if not last:
                out["reply"] = "You have no orders to cancel."
                return out
            args["order_id"] = last.id
        summary = f"Cancel order #{args['order_id']}"
    if tool.mutating:
        action = propose(user, tool.name, args, summary)
        out["pending_action"] = _action_payload(action)
        out["reply"] = f"{summary}? Please confirm."
        return out
    try:
        data = run_tool(user, tool.name, args)
    except DomainError as exc:
        out["reply"] = str(exc.detail)
        return out
    out["data"], out["args"] = data, args
    out["reply"] = _describe(tool.name, data)
    if tool.name in ("search_products", "get_recommendations") and data.get("results"):
        out["meta"] = {
            "last_product_id": data["results"][0].get("product_id"),
            "last_product_name": data["results"][0].get("name"),
            "product_ids": [r.get("product_id") for r in data["results"] if r.get("product_id")]
        }
    return out


# ---------------------------------------------------------------------------- LLM path
SYSTEM = {
    "assistant": ("You are the shopping assistant of an online store. Use the tools to look up real data; never "
                  "invent products, prices or order details. Tools that change data (cart, cancellations) are not "
                  "executed immediately: the customer must confirm them in the app, so tell them to confirm. "
                  "Answer briefly."),
    "analytics": ("You answer business questions for store staff. Use only the report tools provided; every number "
                  "in your answer must come from a tool result. If no report fits, say so. Answer briefly."),
}


def _llm(user, channel: str, text: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=env("LLM_API_KEY"), timeout=env("LLM_TIMEOUT_SECONDS", cast=float))
    tools = tools_for(user, channel)
    history = ChatMessage.objects.filter(user=user, channel=channel).order_by("-created_at")[
        : business()["assistant_llm"]["history_turns"] * 2]
    transcript = "\n".join(f"{m.role}: {m.content}" for m in reversed(list(history)))
    content = f"Conversation so far:\n{transcript}\n\nNew message: {text}" if transcript else text
    messages = [{"role": "user", "content": content}]
    pending, data, used = None, None, []
    for _ in range(business()["assistant"]["max_tool_rounds"]):
        resp = client.messages.create(
            model=env("LLM_MODEL"), max_tokens=env("LLM_MAX_TOKENS", cast=int), system=SYSTEM[channel],
            tools=[t.anthropic_spec() for t in tools], messages=messages,
            output_config={"effort": business()["assistant_llm"]["effort"]})
        if resp.stop_reason == "refusal":
            return {"reply": "Sorry, I can't help with that request.", "engine": engine_name(), "data": data,
                    "pending_action": _action_payload(pending), "tools_used": used}
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            reply = "".join(b.text for b in resp.content if b.type == "text").strip()
            return {"reply": reply, "engine": engine_name(), "data": data, "pending_action": _action_payload(pending),
                    "tools_used": used}
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            used.append(block.name)
            tool = TOOLS.get(block.name)
            try:
                if tool is None or tool not in tools:
                    raise DomainError("Tool not available.", code="tool_forbidden")
                args = dict(block.input)
                if tool.mutating:
                    pending = propose(user, tool.name, args, f"{tool.name.replace('_', ' ')} {json.dumps(args)}")
                    result = {"status": "awaiting_user_confirmation", "action_id": pending.id}
                else:
                    result = data = run_tool(user, tool.name, args)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)})
            except (DomainError, TypeError) as exc:
                results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                "content": str(getattr(exc, "detail", exc))})
        messages.append({"role": "user", "content": results})
    return {"reply": "I couldn't finish that request.", "engine": engine_name(), "data": data,
            "pending_action": _action_payload(pending), "tools_used": used}


def handle(user, channel: str, text: str) -> dict:
    text = text.strip()
    if not text:
        raise DomainError("Message is empty.", code="invalid")
    if llm_enabled():
        try:
            out = _llm(user, channel, text)
        except DomainError:
            raise
        except Exception as exc:  # network/API failure: degrade to the local model, and say so
            log.warning("LLM call failed (%s); using local intent classifier", exc)
            out = _local(user, channel, text)
            out["engine"] += " (LLM unavailable)"
    else:
        out = _local(user, channel, text)
    ChatMessage.objects.create(user=user, channel=channel, role="user", content=text)
    meta = {k: out.get(k) for k in ("engine", "intent", "tool")}
    if "meta" in out and isinstance(out["meta"], dict):
        meta.update(out["meta"])
    ChatMessage.objects.create(user=user, channel=channel, role="assistant", content=out["reply"],
                               meta=meta)
    return out
