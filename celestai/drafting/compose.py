"""تحويل المخطط لرسمة معمارية — Layout → Drawing.

بيرسم: حوائط مقطوعة عند الفتحات، أبواب بدوران الفتح، شبابيك، فرش،
خطوط أبعاد متسلسلة، أسماء ومساحات الفراغات، سهم شمال، ومقياس رسم.
"""

from __future__ import annotations

import math

from ..knowledge import UNROOFED
from ..models import Layout, Opening, RoomKind, WallSegment, Zone
from .drawing import Arc, Circle, Drawing, Line, Poly, Text
from .furniture import draw_furniture

MARGIN = 2.6                      # هامش حول المبنى (متر) للأبعاد والعناوين
DIM_OFFSET_1 = 0.85               # سلسلة الأبعاد الأولى
DIM_OFFSET_2 = 1.75               # الأبعاد الكلية
TICK = 0.13

ZONE_FILL = {
    Zone.DAY: "#F3F7FB",
    Zone.NIGHT: "#F6F3FA",
    Zone.SERVICE: "#F2F8F5",
    Zone.CIRCULATION: "#FBF7EF",
}

# ---------------------------------------------------------------------------
# نصوص الرسمة بالعربي والإنجليزي — the drawing's own vocabulary
# ---------------------------------------------------------------------------

STRINGS: dict[str, dict[str, str]] = {
    "ar": {
        "metres": "متر",
        "entrance": "المدخل",
        "gross_area": "المساحة الإجمالية",
        "net_area": "المساحة الصافية",
        "efficiency": "كفاءة التوزيع",
        "plot_dims": "أبعاد القطعة",
        "entry_side": "جهة المدخل",
        "unit_m2": "م²",
        "unit_m": "م",
        "north": "الشمال", "south": "الجنوب", "east": "الشرق", "west": "الغرب",
    },
    "en": {
        "metres": "metres",
        "entrance": "Entrance",
        "gross_area": "Gross area",
        "net_area": "Net area",
        "efficiency": "Planning efficiency",
        "plot_dims": "Plot dimensions",
        "entry_side": "Entrance from",
        "unit_m2": "m²",
        "unit_m": "m",
        "north": "North", "south": "South", "east": "East", "west": "West",
    },
}


def L(language: str, key: str) -> str:
    """يرجّع نص الرسمة باللغة المطلوبة."""
    return STRINGS.get(language, STRINGS["ar"]).get(key, key)


# ---------------------------------------------------------------------------
# الحوائط والفتحات
# ---------------------------------------------------------------------------


def _openings_on(wall: WallSegment, openings: list[Opening]) -> list[Opening]:
    out = []
    for o in openings:
        if o.axis != wall.axis or abs(o.coord - wall.coord) > 1e-3:
            continue
        if o.end <= wall.start + 1e-4 or o.start >= wall.end - 1e-4:
            continue
        out.append(o)
    return sorted(out, key=lambda o: o.start)


def _wall_piece(dw: Drawing, wall: WallSegment, a: float, b: float) -> None:
    if b - a < 1e-3:
        return
    t = wall.thickness / 2
    layer = "WALL_EXT" if wall.exterior else "WALL_INT"
    colour = "#1B2430" if wall.exterior else "#3B4857"
    if wall.axis == "v":
        pts = [
            (wall.coord - t, a), (wall.coord + t, a),
            (wall.coord + t, b), (wall.coord - t, b),
        ]
    else:
        pts = [
            (a, wall.coord - t), (a, wall.coord + t),
            (b, wall.coord + t), (b, wall.coord - t),
        ]
    dw.add(Poly(pts, layer=layer, fill=colour, stroke=False))


def draw_walls(dw: Drawing, layout: Layout) -> None:
    """يرسم الحوائط مقطوعة عند كل فتحة."""
    for wall in layout.walls:
        cuts = _openings_on(wall, layout.openings)
        cursor = wall.start
        for o in cuts:
            _wall_piece(dw, wall, cursor, max(cursor, o.start))
            cursor = max(cursor, o.end)
        _wall_piece(dw, wall, cursor, wall.end)


def _door(dw: Drawing, o: Opening, thickness: float) -> None:
    """باب: عتب + درفة مفتوحة 90° + قوس الدوران."""
    if o.axis == "v":
        hx = o.coord
        hy = o.start if o.hinge > 0 else o.end
        along = (0.0, 1.0 if o.hinge > 0 else -1.0)
        perp = (float(o.swing), 0.0)
    else:
        hx = o.start if o.hinge > 0 else o.end
        hy = o.coord
        along = (1.0 if o.hinge > 0 else -1.0, 0.0)
        perp = (0.0, float(o.swing))

    w = o.width
    # عتبة الفتحة (خطوط الجوانب)
    t = thickness / 2
    if o.axis == "v":
        dw.add(Line(o.coord - t, o.start, o.coord + t, o.start, layer="DOOR"))
        dw.add(Line(o.coord - t, o.end, o.coord + t, o.end, layer="DOOR"))
    else:
        dw.add(Line(o.start, o.coord - t, o.start, o.coord + t, layer="DOOR"))
        dw.add(Line(o.end, o.coord - t, o.end, o.coord + t, layer="DOOR"))

    # الدرفة
    lx, ly = hx + perp[0] * w, hy + perp[1] * w
    dw.add(Line(hx, hy, lx, ly, layer="DOOR", width_scale=1.5))

    # قوس الدوران من وضع الغلق لوضع الفتح
    a_closed = math.degrees(math.atan2(along[1], along[0])) % 360
    a_open = math.degrees(math.atan2(perp[1], perp[0])) % 360
    diff = (a_open - a_closed) % 360
    if diff > 180:
        a0, a1 = a_open, a_closed
    else:
        a0, a1 = a_closed, a_open
    dw.add(Arc(hx, hy, w, a0, a1, layer="DOOR", dash=(0.10, 0.08)))


def _window(dw: Drawing, o: Opening, thickness: float) -> None:
    """شباك: إطار + خطوط الزجاج."""
    t = thickness / 2
    if o.axis == "v":
        dw.add(Poly(
            [(o.coord - t, o.start), (o.coord + t, o.start),
             (o.coord + t, o.end), (o.coord - t, o.end)],
            layer="WINDOW", fill="#FFFFFF", stroke=True,
        ))
        for f in (-0.34, 0.0, 0.34):
            dw.add(Line(o.coord + t * f * 2, o.start, o.coord + t * f * 2, o.end, layer="WINDOW"))
    else:
        dw.add(Poly(
            [(o.start, o.coord - t), (o.start, o.coord + t),
             (o.end, o.coord + t), (o.end, o.coord - t)],
            layer="WINDOW", fill="#FFFFFF", stroke=True,
        ))
        for f in (-0.34, 0.0, 0.34):
            dw.add(Line(o.start, o.coord + t * f * 2, o.end, o.coord + t * f * 2, layer="WINDOW"))


def draw_openings(dw: Drawing, layout: Layout) -> None:
    thick = {}
    for w in layout.walls:
        thick.setdefault((w.axis, round(w.coord, 3)), w.thickness)
        thick[(w.axis, round(w.coord, 3))] = max(
            thick[(w.axis, round(w.coord, 3))], w.thickness
        )

    for o in layout.openings:
        t = thick.get((o.axis, round(o.coord, 3)), 0.12)
        if o.kind == "window":
            _window(dw, o, t)
        else:
            _door(dw, o, t)


# ---------------------------------------------------------------------------
# الفراغات
# ---------------------------------------------------------------------------


def _hatch(dw: Drawing, x: float, y: float, w: float, h: float,
           spacing: float = 0.30, layer: str = "RAILING") -> None:
    """تظليل مائل — الاصطلاح المعماري للفراغ المكشوف للسما."""
    if w <= 0 or h <= 0:
        return
    t = spacing
    while t < w + h:
        # خط بميل 45°، مقصوص على حدود المستطيل
        x1, y1 = (x + t, y) if t <= w else (x + w, y + t - w)
        x2, y2 = (x, y + t) if t <= h else (x + t - h, y + h)
        dw.add(Line(x1, y1, x2, y2, layer=layer, width_scale=0.55))
        t += spacing


def draw_rooms(dw: Drawing, layout: Layout, language: str = "ar") -> None:
    for room in layout.rooms:
        n = room.net_rect
        fill = ZONE_FILL.get(room.zone, "#F5F7FA")
        if room.kind in UNROOFED:
            fill = "#FAFBFC"
        dw.rect(n.x, n.y, n.w, n.h, layer="ROOM_FILL", fill=fill, stroke=False)

        if room.kind == RoomKind.SHAFT:
            # المنور مكشوف للسما: تظليل مائل بدل الفرش
            _hatch(dw, n.x, n.y, n.w, n.h)
            continue
        if room.kind in UNROOFED:
            # درابزين البلكونة
            dw.rect(n.x + 0.06, n.y + 0.06, n.w - 0.12, n.h - 0.12,
                    layer="RAILING", dash=(0.14, 0.10))

        draw_furniture(dw, room)

    # الأسماء فوق الفرش عشان تفضل مقروءة
    for room in layout.rooms:
        n = room.net_rect
        if n.w < 0.85 or n.h < 0.85:
            continue
        name = room.name_ar if language == "ar" else room.name_en
        size = max(0.17, min(0.30, min(n.w, n.h) * 0.16))

        # خلفية بيضا خفيفة تحت النص عشان يبان فوق الفرش
        pad_w = min(n.w * 0.92, len(name) * size * 0.62 + 0.3)
        pad_h = size * (4.0 if min(n.w, n.h) > 1.9 else 2.9)
        dw.rect(n.cx - pad_w / 2, n.cy - pad_h * 0.62, pad_w, pad_h,
                layer="ROOM_FILL", fill="#FFFFFFCC", stroke=False)

        dw.add(Text(n.cx, n.cy + size * 0.55, name, size=size, layer="TEXT",
                    anchor="middle", bold=True, rtl=(language == "ar")))
        dw.add(Text(n.cx, n.cy - size * 0.85, f"{n.area:.2f} m²",
                    size=size * 0.82, layer="TEXT_SUB", anchor="middle"))
        if min(n.w, n.h) > 1.9:
            dw.add(Text(n.cx, n.cy - size * 2.05, f"{n.w:.2f} × {n.h:.2f}",
                        size=size * 0.70, layer="TEXT_SUB", anchor="middle"))


# ---------------------------------------------------------------------------
# خطوط الأبعاد
# ---------------------------------------------------------------------------


def _dim(dw: Drawing, x1: float, y1: float, x2: float, y2: float, label: str,
         horizontal: bool) -> None:
    dw.add(Line(x1, y1, x2, y2, layer="DIM"))
    if horizontal:
        dw.add(Line(x1, y1 - TICK, x1, y1 + TICK, layer="DIM"))
        dw.add(Line(x2, y2 - TICK, x2, y2 + TICK, layer="DIM"))
        dw.add(Text((x1 + x2) / 2, y1 + 0.10, label, size=0.20, layer="DIM",
                    anchor="middle"))
    else:
        dw.add(Line(x1 - TICK, y1, x1 + TICK, y1, layer="DIM"))
        dw.add(Line(x2 - TICK, y2, x2 + TICK, y2, layer="DIM"))
        dw.add(Text(x1 - 0.10, (y1 + y2) / 2, label, size=0.20, layer="DIM",
                    anchor="middle", rotation=90))


def draw_dimensions(dw: Drawing, layout: Layout) -> None:
    p = layout.plot

    xs = sorted({round(w.coord, 3) for w in layout.walls if w.axis == "v"})
    ys = sorted({round(w.coord, 3) for w in layout.walls if w.axis == "h"})

    # سلسلة الأبعاد الجزئية تحت المبنى
    y = p.y - DIM_OFFSET_1
    for a, b in zip(xs, xs[1:]):
        if b - a > 0.35:
            _dim(dw, a, y, b, y, f"{b - a:.2f}", horizontal=True)
            dw.add(Line(a, p.y - 0.12, a, y - 0.10, layer="GRID"))
    dw.add(Line(xs[-1], p.y - 0.12, xs[-1], y - 0.10, layer="GRID"))

    # سلسلة الأبعاد الجزئية على الشمال
    x = p.x - DIM_OFFSET_1
    for a, b in zip(ys, ys[1:]):
        if b - a > 0.35:
            _dim(dw, x, a, x, b, f"{b - a:.2f}", horizontal=False)
            dw.add(Line(p.x - 0.12, a, x - 0.10, a, layer="GRID"))
    dw.add(Line(p.x - 0.12, ys[-1], x - 0.10, ys[-1], layer="GRID"))

    # الأبعاد الكلية
    _dim(dw, p.x, p.y - DIM_OFFSET_2, p.x2, p.y - DIM_OFFSET_2,
         f"{p.w:.2f}", horizontal=True)
    _dim(dw, p.x - DIM_OFFSET_2, p.y, p.x - DIM_OFFSET_2, p.y2,
         f"{p.h:.2f}", horizontal=False)


# ---------------------------------------------------------------------------
# سهم الشمال + مقياس الرسم
# ---------------------------------------------------------------------------


def draw_north(dw: Drawing, layout: Layout) -> None:
    p = layout.plot
    cx, cy = p.x2 + 1.35, p.y2 - 0.55
    r = 0.55
    a = math.radians(90 + layout.north_angle)
    tipx, tipy = cx + r * math.cos(a), cy + r * math.sin(a)
    left = (cx + r * 0.42 * math.cos(a + 2.42), cy + r * 0.42 * math.sin(a + 2.42))
    right = (cx + r * 0.42 * math.cos(a - 2.42), cy + r * 0.42 * math.sin(a - 2.42))
    dw.add(Circle(cx, cy, r, layer="TEXT", fill=None))
    dw.add(Poly([(tipx, tipy), left, (cx, cy), right], layer="TEXT",
                fill="#1B2430", stroke=True))
    dw.add(Text(cx, cy - r - 0.42, "N", size=0.28, layer="TEXT",
                anchor="middle", bold=True))


def draw_scale_bar(dw: Drawing, layout: Layout, language: str = "ar") -> None:
    p = layout.plot
    x0, y0 = p.x, p.y - DIM_OFFSET_2 - 1.15
    seg = 1.0
    n = 5
    for i in range(n):
        fill = "#1B2430" if i % 2 == 0 else "#FFFFFF"
        dw.rect(x0 + i * seg, y0, seg, 0.17, layer="TEXT", fill=fill, stroke=True)
    for i in range(n + 1):
        dw.add(Text(x0 + i * seg, y0 - 0.34, str(i), size=0.19,
                    layer="TEXT_SUB", anchor="middle"))
    dw.add(Text(x0 + n * seg + 0.35, y0 - 0.02, L(language, "metres"), size=0.20,
                layer="TEXT_SUB", anchor="start", rtl=(language == "ar")))


# ---------------------------------------------------------------------------
# التجميع
# ---------------------------------------------------------------------------


def compose(layout: Layout, title: str = "", subtitle: str = "",
            language: str = "ar", furniture: bool = True) -> Drawing:
    dw = Drawing()
    p = layout.plot

    draw_rooms(dw, layout, language=language)
    draw_walls(dw, layout)
    draw_openings(dw, layout)
    draw_dimensions(dw, layout)
    draw_north(dw, layout)
    draw_scale_bar(dw, layout, language=language)

    # علامة المدخل
    entry = next((o for o in layout.openings if o.kind == "entry"), None)
    if entry:
        if entry.axis == "h":
            ex, ey = entry.mid, entry.coord
            ox, oy = 0.0, -0.72 if abs(ey - p.y) < 0.2 else 0.72
        else:
            ex, ey = entry.coord, entry.mid
            ox, oy = (-0.72 if abs(ex - p.x) < 0.2 else 0.72), 0.0
        dw.add(Line(ex + ox * 1.5, ey + oy * 1.5, ex + ox * 0.35, ey + oy * 0.35,
                    layer="DIM", width_scale=1.6))
        dw.add(Text(ex + ox * 2.0, ey + oy * 2.0, L(language, "entrance"), size=0.24,
                    layer="DIM", anchor="middle", rtl=(language == "ar")))

    # نحجز شريط فوق المبنى للوحة البيانات عشان ما تغطّيش على الرسم
    title_band = 1.10 + 0.34 * (len(layout.metrics and [1, 1, 1, 1, 1]) + (1 if subtitle else 0))
    dw.bounds = (
        p.x - MARGIN - 1.4,
        p.y - MARGIN - 2.2,
        p.x2 + MARGIN + 0.6,
        p.y2 + MARGIN * 0.45 + title_band,
    )
    m2, m = L(language, "unit_m2"), L(language, "unit_m")
    dw.title = title
    dw.subtitle = subtitle
    dw.meta = {
        L(language, "gross_area"): f"{layout.metrics.get('gross_area', 0):.2f} {m2}",
        L(language, "net_area"): f"{layout.metrics.get('net_area', 0):.2f} {m2}",
        L(language, "efficiency"): f"{layout.metrics.get('efficiency', 0) * 100:.1f}%",
        L(language, "plot_dims"): f"{p.w:.2f} × {p.h:.2f} {m}",
        L(language, "entry_side"): L(language, layout.entry_side),
    }
    return dw
