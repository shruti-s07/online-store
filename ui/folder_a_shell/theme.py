"""Builds the Qt stylesheet from config/theme.json (palette, fonts, radii, spacing)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont

from config.loader import theme as theme_cfg


class Theme:
    def __init__(self, mode: str | None = None):
        self.cfg = theme_cfg()
        self.mode = mode or self.cfg["default_mode"]

    @property
    def c(self) -> dict:
        return self.cfg["modes"][self.mode]

    def toggle(self) -> str:
        self.mode = "dark" if self.mode == "light" else "light"
        return self.mode

    def status_label(self, status: str) -> str:
        """'ON_HOLD' -> 'On hold' (overrides in theme.json status_labels)."""
        text = self.cfg.get("status_labels", {}).get(status)
        if text:
            return text
        words = status.replace("_", " ").strip().lower()
        return words[:1].upper() + words[1:]

    def status_text_color(self, status: str) -> str:
        key = self.cfg["status_colors"].get(status, "muted")
        return self.c["warning_text"] if key == "warning" else self.c[key]

    def status_color(self, status: str) -> str:
        key = self.cfg["status_colors"].get(status, "muted")
        return self.c[key]

    def font(self, size_pt: int | None = None, bold: bool = False) -> QFont:
        f = QFont(self.cfg["font_family"].split(",")[0].strip())
        f.setPointSize(size_pt or self.cfg["font_size_pt"])
        f.setBold(bold)
        return f

    def qcolor(self, key: str) -> QColor:
        return QColor(self.c[key])

    @staticmethod
    def alpha(hex_color: str, a: float) -> str:
        col = QColor(hex_color)
        return f"rgba({col.red()},{col.green()},{col.blue()},{int(a * 255)})"

    def _arrow_icons(self) -> dict[str, str]:
        """Render chevrons for combo/spin boxes to PNG files (QSS needs image URLs)."""
        import tempfile
        from pathlib import Path

        import qtawesome as qta
        d = Path(tempfile.gettempdir()) / "online_store_ui"
        d.mkdir(exist_ok=True)
        out = {}
        for name, glyph in (("up", "fa5s.chevron-up"), ("down", "fa5s.chevron-down")):
            p = d / f"{name}_{self.mode}.png"
            qta.icon(glyph, color=self.c["muted"]).pixmap(20, 20).save(str(p))
            out[name] = p.as_posix()
        return out

    def stylesheet(self) -> str:
        c, r, sr = self.c, self.cfg["radius_px"], self.cfg["small_radius_px"]
        fs = self.cfg["font_size_pt"]
        arrows = self._arrow_icons()
        return f"""
* {{ font-family: {self.cfg['font_family']}; font-size: {fs}pt; color: {c['text']}; }}
QMainWindow, QDialog, #Page {{ background: {c['background']}; }}
QWidget#Page {{ background: {c['background']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
#Sidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['border']}; }}
#Sidebar QLabel {{ color: {c['sidebar_text']}; }}
#Logo {{ color: {c['primary']}; font-size: {fs + 7}pt; font-weight: 700; }}
#LogoSub {{ color: {c['muted']}; font-size: {fs - 1}pt; }}
#NavSection {{ color: {c['subtle']}; font-size: {fs - 2}pt; font-weight: 600; padding: 14px 10px 4px 10px;
               letter-spacing: 0.6px; }}
QPushButton#NavButton {{ background: transparent; color: {c['sidebar_text']}; border: none; text-align: left;
               padding: 7px 10px; border-radius: {sr}px; font-weight: 400; }}
QPushButton#NavButton:hover {{ background: {c['surface_alt']}; }}
QPushButton#NavButton:checked {{ background: {c['sidebar_active']}; color: {c['sidebar_active_text']}; font-weight: 600; }}
#TopBar, #StoreHeader {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
QPushButton#HeaderLink {{ background: transparent; border: none; padding: 6px 4px; font-weight: 500; }}
QPushButton#HeaderLink:hover {{ color: {c['primary']}; }}
QPushButton#HeaderLink:checked {{ color: {c['primary']}; font-weight: 600; }}
QLineEdit#HeaderSearch {{ background: {c['background']}; border: 1px solid {c['input_border']}; border-radius: {sr}px;
               padding: 8px 12px; }}
#CountBadge {{ background: {c['primary']}; color: {c['primary_text']}; border-radius: 9px; padding: 1px 6px;
               font-size: {fs - 2}pt; font-weight: 600; }}
#Avatar {{ background: {c['primary_soft']}; color: {c['primary']}; border-radius: 16px; font-weight: 600;
               font-size: {fs - 1}pt; }}
QPushButton#MenuButton::menu-indicator {{ image: none; width: 0; }}
#PageTitle {{ font-size: {self.cfg['heading_size_pt']}pt; font-weight: 600; }}
#Subtitle, #Muted {{ color: {c['muted']}; }}
#Small {{ color: {c['muted']}; font-size: {fs - 1}pt; }}
#Caption {{ color: {c['subtle']}; font-size: {fs - 1}pt; }}
#Overline {{ color: {c['muted']}; font-size: {fs - 2}pt; font-weight: 600; letter-spacing: 0.6px; }}
#H2 {{ font-size: {self.cfg['subheading_size_pt']}pt; font-weight: 600; }}
#Strong {{ font-weight: 600; }}
#Brand {{ color: {c['primary']}; font-size: {fs - 1}pt; font-weight: 500; }}
#Link {{ color: {c['primary']}; font-weight: 500; }}
#Good {{ color: {c['success']}; font-weight: 500; }}
#Warn {{ color: {c['warning_text']}; font-weight: 500; }}
#Bad {{ color: {c['danger']}; font-weight: 500; }}
#RatingBadge {{ background: {c['success']}; color: #FFFFFF; border-radius: 4px; padding: 1px 6px;
               font-size: {fs - 2}pt; font-weight: 600; }}
#Tag {{ background: {c['surface_alt']}; color: {c['muted']}; border-radius: 4px; padding: 2px 8px; font-size: {fs - 1}pt; }}
#TagGood {{ background: {self.alpha(c['success'], 0.12)}; color: {c['success']}; border-radius: 4px; padding: 3px 8px;
               font-size: {fs - 1}pt; font-weight: 500; }}
#TagBad {{ background: {self.alpha(c['danger'], 0.10)}; color: {c['danger']}; border-radius: 4px; padding: 3px 8px;
               font-size: {fs - 1}pt; font-weight: 500; }}
#Divider {{ background: {c['border']}; max-height: 1px; min-height: 1px; }}
#Card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r}px; }}
#Card:hover[clickable="true"] {{ border: 1px solid {c['input_border']}; }}
#CardHead {{ background: {c['background']}; border-bottom: 1px solid {c['border']};
               border-top-left-radius: {r}px; border-top-right-radius: {r}px; }}
#Thumb {{ background: {c['background']}; border-radius: {sr}px; }}
#StatValue {{ font-size: {fs + 9}pt; font-weight: 600; }}
#Price {{ color: {c['text']}; font-weight: 600; font-size: {fs + 3}pt; }}
#PriceLarge {{ color: {c['text']}; font-weight: 600; font-size: {fs + 10}pt; }}
QPushButton {{ background: {c['surface']}; border: 1px solid {c['input_border']}; border-radius: {sr}px;
               padding: 7px 14px; font-weight: 500; }}
QPushButton:hover {{ background: {c['surface_alt']}; }}
QPushButton:disabled {{ color: {c['subtle']}; background: {c['surface_alt']}; border-color: {c['border']}; }}
QPushButton[variant="primary"], QPushButton[variant="success"] {{ background: {c['primary']}; color: {c['primary_text']};
               border: 1px solid {c['primary']}; font-weight: 600; }}
QPushButton[variant="primary"]:hover, QPushButton[variant="success"]:hover {{ background: {c['primary_hover']}; }}
QPushButton[variant="primary"]:disabled {{ background: {c['surface_alt']}; color: {c['subtle']}; border-color: {c['border']}; }}
QPushButton[variant="accent"], QPushButton[variant="secondary"] {{ background: {c['surface']}; color: {c['primary']};
               border: 1px solid {c['primary']}; font-weight: 600; }}
QPushButton[variant="accent"]:hover, QPushButton[variant="secondary"]:hover {{ background: {c['primary_soft']}; }}
QPushButton[variant="accent"]:disabled, QPushButton[variant="secondary"]:disabled {{ color: {c['subtle']};
               border-color: {c['border']}; background: {c['surface_alt']}; }}
QPushButton[variant="danger"] {{ background: {c['surface']}; color: {c['danger']}; border: 1px solid {self.alpha(c['danger'], 0.45)}; }}
QPushButton[variant="danger"]:hover {{ background: {self.alpha(c['danger'], 0.08)}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: none; color: {c['primary']}; padding: 7px 8px; }}
QPushButton[variant="ghost"]:hover {{ background: {c['surface_alt']}; }}
QPushButton[variant="ghost"]:disabled {{ background: transparent; color: {c['subtle']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background: {c['surface']}; border: 1px solid {c['input_border']}; border-radius: {sr}px; padding: 7px 10px;
    selection-background-color: {c['primary']}; selection-color: {c['primary_text']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {c['primary']}; }}
QLineEdit[invalid="true"], QComboBox[invalid="true"] {{ border: 1px solid {c['danger']}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none; }}
QComboBox::down-arrow {{ image: url({arrows['down']}); width: 10px; height: 10px; }}
QAbstractSpinBox {{ padding-right: 24px; }}
QAbstractSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 22px;
    border: none; background: transparent; margin-top: 3px; }}
QAbstractSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 22px;
    border: none; background: transparent; margin-bottom: 3px; }}
QAbstractSpinBox::up-arrow {{ image: url({arrows['up']}); width: 9px; height: 9px; }}
QAbstractSpinBox::down-arrow {{ image: url({arrows['down']}); width: 9px; height: 9px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{ image: none; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border']};
    selection-background-color: {c['primary_soft']}; selection-color: {c['text']}; }}
#FieldLabel {{ font-size: {fs - 1}pt; font-weight: 500; }}
#FieldError {{ color: {c['danger']}; font-size: {fs - 1}pt; }}
QTableView {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r}px;
    gridline-color: transparent; alternate-background-color: {c['surface']};
    selection-background-color: {c['primary_soft']}; selection-color: {c['text']}; }}
QTableView::item {{ padding: 6px 10px; border-bottom: 1px solid {c['border']}; }}
QHeaderView::section {{ background: {c['background']}; color: {c['muted']}; border: none;
    border-bottom: 1px solid {c['border']}; padding: 8px 10px; font-weight: 600; font-size: {fs - 1}pt; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 2px; margin-right: 22px; color: {c['muted']}; font-weight: 500;
    border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {c['primary']}; font-weight: 600; border-bottom: 2px solid {c['primary']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 6px; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['primary_soft']}; color: {c['text']}; }}
QSplitter::handle {{ background: transparent; }}
#Banner {{ border-radius: {sr}px; }}
#Banner[kind="error"] {{ background: {self.alpha(c['danger'], 0.08)}; border: 1px solid {self.alpha(c['danger'], 0.35)}; }}
#Banner[kind="warning"] {{ background: {self.alpha(c['warning'], 0.10)}; border: 1px solid {self.alpha(c['warning'], 0.35)}; }}
#Banner[kind="success"] {{ background: {self.alpha(c['success'], 0.08)}; border: 1px solid {self.alpha(c['success'], 0.35)}; }}
#Banner[kind="info"] {{ background: {self.alpha(c['info'], 0.07)}; border: 1px solid {self.alpha(c['info'], 0.30)}; }}
#ChatBubbleUser {{ background: {c['primary']}; color: {c['primary_text']}; border-radius: {r}px; padding: 10px 14px; }}
#ChatBubbleBot {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r}px; padding: 10px 14px; }}
#LoginPage {{ background: {c['background']}; }}
"""
