"""Reusable widgets: cards, status chips, banners, loading/empty/error states, sortable paginated
table, validated form, confirm dialog, error message, image loader, timeline."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import qtawesome as qta
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .context import ctx
from backend.shared.formatting import format_date, format_datetime, format_money, group_number


def icon(name: str, color_key: str = "text"):
    return qta.icon(name, color=ctx().theme.c[color_key])


def button(text: str, variant: str | None = None, icon_name: str | None = None, on_click=None) -> QPushButton:
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if icon_name and not text:
        # Icons only on icon-only buttons; labelled buttons stay text-only for a quieter UI
        b.setIcon(icon(icon_name, "muted"))
    b.setCursor(Qt.PointingHandCursor)
    if on_click:
        b.clicked.connect(on_click)
    return b


def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    l.setWordWrap(wrap)
    return l


def money(v) -> str:
    return format_money(v)


class Card(QFrame):
    clicked = Signal()

    def __init__(self, parent=None, clickable: bool = False, padding: int | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("clickable", "true" if clickable else "false")
        sp = ctx().theme.cfg["spacing_px"] if padding is None else padding
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(sp, sp, sp, sp)
        self.lay.setSpacing(max(6, sp // 2))
        if clickable:
            self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if self.property("clickable") == "true":
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class StatusChip(QLabel):
    def __init__(self, status: str, parent=None):
        super().__init__(parent)
        self.set_status(status)

    def set_status(self, status: str):
        t = ctx().theme
        col, fg = t.status_color(status), t.status_text_color(status)
        self.setTextFormat(Qt.RichText)
        self.setText(f"<span style='color:{col}'>●</span>&nbsp;{t.status_label(status)}")
        self.setStyleSheet(f"background:{t.alpha(col, 0.11)}; color:{fg}; border-radius:4px; padding:2px 8px;"
                           f"font-weight:500; font-size:{t.cfg['font_size_pt'] - 1}pt;")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)


class ChipDelegate(QStyledItemDelegate):
    """Paints status values as rounded coloured chips inside tables (keeps sorting intact)."""

    def paint(self, painter: QPainter, option, index):
        status = index.data(Qt.DisplayRole) or ""
        if not status:
            return super().paint(painter, option, index)
        # Paint the normal cell (background, selection, row border) without its text, then the chip on top
        base = QStyleOptionViewItem(option)
        self.initStyleOption(base, index)
        base.text = ""
        style = base.widget.style() if base.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, base, painter, base.widget)
        t = ctx().theme
        col = QColor(t.status_color(status))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        f = option.font
        f.setWeight(QFont.Medium)
        f.setPointSize(t.cfg["font_size_pt"] - 1)
        painter.setFont(f)
        text = t.status_label(status)
        fm = painter.fontMetrics()
        dot = 6
        w = fm.horizontalAdvance(text) + dot + 22
        h = fm.height() + 4
        r = QRectF(option.rect.x() + 10, option.rect.center().y() - h / 2, w, h)
        bg = QColor(col)
        bg.setAlphaF(0.11)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(r, 4, 4)
        painter.setBrush(col)
        painter.drawEllipse(QRectF(r.x() + 8, r.center().y() - dot / 2, dot, dot))
        painter.setPen(QColor(t.status_text_color(status)))
        painter.drawText(r.adjusted(dot + 14, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()


class Banner(QFrame):
    """Inline message: error / warning / success / info."""

    ICONS = {"error": "fa5s.exclamation-circle", "warning": "fa5s.exclamation-triangle",
             "success": "fa5s.check-circle", "info": "fa5s.info-circle"}
    COLORS = {"error": "danger", "warning": "warning", "success": "success", "info": "info"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.ic = QLabel()
        self.text = QLabel()
        self.text.setWordWrap(True)
        lay.addWidget(self.ic)
        lay.addWidget(self.text, 1)
        self.hide()

    def show_message(self, text: str, kind: str = "info"):
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        self.ic.setPixmap(icon(self.ICONS[kind], self.COLORS[kind]).pixmap(18, 18))
        self.text.setText(text)
        self.show()

    def clear(self):
        self.hide()


class Spinner(QWidget):
    def __init__(self, parent=None, size: int = 36):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(30)

    def _tick(self):
        self.angle = (self.angle + 10) % 360
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(ctx().theme.c["primary"]), 4, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        m = 4
        p.drawArc(QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m), -self.angle * 16, 270 * 16)


class StatePane(QStackedWidget):
    """Content / loading / empty / error states for every screen."""

    retry = Signal()

    def __init__(self, content: QWidget, empty_text: str = "Nothing here yet.", empty_icon: str = "fa5s.inbox",
                 parent=None):
        super().__init__(parent)
        self.content = content
        self.addWidget(content)
        self.loading = self._center([Spinner(), label("Loading…", "Muted")])
        self.addWidget(self.loading)
        self.empty_icon = QLabel()
        self.empty_icon.setPixmap(icon(empty_icon, "muted").pixmap(56, 56))
        self.empty_label = label(empty_text, "Muted")
        self.empty_action = button("", "primary")
        self.empty_action.hide()
        self.empty = self._center([self.empty_icon, self.empty_label, self.empty_action])
        self.addWidget(self.empty)
        self.err_icon = QLabel()
        self.err_icon.setPixmap(icon("fa5s.exclamation-triangle", "danger").pixmap(48, 48))
        self.err_label = label("", wrap=True)
        self.err_label.setAlignment(Qt.AlignCenter)
        self.err_label.setFixedWidth(560)
        self.err_label.setMinimumHeight(48)
        retry = button("Try again", "primary", "fa5s.redo", lambda: self.retry.emit())
        self.error = self._center([self.err_icon, label("Something went wrong", "H2"), self.err_label, retry])
        self.addWidget(self.error)

    def _center(self, widgets):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch()
        for x in widgets:
            lay.addWidget(x, 0, Qt.AlignHCenter)
        lay.addStretch()
        return w

    def show_content(self):
        self.setCurrentWidget(self.content)

    def show_loading(self):
        self.setCurrentWidget(self.loading)

    def show_empty(self, text: str | None = None, action_text: str | None = None, on_action=None):
        if text:
            self.empty_label.setText(text)
        if action_text and on_action:
            self.empty_action.setText(action_text)
            if getattr(self, "_empty_cb", None) is not None:
                self.empty_action.clicked.disconnect(self._empty_cb)
            self._empty_cb = on_action
            self.empty_action.clicked.connect(on_action)
            self.empty_action.show()
        else:
            self.empty_action.hide()
        self.setCurrentWidget(self.empty)

    def show_error(self, exc):
        self.err_label.setText(str(exc))
        self.setCurrentWidget(self.error)


@dataclass
class Col:
    key: str
    title: str
    kind: str = "text"  # text | id | money | status | int | float | date | datetime
    width: int | None = None
    fmt: Callable[[Any], str] | None = None


class _SortItem(QTableWidgetItem):
    def __lt__(self, other):
        a, b = self.data(Qt.UserRole), other.data(Qt.UserRole)
        try:
            return (a is None, a) < (b is None, b)
        except TypeError:
            return str(a) < str(b)


class DataTable(QWidget):
    """Sortable table with optional server-side pagination bar."""

    page_requested = Signal(int, int)  # page, page_size
    activated = Signal(dict)
    selected = Signal(dict)

    def __init__(self, columns: list[Col], paginated: bool = True, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows: list[dict] = []
        self.page, self.total = 1, 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels([c.title for c in columns])
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setFocusPolicy(Qt.NoFocus)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hh.setSectionResizeMode(QHeaderView.Stretch)
        self._chip = ChipDelegate(self.table)
        for i, c in enumerate(columns):
            if c.kind == "status":
                self.table.setItemDelegateForColumn(i, self._chip)
            if c.width:
                hh.setSectionResizeMode(i, QHeaderView.Fixed)
                self.table.setColumnWidth(i, c.width)
        self.table.itemDoubleClicked.connect(lambda it: self.activated.emit(self._row_at(it.row())))
        self.table.itemSelectionChanged.connect(self._on_select)
        lay.addWidget(self.table)
        self.bar = QWidget()
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(0, 8, 0, 0)
        self.info = label("", "Muted")
        self.size_combo = QComboBox()
        for n in ctx().theme.cfg["page_sizes"]:
            self.size_combo.addItem(f"{n} per page", n)
        self.size_combo.setCurrentIndex(1 if len(ctx().theme.cfg["page_sizes"]) > 1 else 0)
        self.size_combo.currentIndexChanged.connect(lambda: self.page_requested.emit(1, self.page_size))
        self.prev = button("", "ghost", "fa5s.chevron-left", lambda: self.page_requested.emit(self.page - 1, self.page_size))
        self.next = button("", "ghost", "fa5s.chevron-right", lambda: self.page_requested.emit(self.page + 1, self.page_size))
        bl.addWidget(self.info)
        bl.addStretch()
        bl.addWidget(self.size_combo)
        bl.addWidget(self.prev)
        bl.addWidget(self.next)
        lay.addWidget(self.bar)
        self.bar.setVisible(paginated)

    @property
    def page_size(self) -> int:
        return self.size_combo.currentData()

    def _row_at(self, r: int) -> dict:
        item = self.table.item(r, 0)
        return self.rows[item.data(Qt.UserRole + 1)] if item else {}

    def _on_select(self):
        items = self.table.selectedItems()
        if items:
            self.selected.emit(self._row_at(items[0].row()))

    def _display(self, c: Col, v) -> tuple[str, Any]:
        if c.fmt:
            return c.fmt(v), v
        if v is None:
            return "—", None
        if c.kind == "money":
            try:
                return money(v), float(v)
            except ValueError:
                return str(v), str(v)
        if c.kind == "datetime" and isinstance(v, str):
            return format_datetime(v), v
        if c.kind == "date" and isinstance(v, str):
            return format_date(v), v
        if c.kind == "id":
            return f"#{v}", int(v)
        if c.kind in ("int", "float"):
            try:
                return (f"{float(v):,.2f}" if c.kind == "float" else group_number(v)), float(v)
            except (TypeError, ValueError):
                return str(v), str(v)
        return str(v), str(v)

    def set_rows(self, rows: list[dict], total: int | None = None, page: int = 1):
        self.rows = rows
        self.page, self.total = page, total if total is not None else len(rows)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for ci, c in enumerate(self.columns):
                text, key = self._display(c, row.get(c.key))
                it = _SortItem(text)
                it.setData(Qt.UserRole, key)
                it.setData(Qt.UserRole + 1, r)
                if c.kind in ("money", "int", "float"):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, ci, it)
        self.table.setSortingEnabled(True)
        size = self.page_size or max(1, len(rows))
        pages = max(1, -(-self.total // size))
        start = (page - 1) * size + 1 if rows else 0
        self.info.setText(f"Showing {start}–{start + len(rows) - 1 if rows else 0} of {group_number(self.total)}")
        self.prev.setEnabled(page > 1)
        self.next.setEnabled(page < pages)


@dataclass
class Field:
    name: str
    label: str
    kind: str = "text"  # text | password | int | decimal | combo | multiline | email
    required: bool = False
    choices: list[tuple[str, Any]] = field(default_factory=list)
    minimum: float | None = None
    maximum: float | None = None
    pattern: str | None = None
    message: str | None = None
    placeholder: str = ""
    validator: Callable[[Any, dict], str | None] | None = None


EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class ValidatedForm(QWidget):
    """Form with client-side validation and inline error labels (server errors can be shown too)."""

    def __init__(self, fields: list[Field], columns: int = 1, parent=None):
        super().__init__(parent)
        self.fields = {f.name: f for f in fields}
        self.inputs: dict[str, QWidget] = {}
        self.errors: dict[str, QLabel] = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        for i, f in enumerate(fields):
            w = self._make(f)
            self.inputs[f.name] = w
            err = label("", "FieldError")
            err.hide()
            self.errors[f.name] = err
            row, col = divmod(i, columns)
            box = QVBoxLayout()
            box.setSpacing(4)
            box.addWidget(label(f.label if f.required else f"{f.label} (optional)", "FieldLabel"))
            box.addWidget(w)
            box.addWidget(err)
            grid.addLayout(box, row, col)

    def _make(self, f: Field) -> QWidget:
        if f.kind == "int":
            w = QSpinBox()
            w.setRange(int(f.minimum if f.minimum is not None else -10**9), int(f.maximum if f.maximum is not None else 10**9))
        elif f.kind == "decimal":
            w = QDoubleSpinBox()
            w.setDecimals(2)
            w.setRange(f.minimum if f.minimum is not None else -10**9, f.maximum if f.maximum is not None else 10**9)
        elif f.kind == "combo":
            w = QComboBox()
            for text, value in f.choices:
                w.addItem(text, value)
        elif f.kind == "multiline":
            w = QPlainTextEdit()
            w.setFixedHeight(90)
            w.setPlaceholderText(f.placeholder)
        else:
            w = QLineEdit()
            w.setPlaceholderText(f.placeholder)
            if f.kind == "password":
                w.setEchoMode(QLineEdit.Password)
        return w

    def value(self, name: str):
        w = self.inputs[name]
        if isinstance(w, QSpinBox):
            return w.value()
        if isinstance(w, QDoubleSpinBox):
            return round(w.value(), 2)
        if isinstance(w, QComboBox):
            return w.currentData()
        if isinstance(w, QPlainTextEdit):
            return w.toPlainText().strip()
        return w.text().strip()

    def set_value(self, name: str, v):
        w = self.inputs[name]
        if isinstance(w, QSpinBox):
            w.setValue(int(v or 0))
        elif isinstance(w, QDoubleSpinBox):
            w.setValue(float(v or 0))
        elif isinstance(w, QComboBox):
            i = w.findData(v)
            w.setCurrentIndex(max(0, i))
        elif isinstance(w, QPlainTextEdit):
            w.setPlainText(str(v or ""))
        else:
            w.setText("" if v is None else str(v))

    def set_values(self, data: dict):
        for k, v in data.items():
            if k in self.inputs:
                self.set_value(k, v)

    def _error(self, name: str, msg: str | None):
        e, w = self.errors[name], self.inputs[name]
        w.setProperty("invalid", "true" if msg else "false")
        w.style().unpolish(w)
        w.style().polish(w)
        e.setText(msg or "")
        e.setVisible(bool(msg))

    def validate(self) -> dict | None:
        data = {n: self.value(n) for n in self.fields}
        ok = True
        for n, f in self.fields.items():
            v, msg = data[n], None
            if f.required and (v is None or v == ""):
                msg = "This field is required."
            elif f.kind == "email" and v and not re.match(EMAIL_RE, v):
                msg = "Enter a valid email address."
            elif f.pattern and v and not re.match(f.pattern, str(v)):
                msg = f.message or "Invalid format."
            elif f.kind in ("int", "decimal") and f.minimum is not None and v < f.minimum:
                msg = f"Must be at least {f.minimum}."
            elif f.validator:
                msg = f.validator(v, data)
            self._error(n, msg)
            ok = ok and not msg
        return data if ok else None

    def set_server_errors(self, errors: dict):
        for k, v in (errors or {}).items():
            if k in self.errors:
                self._error(k, " ".join(v) if isinstance(v, list) else str(v))


class ConfirmDialog(QDialog):
    def __init__(self, parent, title: str, text: str, confirm_text: str = "Confirm", danger: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icon("fa5s.exclamation-triangle" if danger else "fa5s.question-circle",
                          "danger" if danger else "primary").pixmap(28, 28))
        head.addWidget(ic)
        head.addWidget(label(title, "H2"), 1)
        lay.addLayout(head)
        lay.addWidget(label(text, wrap=True))
        bb = QDialogButtonBox()
        ok = button(confirm_text, "danger" if danger else "primary")
        cancel = button("Cancel")
        bb.addButton(ok, QDialogButtonBox.AcceptRole)
        bb.addButton(cancel, QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @staticmethod
    def ask(parent, title, text, confirm_text="Confirm", danger=False) -> bool:
        return ConfirmDialog(parent, title, text, confirm_text, danger).exec() == QDialog.Accepted


def show_error(parent, exc, title: str = "Something went wrong"):
    from .api_client import SessionExpired
    if isinstance(exc, SessionExpired):
        return  # the shell already returned to the login screen
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(str(exc))
    box.exec()


def show_info(parent, title: str, text: str):
    QMessageBox.information(parent, title, text)


class ImageLabel(QLabel):
    """Loads an image URL asynchronously (cached)."""

    _cache: dict[str, QPixmap] = {}

    def __init__(self, size: QSize, parent=None):
        super().__init__(parent)
        self.box = size
        self.setFixedSize(size)
        self.setAlignment(Qt.AlignCenter)
        t = ctx().theme
        self.setObjectName("Thumb")
        self.setPixmap(icon("fa5s.image", "muted").pixmap(32, 32))

    def load(self, url: str | None):
        if not url:
            return
        if url in self._cache:
            return self._show(self._cache[url])
        from .worker import run_async

        def done(data):
            if not data:
                return
            pm = QPixmap()
            pm.loadFromData(data)
            self._cache[url] = pm
            try:
                self._show(pm)
            except RuntimeError:
                pass
        run_async(lambda: ctx().api.fetch_bytes(url), done, lambda e: None)

    def _show(self, pm: QPixmap):
        # Letterbox on the photo's own backdrop colour so the image always fills its box
        scaled = pm.scaled(self.box, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        canvas = QPixmap(self.box)
        canvas.fill(QColor(pm.toImage().pixelColor(2, 2)))
        painter = QPainter(canvas)
        painter.drawPixmap((self.box.width() - scaled.width()) // 2, (self.box.height() - scaled.height()) // 2, scaled)
        painter.end()
        self.setPixmap(canvas)


class Timeline(QWidget):
    """Vertical status timeline (order history)."""

    def __init__(self, events: list[dict], parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        t = ctx().theme
        for i, ev in enumerate(events):
            row = QHBoxLayout()
            dot = QLabel()
            col = t.status_color(ev["to_status"])
            last = i == len(events) - 1
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background:{col}; border-radius:5px;")
            line = QFrame()
            line.setFixedWidth(2)
            line.setStyleSheet(f"background:{t.c['border'] if not last else 'transparent'};")
            left = QVBoxLayout()
            left.setSpacing(0)
            left.addWidget(dot, 0, Qt.AlignHCenter)
            left.addWidget(line, 1, Qt.AlignHCenter)
            row.addLayout(left)
            body = QVBoxLayout()
            body.setSpacing(2)
            top = QHBoxLayout()
            top.addWidget(label(t.status_label(ev["to_status"]), "Strong"))
            top.addWidget(label(format_datetime(ev["created_at"]), "Caption"))
            top.addStretch()
            body.addLayout(top)
            who = ev.get("actor_email") or str(ev.get("actor_label", "")).capitalize()
            note = ev.get("note") or ""
            body.addWidget(label(f"{note} · {who}" if note else who, "Caption", wrap=True))
            body.addSpacing(6)
            row.setAlignment(Qt.AlignTop)
            row.setSpacing(12)
            row.addLayout(body, 1)
            lay.addLayout(row)


class StatCard(Card):
    """KPI tile: small label, large value, optional one-line note (icon/colour args kept for callers)."""

    def __init__(self, title: str, value: str, icon_name: str = "", color_key: str = "primary", sub: str = ""):
        super().__init__(padding=18)
        self.lay.setSpacing(4)
        self.lay.addWidget(label(title, "Muted"))
        # Numbers get the large KPI style; words (e.g. an engine name) a calmer heading size
        self.value = label(value, "H2" if re.search(r"[A-Za-z]{3}", value) else "StatValue", wrap=True)
        self.lay.addWidget(self.value)
        if sub:
            self.lay.addWidget(label(sub, "Small", wrap=True))


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.NoFrame)
    return line


def rating_badge(value) -> QLabel:
    return label(f"{float(value):.1f} ★", "RatingBadge")


def hbox(*widgets, spacing: int = 8, stretch_last: bool = False) -> QHBoxLayout:
    l = QHBoxLayout()
    l.setSpacing(spacing)
    for w in widgets:
        if w is None:
            l.addStretch()
        elif isinstance(w, QWidget):
            l.addWidget(w)
        else:
            l.addLayout(w)
    if stretch_last:
        l.addStretch()
    return l
