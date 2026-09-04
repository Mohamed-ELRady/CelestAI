"""رسم دور في مبنى متعدد الأدوار — Building floor plate drawing.

بيبني على نفس الرسّام بتاع الوحدة المستقلة، وبيزوّد فوقه طبقة المبنى:
حدود الوحدات بخط عريض، وأسماء الوحدات ومساحاتها، ورموز النواة الرأسية.
"""

from __future__ import annotations

from ..models import FloorPlan, FloorUse
from .compose import (
    MARGIN,
    L,
    draw_dimensions,
    draw_north,
    draw_openings,
    draw_rooms,
    draw_scale_bar,
    draw_walls,
)
from .drawing import Drawing, Line, Poly, Text

USE_TINT = {
    FloorUse.APARTMENTS: "#F6F3FA",
    FloorUse.OFFICES: "#F1F6FB",
    FloorUse.CLINICS: "#F1F9F5",
    FloorUse.RETAIL: "#FDF6EC",
    FloorUse.PARKING: "#F4F5F7",
    FloorUse.SERVICES: "#F4F5F7",
}

CORE_TINT = {
    "stair": "#E6EAF0",
    "lift": "#DCE3EC",
    "landing": "#FBF7EF",
    "shaft": "#EDF0F4",
}


def draw_unit_outlines(dw: Drawing, floor: FloorPlan, language: str = "ar") -> None:
    """حد كل وحدة بخط عريض + بطاقة اسمها ومساحتها.

    بيترسم فوق التوزيع الداخلي عشان الراسم يفرّق بسرعة بين حدود الشقة
    وحوائطها الداخلية.
    """
    ar = language == "ar"
    for unit in floor.units:
        r = unit.rect
        dw.add(Poly(
            [(r.x, r.y), (r.x2, r.y), (r.x2, r.y2), (r.x, r.y2)],
            layer="TITLE", fill=None, stroke=True, width_scale=2.1,
        ))

        # بطاقة الوحدة عند ركنها، بعيد عن أسماء الغرف في النص
        name = unit.name_ar if ar else unit.name_en
        area_txt = f"{unit.area:.1f} " + ("م²" if ar else "m²")
        size = max(0.22, min(0.36, min(r.w, r.h) * 0.075))
        pad_w = max(len(name), len(area_txt)) * size * 0.66 + 0.34
        pad_h = size * 2.9
        cx = r.x + pad_w / 2 + 0.20
        cy = r.y2 - pad_h / 2 - 0.20

        dw.rect(cx - pad_w / 2, cy - pad_h / 2, pad_w, pad_h,
                layer="TITLE", fill="#1B2430", stroke=False)
        dw.add(Text(cx, cy + size * 0.52, name, size=size, layer="ROOM_FILL",
                    anchor="middle", bold=True, rtl=ar))
        dw.add(Text(cx, cy - size * 0.72, area_txt, size=size * 0.82,
                    layer="ROOM_FILL", anchor="middle"))


def draw_core(dw: Drawing, floor: FloorPlan, language: str = "ar") -> None:
    """رموز النواة: درجات السلم وسهم الصعود، وعلامة × على بئر المصعد."""
    ar = language == "ar"
    for el in floor.core:
        r = el.net_rect
        if r.w < 0.4 or r.h < 0.4:
            continue
        dw.rect(r.x, r.y, r.w, r.h, layer="ROOM_FILL",
                fill=CORE_TINT.get(el.kind, "#F0F2F5"), stroke=False)

        if el.kind == "lift":
            dw.add(Line(r.x, r.y, r.x2, r.y2, layer="FURNITURE"))
            dw.add(Line(r.x, r.y2, r.x2, r.y, layer="FURNITURE"))
        elif el.kind == "stair":
            horiz = r.w >= r.h
            length = r.w if horiz else r.h
            n = max(3, int(length // 0.28))
            for i in range(1, n):
                t = i * (length / n)
                if horiz:
                    dw.add(Line(r.x + t, r.y, r.x + t, r.y2, layer="FURNITURE"))
                else:
                    dw.add(Line(r.x, r.y + t, r.x2, r.y + t, layer="FURNITURE"))
            if horiz:
                dw.add(Line(r.x + 0.2, r.cy, r.x2 - 0.2, r.cy,
                            layer="FURNITURE", width_scale=1.5))
                dw.add(Line(r.x2 - 0.45, r.cy - 0.13, r.x2 - 0.2, r.cy,
                            layer="FURNITURE", width_scale=1.5))
                dw.add(Line(r.x2 - 0.45, r.cy + 0.13, r.x2 - 0.2, r.cy,
                            layer="FURNITURE", width_scale=1.5))
            else:
                dw.add(Line(r.cx, r.y + 0.2, r.cx, r.y2 - 0.2,
                            layer="FURNITURE", width_scale=1.5))
                dw.add(Line(r.cx - 0.13, r.y2 - 0.45, r.cx, r.y2 - 0.2,
                            layer="FURNITURE", width_scale=1.5))
                dw.add(Line(r.cx + 0.13, r.y2 - 0.45, r.cx, r.y2 - 0.2,
                            layer="FURNITURE", width_scale=1.5))

        if min(r.w, r.h) > 1.1:
            label = el.name_ar if ar else el.name_en
            size = max(0.17, min(0.26, min(r.w, r.h) * 0.16))
            dw.add(Text(r.cx, r.cy, label, size=size, layer="TEXT_SUB",
                        anchor="middle", rtl=ar))


def compose_floor_plate(
    floor: FloorPlan, title: str = "", subtitle: str = "", language: str = "ar",
) -> Drawing:
    """يبني رسمة دور كامل — نفس ترتيب طبقات الوحدة المستقلة."""
    dw = Drawing()
    plate = floor.plate
    p = plate.plot
    ar = language == "ar"

    # خلفية بلون الاستخدام قبل أي حاجة، عشان الأدوار تتميّز بصريًا
    dw.rect(p.x, p.y, p.w, p.h, layer="ROOM_FILL",
            fill=USE_TINT.get(floor.use, "#F5F7FA"), stroke=False)

    draw_rooms(dw, plate, language=language)
    draw_core(dw, floor, language=language)
    draw_walls(dw, plate)
    draw_openings(dw, plate)
    draw_unit_outlines(dw, floor, language=language)
    draw_dimensions(dw, plate)
    draw_north(dw, plate)
    draw_scale_bar(dw, plate, language=language)

    m2 = "م²" if ar else "m²"
    unit_word = "وحدة" if ar else "units"
    title_band = 1.10 + 0.34 * 6
    dw.bounds = (
        p.x - MARGIN - 1.4, p.y - MARGIN - 2.2,
        p.x2 + MARGIN + 0.6, p.y2 + MARGIN * 0.45 + title_band,
    )
    dw.title = title or (floor.label_ar if ar else floor.label_en)
    dw.subtitle = subtitle
    dw.meta = {
        L(language, "gross_area"): f"{floor.metrics.get('gross_area', 0):.2f} {m2}",
        ("مساحة الوحدات" if ar else "Units area"):
            f"{floor.metrics.get('unit_area', 0):.2f} {m2}",
        ("النواة والبسطة" if ar else "Core & landing"):
            f"{floor.metrics.get('core_area', 0):.2f} {m2}",
        L(language, "efficiency"): f"{floor.metrics.get('efficiency', 0) * 100:.1f}%",
        ("عدد الوحدات" if ar else "Unit count"):
            f"{int(floor.metrics.get('units', 0))} {unit_word}",
        L(language, "entry_side"): L(language, plate.entry_side),
    }
    return dw


def floor_title(floor: FloorPlan, language: str = "ar") -> str:
    return floor.label_ar if language == "ar" else floor.label_en
