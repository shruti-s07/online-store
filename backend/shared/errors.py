"""Uniform error payloads: {"detail": str, "code": str, ...extra}."""
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_handler


class DomainError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "domain_error"

    def __init__(self, detail, code=None, status_code=None, **extra):
        super().__init__(detail, code or self.default_code)
        if status_code:
            self.status_code = status_code
        self.code = code or self.default_code
        self.extra = extra


class OutOfStock(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "out_of_stock"


class ReservationExpired(DomainError):
    status_code = status.HTTP_410_GONE
    default_code = "reservation_expired"


class InvalidTransition(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "invalid_transition"


def exception_handler(exc, context):
    response = drf_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, DomainError):
        response.data = {"detail": str(exc.detail), "code": exc.code, **exc.extra}
    elif isinstance(response.data, dict) and "detail" in response.data:
        response.data.setdefault("code", getattr(exc, "default_code", "error"))
    else:
        response.data = {"detail": "Validation failed", "code": "invalid", "errors": response.data}
    return response
