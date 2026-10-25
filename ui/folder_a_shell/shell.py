"""Main window: login screen, storefront header (customers) or Seller Hub sidebar (staff), page stack.

Both navigation styles are built from the page registry."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from backend.shared.formatting import group_number
from backend.shared.roles import Role

from config.loader import env

from . import registry
from .context import ctx
from .login import LoginView
from .widgets import button, icon, label
from .worker import run_async


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        t = ctx().theme
        self.setWindowTitle(t.cfg["brand"]["name"])
        self.resize(t.cfg["window"]["width"], t.cfg["window"]["height"])
        self.root = QStackedWidget()
        self.setCentralWidget(self.root)
        self.login = LoginView()
        self.login.logged_in.connect(self.enter_app)
        self.root.addWidget(self.login)
        self.app = None
        self.pages: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        ctx().bus.session_expired.connect(self.on_session_expired)
        ctx().bus.navigate.connect(self.open_page)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.refresh_badge)

    # ------------------------------------------------------------------ session
    def start(self):
        user = ctx().api.restore_session()
        if user:
            self.enter_app(user)

    def enter_app(self, user: dict):
        if self.app is not None:
            self.root.removeWidget(self.app)
            self.app.deleteLater()
        self.pages.clear()
        self.nav_buttons.clear()
        self.app = self._build_app(user)
        self.root.addWidget(self.app)
        self.root.setCurrentWidget(self.app)
        specs = registry.pages_for(user["role"])
        if specs:
            self.open_page(specs[0].key)
        self.poll.start(int(env("UI_NOTIFICATION_POLL_SECONDS", cast=float) * 1000))
        self.refresh_badge()

    def logout(self):
        ctx().api.logout()
        self.poll.stop()
        self.root.setCurrentWidget(self.login)
        self.login.show_message("You have been signed out.", "info")

    def on_session_expired(self):
        self.poll.stop()
        self.root.setCurrentWidget(self.login)
        self.login.show_message("Your session expired. Please sign in again.", "warning")

    # ------------------------------------------------------------------ layout
    def _build_app(self, user: dict) -> QWidget:
        """Customers get a storefront header; staff and admins get the Seller Hub sidebar."""
        self.cart_badge = None
        self.bell = None
        if user["role"] == Role.CUSTOMER.value:
            return self._build_storefront(user)
        return self._build_back_office(user)

    def _logo(self, size_pt: int | None = None) -> QLabel:
        t = ctx().theme
        b = t.cfg["brand"]
        logo = label(f"{b['name']}<span style='color:{t.c['accent']}'>{b['mark']}</span>", "Logo")
        logo.setTextFormat(Qt.RichText)
        if size_pt:
            logo.setStyleSheet(f"font-size:{size_pt}pt;")
        return logo

    def _account_menu(self, user: dict, specs) -> QMenu:
        menu = QMenu(self)
        for spec in specs:
            menu.addAction(spec.title, lambda k=spec.key: self.open_page(k))
        menu.addSeparator()
        menu.addAction("Dark mode" if ctx().theme.mode == "light" else "Light mode", self.toggle_theme)
        menu.addAction("Sign out", self.logout)
        return menu

    def _build_storefront(self, user: dict) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QWidget()
        head.setObjectName("StoreHeader")
        head.setFixedHeight(64)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(28, 0, 28, 0)
        hl.setSpacing(24)
        specs = registry.pages_for(user["role"])
        home = specs[0].key if specs else None
        logo = self._logo()
        logo.setCursor(Qt.PointingHandCursor)
        logo.mousePressEvent = lambda _e: home and self.open_page(home)
        hl.addWidget(logo)
        self.header_search = QLineEdit()
        self.header_search.setObjectName("HeaderSearch")
        self.header_search.setPlaceholderText("Search for products, brands and more")
        self.header_search.addAction(icon("mdi6.magnify", "muted"), QLineEdit.LeadingPosition)
        self.header_search.returnPressed.connect(
            lambda: home and self.open_page(home, {"search": self.header_search.text().strip()}))
        hl.addWidget(self.header_search, 1)
        group = QButtonGroup(self)
        group.setExclusive(True)
        account_specs = []
        for spec in specs:
            if spec.key == home:
                continue
            if spec.section != specs[0].section:
                account_specs.append(spec)
                continue
            if spec.key == "cart":
                continue
            b = QPushButton(spec.title.replace("&", "&&"))
            b.setObjectName("HeaderLink")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=spec.key: self.open_page(k))
            group.addButton(b)
            self.nav_buttons[spec.key] = b
            hl.addWidget(b)
        self.bell = QPushButton()
        self.bell.setObjectName("HeaderLink")
        self.bell.setIcon(icon("mdi6.bell-outline", "text"))
        self.bell.setToolTip("Notifications")
        self.bell.setCursor(Qt.PointingHandCursor)
        self.bell.clicked.connect(lambda: self.open_page("notifications"))
        hl.addWidget(self.bell)
        name = user.get("first_name") or user["email"].split("@")[0]
        acct = QPushButton(f" {name}")
        acct.setObjectName("HeaderLink")
        acct.setIcon(icon("mdi6.account-outline", "text"))
        acct.setCursor(Qt.PointingHandCursor)
        acct.setMenu(self._account_menu(user, account_specs))
        hl.addWidget(acct)
        if any(s.key == "cart" for s in specs):
            cart = QPushButton(" Cart")
            cart.setObjectName("HeaderLink")
            cart.setCheckable(True)
            cart.setIcon(icon("mdi6.cart-outline", "text"))
            cart.setCursor(Qt.PointingHandCursor)
            cart.clicked.connect(lambda: self.open_page("cart"))
            group.addButton(cart)
            self.nav_buttons["cart"] = cart
            box = QHBoxLayout()
            box.setSpacing(4)
            box.addWidget(cart)
            self.cart_badge = label("0", "CountBadge")
            box.addWidget(self.cart_badge)
            hl.addLayout(box)
            ctx().bus.cart_changed.connect(self.refresh_cart_count)
        lay.addWidget(head)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.refresh_cart_count()
        return w

    def _build_back_office(self, user: dict) -> QWidget:
        t = ctx().theme
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(t.cfg["sidebar_width_px"])
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 18, 12, 14)
        sl.setSpacing(1)
        brand = QVBoxLayout()
        brand.setContentsMargins(10, 0, 0, 6)
        brand.setSpacing(0)
        brand.addWidget(self._logo())
        brand.addWidget(label(t.cfg["brand"]["staff_area"], "LogoSub"))
        sl.addLayout(brand)
        group = QButtonGroup(self)
        group.setExclusive(True)
        section = None
        for spec in registry.pages_for(user["role"]):
            if spec.section != section:
                section = spec.section
                sl.addWidget(label(section.upper(), "NavSection"))
            b = QPushButton(spec.title.replace("&", "&&"))
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=spec.key: self.open_page(k))
            group.addButton(b)
            self.nav_buttons[spec.key] = b
            sl.addWidget(b)
        sl.addStretch()
        lay.addWidget(side)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        top = QWidget()
        top.setObjectName("TopBar")
        top.setFixedHeight(60)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(28, 0, 28, 0)
        tl.setSpacing(12)
        tl.addStretch()
        self.bell = button("", "ghost", "mdi6.bell-outline", lambda: self.open_page("notifications"))
        self.bell.setToolTip("Notifications")
        tl.addWidget(self.bell)
        first, last = user.get("first_name") or "", user.get("last_name") or ""
        initials = ((first[:1] + last[:1]) or user["email"][:2]).upper()
        avatar = label(initials, "Avatar")
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(Qt.AlignCenter)
        tl.addWidget(avatar)
        who = QVBoxLayout()
        who.setSpacing(0)
        who.addWidget(label(f"{first} {last}".strip() or user["email"], "Strong"))
        who.addWidget(label(t.status_label(user["role"]), "Small"))
        tl.addLayout(who)
        menu_btn = button("", "ghost", "mdi6.chevron-down")
        menu_btn.setObjectName("MenuButton")
        menu_btn.setMenu(self._account_menu(user, []))
        tl.addWidget(menu_btn)
        ml.addWidget(top)
        self.stack = QStackedWidget()
        ml.addWidget(self.stack, 1)
        lay.addWidget(main, 1)
        return w

    # ------------------------------------------------------------------ navigation
    def open_page(self, key: str, payload=None):
        spec = next((p for p in registry.pages_for(ctx().role) if p.key == key), None) if ctx().user else None
        if spec is None:
            return
        if key not in self.pages:
            page = spec.factory()
            self.pages[key] = page
            self.stack.addWidget(page)
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        if key in self.nav_buttons:
            self.nav_buttons[key].setChecked(True)
        else:
            for b in self.nav_buttons.values():
                grp = b.group()
                if grp is not None and grp.checkedButton() is not None:
                    grp.setExclusive(False)
                    grp.checkedButton().setChecked(False)
                    grp.setExclusive(True)
                break
        if payload is not None and hasattr(page, "set_payload"):
            page.set_payload(payload)
        page.on_show()
        self.refresh_cart_count()

    def current_page(self):
        return self.stack.currentWidget() if self.app else self.login

    def refresh_badge(self):
        if not ctx().user:
            return

        def done(data):
            n = data.get("count", 0)
            try:
                self.bell.setText(f" {group_number(n)}" if n else "")
                self.bell.setIcon(icon("mdi6.bell-badge-outline" if n else "mdi6.bell-outline", "text"))
            except RuntimeError:
                pass
        run_async(lambda: ctx().api.get("notifications/", {"unread": "true", "page_size": 1}), done, lambda e: None)

    def refresh_cart_count(self):
        if self.cart_badge is None or not ctx().user:
            return

        def done(cart):
            try:
                n = cart.get("item_count", 0)
                self.cart_badge.setText(str(n))
                self.cart_badge.setVisible(n > 0)
            except RuntimeError:
                pass
        run_async(lambda: ctx().api.get("cart/"), done, lambda e: None)

    def toggle_theme(self):
        from PySide6.QtWidgets import QApplication
        t = ctx().theme
        t.toggle()
        QApplication.instance().setStyleSheet(t.stylesheet())
        # Rebuild so icon colours and painted widgets pick up the new palette
        current = next((k for k, p in self.pages.items() if p is self.stack.currentWidget()), None)
        self.enter_app(ctx().user)
        if current:
            self.open_page(current)
        ctx().bus.theme_changed.emit()
