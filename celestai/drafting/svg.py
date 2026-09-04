"""مُصدِّر SVG — vector floor plan for the browser."""

from __future__ import annotations

import math
from xml.sax.saxutils import escape

from .drawing import LAYERS, Arc, Circle, Drawing, Line, Poly, Text

PX_PER_M = 46.0            # مقياس العرض الافتراضي
LW_SCALE = 3.4             # تحويل سُمك القلم من مم للبكسل


class _Ctx:
    def __init__(self, dw: Drawing, px_per_m: float):
        self.s = px_per_m
        self.x0, self.y0, self.x1, self.y1 = dw.bounds
        self.h = (self.y1 - self.y0) * px_per_m

    def X(self, x: float) -> float:
        return (x - self.x0) * self.s

    def Y(self, y: float) -> float:
        return self.h - (y - self.y0) * self.s      # قلب المحور الرأسي

    def L(self, v: float) -> float:
        return v * self.s


def _lw(layer: str, scale: float) -> float:
    return max(LAYERS[layer].lineweight * LW_SCALE * scale, 0.55)


def _dash(dash, ctx: _Ctx) -> str:
    if not dash:
        return ""
    return f' stroke-dasharray="{" ".join(f"{ctx.L(d):.2f}" for d in dash)}"'


def render_svg(dw: Drawing, px_per_m: float = PX_PER_M, language: str = "ar") -> str:
    ctx = _Ctx(dw, px_per_m)
    W = (ctx.x1 - ctx.x0) * px_per_m
    H = ctx.h
    out: list[str] = []

    for e in dw.entities:
        if isinstance(e, Poly):
            pts = " ".join(f"{ctx.X(x):.2f},{ctx.Y(y):.2f}" for x, y in e.points)
            fill = e.fill or "none"
            stroke = LAYERS[e.layer].colour if e.stroke else "none"
            tag = "polygon" if e.closed else "polyline"
            out.append(
                f'<{tag} points="{pts}" fill="{fill}" stroke="{stroke}" '
                f'stroke-width="{_lw(e.layer, e.width_scale):.2f}"'
                f'{_dash(e.dash, ctx)} stroke-linejoin="round"/>'
            )

        elif isinstance(e, Line):
            out.append(
                f'<line x1="{ctx.X(e.x1):.2f}" y1="{ctx.Y(e.y1):.2f}" '
                f'x2="{ctx.X(e.x2):.2f}" y2="{ctx.Y(e.y2):.2f}" '
                f'stroke="{LAYERS[e.layer].colour}" '
                f'stroke-width="{_lw(e.layer, e.width_scale):.2f}"'
                f'{_dash(e.dash, ctx)} stroke-linecap="round"/>'
            )

        elif isinstance(e, Arc):
            # SVG محورها y لتحت، فبنعكس الزوايا
            a0, a1 = math.radians(e.a0), math.radians(e.a1)
            x0, y0 = e.cx + e.r * math.cos(a0), e.cy + e.r * math.sin(a0)
            x1, y1 = e.cx + e.r * math.cos(a1), e.cy + e.r * math.sin(a1)
            sweep = (e.a1 - e.a0) % 360
            large = 1 if sweep > 180 else 0
            out.append(
                f'<path d="M {ctx.X(x0):.2f} {ctx.Y(y0):.2f} '
                f'A {ctx.L(e.r):.2f} {ctx.L(e.r):.2f} 0 {large} 0 '
                f'{ctx.X(x1):.2f} {ctx.Y(y1):.2f}" fill="none" '
                f'stroke="{LAYERS[e.layer].colour}" '
                f'stroke-width="{_lw(e.layer, e.width_scale):.2f}"{_dash(e.dash, ctx)}/>'
            )

        elif isinstance(e, Circle):
            out.append(
                f'<circle cx="{ctx.X(e.cx):.2f}" cy="{ctx.Y(e.cy):.2f}" '
                f'r="{ctx.L(e.r):.2f}" fill="{e.fill or "none"}" '
                f'stroke="{LAYERS[e.layer].colour}" '
                f'stroke-width="{_lw(e.layer, e.width_scale):.2f}"/>'
            )

        elif isinstance(e, Text):
            anchor = {"start": "start", "middle": "middle", "end": "end"}[e.anchor]
            x, y = ctx.X(e.x), ctx.Y(e.y)
            transform = f' transform="rotate({-e.rotation} {x:.2f} {y:.2f})"' if e.rotation else ""
            weight = ' font-weight="600"' if e.bold else ""
            out.append(
                f'<text x="{x:.2f}" y="{y:.2f}" font-size="{ctx.L(e.size):.2f}" '
                f'fill="{LAYERS[e.layer].colour}" text-anchor="{anchor}" '
                f'dominant-baseline="middle"{weight}{transform}>'
                f"{escape(e.text)}</text>"
            )

    # لوحة البيانات (title block)
    tb = _title_block(dw, ctx, W, H)

    # الرسمة ممكن تتحقن جوه صفحة RTL، وساعتها الاتجاه الموروث بيقلب معنى
    # text-anchor وبيعكس ترتيب "34.21 m²". بنثبّت الاتجاه LTR على مستوى الرسمة
    # ونعزل كل نص لوحده، فالعربي بيتشكّل صح والأرقام ما تنقلبش.
    style = (
        "<style>text{direction:ltr;unicode-bidi:isolate;"
        "font-family:'Segoe UI',Tahoma,Arial,sans-serif;"
        "-webkit-user-select:none;user-select:none}</style>"
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" '
        f'height="{H:.0f}" viewBox="0 0 {W:.2f} {H:.2f}" direction="ltr">'
        f"{style}"
        f'<rect width="100%" height="100%" fill="#FFFFFF"/>'
        f'<g>{"".join(out)}</g>{tb}</svg>'
    )


def _title_block(dw: Drawing, ctx: _Ctx, W: float, H: float) -> str:
    if not dw.title and not dw.meta:
        return ""
    pad = 12.0
    bw = min(max(W * 0.30, 210.0), 330.0)
    rows = list(dw.meta.items())
    bh = 46.0 + len(rows) * 17.0 + (16.0 if dw.subtitle else 0.0)
    bx, by = W - bw - pad, pad

    parts = [
        f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
        f'fill="#FFFFFF" stroke="#1B2430" stroke-width="1.2"/>',
        f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="26" '
        f'fill="#1B2430"/>',
        f'<text x="{bx + bw - 10:.1f}" y="{by + 18:.1f}" font-size="13" '
        f'fill="#FFFFFF" text-anchor="end" font-weight="600">'
        f"{escape(dw.title or 'CelestAI')}</text>",
        f'<text x="{bx + 10:.1f}" y="{by + 18:.1f}" font-size="10.5" '
        f'fill="#9FB3C8" text-anchor="start">CelestAI</text>',
    ]
    y = by + 42.0
    if dw.subtitle:
        parts.append(
            f'<text x="{bx + bw - 10:.1f}" y="{y:.1f}" font-size="11" '
            f'fill="#5A6779" text-anchor="end">'
            f"{escape(dw.subtitle)}</text>"
        )
        y += 16.0
    for k, v in rows:
        parts.append(
            f'<text x="{bx + bw - 10:.1f}" y="{y:.1f}" font-size="10.5" '
            f'fill="#5A6779" text-anchor="end">{escape(k)}</text>'
        )
        parts.append(
            f'<text x="{bx + 10:.1f}" y="{y:.1f}" font-size="10.5" '
            f'fill="#1B2430" text-anchor="start" font-weight="600">{escape(v)}</text>'
        )
        y += 17.0
    return "".join(parts)
