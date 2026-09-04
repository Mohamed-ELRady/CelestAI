"""مُصدِّر PDF — لوحة جاهزة للطباعة بمقياس رسم حقيقي.

النص العربي بيتعمله reshaping + bidi عشان الحروف تتوصّل صح في الـ PDF
(المتصفح بيعمل ده لوحده في الـ SVG، لكن reportlab لأ).
"""

from __future__ import annotations

import os
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A3, A2, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

from .drawing import LAYERS, Arc, Circle, Drawing, Line, Poly, Text

# خطوط عربية محتملة حسب النظام
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Tahoma.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

_FONT = None
_FONT_BOLD = None


def _register_font() -> tuple[str, str]:
    """يسجّل خط يدعم العربي، ويرجّع (عادي، عريض)."""
    global _FONT, _FONT_BOLD
    if _FONT:
        return _FONT, _FONT_BOLD

    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("CelestAI", path))
                _FONT = "CelestAI"
                break
            except Exception:  # noqa: BLE001
                continue
    if not _FONT:
        _FONT = "Helvetica"

    for path in ("/System/Library/Fonts/Supplemental/Tahoma Bold.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"):
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("CelestAI-Bold", path))
                _FONT_BOLD = "CelestAI-Bold"
                break
            except Exception:  # noqa: BLE001
                continue
    _FONT_BOLD = _FONT_BOLD or ("Helvetica-Bold" if _FONT == "Helvetica" else _FONT)
    return _FONT, _FONT_BOLD


def shape_arabic(text: str) -> str:
    """يوصّل الحروف العربية ويعكس اتجاه النص للعرض في PDF."""
    if not any("\u0600" <= c <= "\u06FF" for c in text):
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text))
    except Exception:  # noqa: BLE001
        return text


def render_pdf(dw: Drawing, path: str | Path, page: str = "A3") -> str:
    """لوحة واحدة في ملف PDF."""
    return render_pdf_multi([dw], path, page)


def render_pdf_multi(
    drawings: list[Drawing], path: str | Path, page: str = "A3"
) -> str:
    """كل رسمة في صفحة — أدوار المبنى بتطلع ملف واحد مرتّب."""
    font, font_bold = _register_font()
    pagesize = landscape(A2 if page.upper() == "A2" else A3)
    pw, ph = pagesize

    c = rl_canvas.Canvas(str(path), pagesize=pagesize)
    c.setTitle(drawings[0].title if drawings else "CelestAI Floor Plan")
    c.setAuthor("CelestAI")
    for dw in drawings:
        _draw_page(c, dw, pw, ph, font, font_bold)
        c.showPage()
    c.save()
    return str(path)


def _draw_page(c, dw: Drawing, pw: float, ph: float, font: str, font_bold: str) -> None:
    # نحسب المقياس عشان الرسمة تملى الورقة مع هامش
    margin = 14 * mm
    avail_w, avail_h = pw - 2 * margin, ph - 2 * margin
    s = min(avail_w / max(dw.width, 1e-6), avail_h / max(dw.height, 1e-6))

    # مقياس الرسم: كام مليمتر على الورق بيمثّلوا متر في الواقع
    mm_per_metre = s / mm
    denom = 1000.0 / max(mm_per_metre, 1e-9)
    nice = min([25, 50, 75, 100, 125, 150, 200, 250, 500], key=lambda d: abs(d - denom))

    ox = margin + (avail_w - dw.width * s) / 2 - dw.bounds[0] * s
    oy = margin + (avail_h - dw.height * s) / 2 - dw.bounds[1] * s

    def X(x: float) -> float:
        return ox + x * s

    def Y(y: float) -> float:
        return oy + y * s

    def stroke_setup(layer: str, width_scale: float, dash) -> None:
        lay = LAYERS[layer]
        c.setStrokeColor(HexColor(lay.colour))
        c.setLineWidth(max(lay.lineweight * mm * width_scale, 0.25))
        c.setDash(*( [ [d * s for d in dash], 0 ] if dash else [[], 0] ))

    for e in dw.entities:
        if isinstance(e, Poly):
            p = c.beginPath()
            p.moveTo(X(e.points[0][0]), Y(e.points[0][1]))
            for x, y in e.points[1:]:
                p.lineTo(X(x), Y(y))
            if e.closed:
                p.close()
            stroke_setup(e.layer, e.width_scale, e.dash)
            if e.fill:
                col = e.fill[:7]
                c.setFillColor(HexColor(col))
            c.drawPath(p, stroke=1 if e.stroke else 0, fill=1 if e.fill else 0)

        elif isinstance(e, Line):
            stroke_setup(e.layer, e.width_scale, e.dash)
            c.line(X(e.x1), Y(e.y1), X(e.x2), Y(e.y2))

        elif isinstance(e, Arc):
            stroke_setup(e.layer, e.width_scale, e.dash)
            extent = (e.a1 - e.a0) % 360
            if extent > 180:
                extent -= 360
            c.arc(
                X(e.cx - e.r), Y(e.cy - e.r), X(e.cx + e.r), Y(e.cy + e.r),
                startAng=e.a0, extent=extent,
            )

        elif isinstance(e, Circle):
            stroke_setup(e.layer, e.width_scale, None)
            if e.fill:
                c.setFillColor(HexColor(e.fill[:7]))
            c.circle(X(e.cx), Y(e.cy), e.r * s, stroke=1, fill=1 if e.fill else 0)

        elif isinstance(e, Text):
            c.saveState()
            c.setDash([], 0)
            c.setFillColor(HexColor(LAYERS[e.layer].colour))
            c.setFont(font_bold if e.bold else font, max(e.size * s, 3.2))
            txt = shape_arabic(e.text)
            c.translate(X(e.x), Y(e.y))
            if e.rotation:
                c.rotate(e.rotation)
            dy = -max(e.size * s, 3.2) * 0.34
            if e.anchor == "middle":
                c.drawCentredString(0, dy, txt)
            elif e.anchor == "end":
                c.drawRightString(0, dy, txt)
            else:
                c.drawString(0, dy, txt)
            c.restoreState()

    _title_block(c, dw, pw, ph, font, font_bold, nice)


def _title_block(c, dw: Drawing, pw: float, ph: float, font: str,
                 font_bold: str, scale_denom: int) -> None:
    c.setDash([], 0)
    bw, pad = 78 * mm, 10 * mm
    rows = list(dw.meta.items()) + [("مقياس الرسم", f"1 : {scale_denom}")]
    bh = 16 * mm + len(rows) * 5.4 * mm + (5 * mm if dw.subtitle else 0)
    bx, by = pw - bw - pad, pad

    c.setFillColor(HexColor("#FFFFFF"))
    c.setStrokeColor(HexColor("#1B2430"))
    c.setLineWidth(0.9)
    c.rect(bx, by, bw, bh, stroke=1, fill=1)

    c.setFillColor(HexColor("#1B2430"))
    c.rect(bx, by + bh - 9 * mm, bw, 9 * mm, stroke=0, fill=1)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont(font_bold, 10.5)
    c.drawRightString(bx + bw - 4 * mm, by + bh - 6.2 * mm,
                      shape_arabic(dw.title or "CelestAI"))
    c.setFont(font, 8)
    c.setFillColor(HexColor("#9FB3C8"))
    c.drawString(bx + 4 * mm, by + bh - 6.2 * mm, "CelestAI")

    y = by + bh - 14 * mm
    if dw.subtitle:
        c.setFillColor(HexColor("#5A6779"))
        c.setFont(font, 8)
        c.drawRightString(bx + bw - 4 * mm, y, shape_arabic(dw.subtitle))
        y -= 5 * mm

    for k, v in rows:
        c.setFillColor(HexColor("#5A6779"))
        c.setFont(font, 8)
        c.drawRightString(bx + bw - 4 * mm, y, shape_arabic(k))
        c.setFillColor(HexColor("#1B2430"))
        c.setFont(font_bold, 8)
        c.drawString(bx + 4 * mm, y, shape_arabic(v))
        y -= 5.4 * mm
