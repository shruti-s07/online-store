"""Login and registration screen."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .context import ctx
from .widgets import Banner, Card, Field, ValidatedForm, button, label
from .worker import run_async


class LoginView(QWidget):
    logged_in = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LoginPage")
        t = ctx().theme
        b = t.cfg["brand"]
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.addStretch()
        logo = label(f"{b['name']}<span style='color:{t.c['accent']}'>{b['mark']}</span>", "Logo")
        logo.setTextFormat(Qt.RichText)
        logo.setStyleSheet(f"font-size:{t.cfg['font_size_pt'] + 14}pt;")
        root.addWidget(logo, 0, Qt.AlignHCenter)
        root.addSpacing(18)
        card = Card()
        card.setFixedWidth(440)
        card.lay.setContentsMargins(28, 24, 28, 24)
        self.banner = Banner()
        card.lay.addWidget(self.banner)
        tabs = QTabWidget()
        self.tabs = tabs
        # Sign in
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 12, 0, 0)
        self.login_form = ValidatedForm([
            Field("email", "Email", "email", required=True, placeholder="name@example.com"),
            Field("password", "Password", "password", required=True),
        ])
        l.addWidget(self.login_form)
        self.login_btn = button("Sign in", "primary", None, self.do_login)
        l.addWidget(self.login_btn)
        l.addStretch()
        tabs.addTab(w, "Sign in")
        # Register
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        l2.setContentsMargins(0, 12, 0, 0)
        self.reg_form = ValidatedForm([
            Field("first_name", "First name", required=True), Field("last_name", "Last name"),
            Field("email", "Email", "email", required=True),
            Field("password", "Password", "password", required=True,
                  validator=lambda v, d: None if len(v) >= 8 else "Use at least 8 characters."),
            Field("confirm", "Confirm password", "password", required=True,
                  validator=lambda v, d: None if v == d["password"] else "Passwords do not match."),
        ])
        l2.addWidget(self.reg_form)
        self.reg_btn = button("Create account", "primary", None, self.do_register)
        l2.addWidget(self.reg_btn)
        l2.addStretch()
        tabs.addTab(w2, "Create account")
        card.lay.addWidget(tabs)
        root.addWidget(card, 0, Qt.AlignHCenter)
        root.addStretch()
        self.login_form.inputs["password"].returnPressed.connect(self.do_login)

    def show_message(self, text: str, kind: str = "info"):
        self.banner.show_message(text, kind)

    def _busy(self, btn, text):
        def f(on):
            btn.setEnabled(not on)
            btn.setText("Please wait…" if on else text)
        return f

    def do_login(self):
        data = self.login_form.validate()
        if not data:
            return
        self.banner.clear()
        run_async(lambda: ctx().api.login(data["email"], data["password"]),
                  lambda user: self.logged_in.emit(user),
                  lambda e: self.banner.show_message(
                      "Too many attempts. Please wait a minute and try again." if getattr(e, "status", 0) == 429
                      else ("Wrong email or password." if getattr(e, "status", 0) == 401 else str(e)), "error"),
                  self._busy(self.login_btn, "Sign in"))

    def do_register(self):
        data = self.reg_form.validate()
        if not data:
            return
        data.pop("confirm")

        def done(_):
            self.tabs.setCurrentIndex(0)
            self.login_form.set_value("email", data["email"])
            self.banner.show_message("Your account is ready. Sign in to continue.", "success")

        def err(e):
            self.reg_form.set_server_errors(getattr(e, "data", {}).get("errors", {}))
            self.banner.show_message(str(e), "error")
        run_async(lambda: ctx().api.register(**data), done, err, self._busy(self.reg_btn, "Create account"))
