"""Local fallback NLU: trained intent classifier (ai/train_intents.py) + rule-based slot filling."""
from __future__ import annotations

import re

from ai.common import load_artifact
from backend.folder_one_core.catalog.models import Category, Product
from config.loader import intents as intents_cfg

WORD_NUMBERS = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5, "a couple of": 2}


def classify(text: str, channel: str) -> tuple[str | None, float]:
    """Most likely intent among those offered on `channel`, with its (renormalised) probability."""
    bundle = load_artifact("intents")
    if bundle is None:
        return None, 0.0
    from ai.train_intents import normalize
    spec = intents_cfg()["intents"]
    model = bundle["model"]
    probs = model.predict_proba([normalize(text, bundle["vocab"])])[0]
    allowed = [spec[c]["channel"] in (channel, "both") for c in model.classes_]
    probs = probs * allowed
    probs = probs / probs.sum() if probs.sum() else probs
    i = probs.argmax()
    return str(model.classes_[i]), float(probs[i])


def extract_slots(text: str) -> dict:
    t = text.lower()
    slots: dict = {}
    if m := re.search(r"(?:order|#)\s*(?:number\s*|no\.?\s*)?#?(\d+)", t):
        slots["order_id"] = int(m.group(1))
    if m := re.search(r"(?:under|below|less than|cheaper than|max|up to)\s*(?:\$|₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)", t):
        slots["max_price"] = float(m.group(1).replace(",", ""))
    if m := re.search(r"(?:last|past|previous)\s+(\d+)\s+days?", t):
        slots["days"] = int(m.group(1))
    else:
        for phrase, days in sorted(intents_cfg()["time_phrases"].items(), key=lambda kv: -len(kv[0])):
            if phrase in t:
                slots["days"] = days
                break
    if m := re.search(r"top\s+(\d+)", t):
        slots["limit"] = int(m.group(1))
    if m := re.search(r"(?:below|under)\s+(\d+)\s+units", t):
        slots["threshold"] = int(m.group(1))
    for word, period in (("daily", "day"), ("per day", "day"), ("weekly", "week"), ("per week", "week"),
                         ("monthly", "month"), ("per month", "month"), ("by day", "day"), ("by week", "week"),
                         ("by month", "month")):
        if word in t:
            slots["period"] = period
            break
    for c in Category.objects.all():
        if c.name.lower() in t or c.slug in t or c.name.split()[0].lower() in t.split():
            slots["category"] = c.name
            break
    m = re.search(r"\b(\d+|one|two|three|four|five|a couple of)\b\s+(?:of\s+)?(?:the\s+)?[a-z]", t)
    if m and "order" not in t:
        slots["quantity"] = int(m.group(1)) if m.group(1).isdigit() else WORD_NUMBERS[m.group(1)]
    if m := re.search(r"\bon hold\b|\bpending\b|\bcancelled\b|\bshipped\b", t):
        slots["status"] = m.group(0).replace(" ", "_").upper()
    return slots


def match_product(text: str) -> tuple[Product | None, list[Product]]:
    """Best product for phrases like 'add the voltix speaker'. Returns (match, candidates)."""
    from .tools import STOPWORDS

    words = {w.strip(".,!?") for w in text.lower().split()} - STOPWORDS
    words = {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words if len(w) > 2 and not w.isdigit()}
    if not words:
        return None, []
    scored = []
    for p in Product.objects.all():
        name = p.name.lower()
        score = sum(1 for w in words if w in name)
        if score:
            scored.append((score, p))
    if not scored:
        return None, []
    scored.sort(key=lambda s: (-s[0], s[1].name))
    best = scored[0][0]
    top = [p for s, p in scored if s == best]
    return (top[0] if len(top) == 1 else None), top[:5]
