"""Display formatting shared by the API text responses and the desktop UI.

Currency symbol, digit grouping, paise display and date formats come from
config/business.yaml (currency_symbol, locale)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from config.loader import business


# Report columns that hold rupee amounts (report functions in folder two name them this way)
MONEY_COLUMNS = frozenset({"Revenue", "Gross margin", "Total", "Avg order"})


def _group(int_digits: str) -> str:
    if business()["locale"]["digit_grouping"] != "indian" or len(int_digits) <= 3:
        return f"{int(int_digits):,}"
    head, tail = int_digits[:-3], int_digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def group_number(value) -> str:
    """12345678 -> '1,23,45,678' (Indian grouping) for whole numbers."""
    try:
        n = int(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    return ("-" if n < 0 else "") + _group(str(abs(n)))


def format_money(value) -> str:
    """Decimal/str/float -> '₹1,23,456' or '₹1,299.50'. Non-numbers are returned unchanged."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    cfg = business()
    places = cfg["money_decimal_places"]
    d = d.quantize(Decimal(1).scaleb(-places))
    sign = "−" if d < 0 else ""
    d = abs(d)
    whole, _, frac = f"{d:f}".partition(".")
    text = cfg["currency_symbol"] + _group(whole)
    if frac and not (cfg["locale"]["hide_zero_paise"] and int(frac) == 0):
        text += "." + frac
    return sign + text


def format_money_compact(value) -> str:
    """Axis/tile style: ₹950, ₹12.5k, ₹4.2 L, ₹1.3 Cr (Indian units)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    sym, sign, v = business()["currency_symbol"], "−" if v < 0 else "", abs(v)
    for size, unit in ((1e7, " Cr"), (1e5, " L"), (1e3, "k")):
        if v >= size:
            return f"{sign}{sym}{v / size:.1f}".rstrip("0").rstrip(".") + unit
    return f"{sign}{sym}{v:.0f}"


def _as_local(value) -> datetime | date | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                value = date.fromisoformat(value[:10])
            except ValueError:
                return None
    if isinstance(value, datetime) and value.tzinfo is not None:
        value = value.astimezone(ZoneInfo(business()["locale"]["time_zone"]))
    return value


def format_date(value) -> str:
    """ISO string / date / datetime -> '21 Oct 2026' in the store time zone."""
    v = _as_local(value)
    if v is None:
        return str(value or "")
    return v.strftime(business()["locale"]["date_format"]).lstrip("0")


def format_datetime(value) -> str:
    """ISO string / datetime -> '21 Oct 2026, 14:05' in the store time zone."""
    v = _as_local(value)
    if v is None:
        return str(value or "")
    if not isinstance(v, datetime):
        return format_date(v)
    return v.strftime(business()["locale"]["datetime_format"]).lstrip("0")
