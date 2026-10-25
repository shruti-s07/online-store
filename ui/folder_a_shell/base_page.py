"""Base class for sidebar pages: header, banner, state pane and async loading."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from .context import ctx
from .widgets import Banner, StatePane, label
from .worker import run_async


class BasePage(QWidget):
    title = ""
    subtitle = ""
    empty_text = "Nothing here yet."
    empty_icon = "fa5s.inbox"
    scrollable = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        sp = ctx().theme.cfg["spacing_px"]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(sp * 2, sp * 1.5, sp * 2, sp * 1.5)
        outer.setSpacing(sp)
        outer.setSpacing(sp)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_lbl = label(self.title, "PageTitle")
        titles.addWidget(self.title_lbl)
        if self.subtitle:
            titles.addWidget(label(self.subtitle, "Subtitle"))
        head.addLayout(titles, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        head.addLayout(self.actions)
        outer.addLayout(head)
        self.banner = Banner()
        outer.addWidget(self.banner)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(sp)
        content = self.body
        if self.scrollable:
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setWidget(self.body)
            content = sc
        self.state = StatePane(content, self.empty_text, self.empty_icon)
        self.state.retry.connect(self.refresh)
        outer.addWidget(self.state, 1)
        self.build()

    def set_title(self, text: str):
        self.title_lbl.setText(text)

    # Subclasses: build() creates widgets, fetch() returns data (runs in a QThread), render(data) fills widgets
    def build(self):
        pass

    def fetch(self):
        return None

    def render(self, data):
        pass

    def is_empty(self, data) -> bool:
        return False

    def refresh(self):
        self.state.show_loading()

        def done(data):
            if self.is_empty(data):
                self.state.show_empty()
            else:
                self.state.show_content()
            self.render(data)

        run_async(self.fetch, done, self.state.show_error)

    def on_show(self):
        self.refresh()

    @property
    def api(self):
        return ctx().api
