from decimal import ROUND_HALF_UP, Decimal

from config.loader import business

_Q = Decimal(1).scaleb(-business()["money_decimal_places"])


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(_Q, rounding=ROUND_HALF_UP)
