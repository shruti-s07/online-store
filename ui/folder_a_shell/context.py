"""App-wide context: API client, theme, current user, and cross-thread signals."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

_ctx = None


class Bus(QObject):
    session_expired = Signal()
    cart_changed = Signal()
    theme_changed = Signal()
    navigate = Signal(str, object)  # page key, optional payload


class AppContext:
    def __init__(self, api, theme):
        self.api = api
        self.theme = theme
        self.bus = Bus()
        # Called from worker threads: re-emit as a signal so the GUI thread handles it
        api.on_session_expired = lambda: self.bus.session_expired.emit()

    @property
    def user(self) -> dict | None:
        return self.api.user

    @property
    def role(self) -> str | None:
        return self.user and self.user["role"]


def init(api, theme) -> AppContext:
    global _ctx
    _ctx = AppContext(api, theme)
    return _ctx


def ctx() -> AppContext:
    if _ctx is None:
        raise RuntimeError("UI context not initialised")
    return _ctx
