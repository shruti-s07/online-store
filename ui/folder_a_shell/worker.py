"""Run blocking API calls off the GUI thread.

Worker is a QThread; results are delivered back on the GUI thread through a relay QObject,
so callbacks may touch widgets safely.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

_active: set["Worker"] = set()


class Worker(QThread):
    succeeded = Signal(object)
    errored = Signal(object)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.succeeded.emit(self.fn())
        except Exception as exc:  # delivered to the GUI thread, shown by the caller
            self.errored.emit(exc)


class _Relay(QObject):
    def __init__(self, on_done, on_error, on_finally):
        super().__init__()
        self.on_done, self.on_error, self.on_finally = on_done, on_error, on_finally

    @Slot(object)
    def done(self, result):
        try:
            self.on_done(result)
        finally:
            self.on_finally()

    @Slot(object)
    def error(self, exc):
        try:
            self.on_error(exc)
        finally:
            self.on_finally()


def run_async(fn: Callable, on_done: Callable, on_error: Callable | None = None,
              busy: Callable[[bool], None] | None = None) -> Worker:
    """Run fn() in a QThread; call on_done(result) or on_error(exc) on the GUI thread.
    `busy(True/False)` toggles a loading indicator around the call."""
    from .widgets import show_error

    worker = Worker(fn)
    if busy:
        busy(True)

    def finish():
        if busy:
            try:
                busy(False)
            except RuntimeError:  # widget already deleted
                pass

    relay = _Relay(on_done, on_error or (lambda e: show_error(None, e)), finish)
    worker.relay = relay  # keep alive
    worker.succeeded.connect(relay.done)
    worker.errored.connect(relay.error)
    _active.add(worker)
    worker.finished.connect(lambda: _active.discard(worker))
    worker.start()
    return worker


def active_count() -> int:
    return len(_active)
