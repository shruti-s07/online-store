"""Sidebar page registry. Any module (e.g. ui/folder_b_panels/*) calls register_page() at import
time and its page appears in the sidebar for the allowed roles; the main window is never edited."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.shared.roles import Role

ALL = frozenset(Role)
CUSTOMER = frozenset({Role.CUSTOMER})
BACK_OFFICE = frozenset({Role.STAFF, Role.ADMIN})
ADMIN = frozenset({Role.ADMIN})


@dataclass(frozen=True)
class PageSpec:
    key: str
    title: str
    icon: str
    roles: frozenset
    factory: Callable
    section: str = "Shop"
    order: int = 100


_pages: dict[str, PageSpec] = {}


def register_page(spec: PageSpec) -> PageSpec:
    _pages[spec.key] = spec
    return spec


def pages_for(role: str) -> list[PageSpec]:
    return sorted((p for p in _pages.values() if Role(role) in p.roles), key=lambda p: (p.order, p.title))


def all_pages() -> list[PageSpec]:
    return list(_pages.values())
