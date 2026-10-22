"""The one and only definition of user roles. Admin acts as the seller."""
from enum import StrEnum


class Role(StrEnum):
    CUSTOMER = "CUSTOMER"
    STAFF = "STAFF"
    ADMIN = "ADMIN"


ROLE_CHOICES = [(r.value, r.value.title()) for r in Role]
DEFAULT_ROLE = Role.CUSTOMER
# Roles allowed to operate the back office (order queue, products, moderation).
BACK_OFFICE_ROLES = frozenset({Role.STAFF, Role.ADMIN})
# Roles allowed to manage users, discounts and AI settings.
ADMIN_ROLES = frozenset({Role.ADMIN})
