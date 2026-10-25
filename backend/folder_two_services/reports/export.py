import csv
import io

from django.utils import timezone

from backend.shared.formatting import MONEY_COLUMNS, format_datetime, format_money
from config.loader import business, theme


def _unicode_font() -> str:
    """Register DejaVu Sans (shipped with matplotlib, which the project already depends on) so the
    PDF can print the rupee sign; the built-in PDF fonts have no ₹ glyph."""
    from pathlib import Path

    import matplotlib
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    name = "DejaVuSans"
    if name not in pdfmetrics.getRegisteredFontNames():
        base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        pdfmetrics.registerFont(TTFont(name, str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont(name + "-Bold", str(base / "DejaVuSans-Bold.ttf")))
    return name


def to_csv(report: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(report["columns"])
    w.writerows(report["rows"])
    return buf.getvalue().encode("utf-8")


def to_pdf(report: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    pal = theme()["modes"]["light"]
    max_rows = business()["reports"]["pdf_max_rows"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title=report["title"])
    styles = getSampleStyleSheet()
    font = _unicode_font()
    for st in styles.byName.values():
        st.fontName = font + "-Bold" if "Title" in st.name or st.name.startswith("Heading") else font
    money_cols = {i for i, c in enumerate(report["columns"]) if c in MONEY_COLUMNS}
    rows = [[format_money(c) if i in money_cols else str(c) for i, c in enumerate(r)]
            for r in report["rows"][:max_rows]]
    story = [Paragraph(report["title"], styles["Title"]),
             Paragraph(f"Generated {format_datetime(timezone.now())}", styles["Normal"]), Spacer(1, 12)]
    if rows:
        t = Table([report["columns"]] + rows, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(pal["primary"])),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(pal["primary_text"])),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(pal["surface_alt"])]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(pal["border"])),
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTNAME", (0, 0), (-1, 0), font + "-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(t)
        if len(report["rows"]) > max_rows:
            story.append(Paragraph(f"Showing {max_rows} of {len(report['rows'])} rows. Export CSV for all rows.",
                                   styles["Italic"]))
    else:
        story.append(Paragraph("No data for this period.", styles["Normal"]))
    doc.build(story)
    return buf.getvalue()
