"""Role-based DRF permissions. Every view uses one of these explicitly."""
from rest_framework.permissions import BasePermission

from backend.shared.roles import ADMIN_ROLES, BACK_OFFICE_ROLES, Role


def _role(request):
    user = request.user
    return getattr(user, "role", None) if user and user.is_authenticated else None


class IsAnyRole(BasePermission):
    """Any authenticated user with a known role."""

    def has_permission(self, request, view):
        return _role(request) in set(Role)


class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        return _role(request) == Role.CUSTOMER


class IsBackOffice(BasePermission):
    def has_permission(self, request, view):
        return _role(request) in BACK_OFFICE_ROLES


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return _role(request) in ADMIN_ROLES


class ReadAnyWriteBackOffice(BasePermission):
    """Any role may read; only Staff/Admin may write."""

    def has_permission(self, request, view):
        role = _role(request)
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return role in set(Role)
        return role in BACK_OFFICE_ROLES


def is_back_office(user) -> bool:
    return getattr(user, "role", None) in BACK_OFFICE_ROLES
