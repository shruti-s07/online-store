"""Payment-method rules from config/business.yaml (checkout.*)."""
from config.loader import business


def is_prepaid(method: str) -> bool:
    return method in business()["checkout"]["prepaid_methods"]


def cod_method() -> str:
    return business()["checkout"]["cash_on_delivery_method"]


def is_cod(method: str) -> bool:
    return not is_prepaid(method)
