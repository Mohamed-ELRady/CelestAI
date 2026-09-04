"""تصدير مجسّم ثلاثي الأبعاد — extruded model for the browser viewer."""

from __future__ import annotations

from .knowledge import SLAB_HEIGHT, UNROOFED
from .models import Layout

ZONE_COLOUR = {
    "day": "#BFD4E8",
    "night": "#CFC4E2",
    "service": "#C0DCCF",
    "circulation": "#E8DCC0",
}


def _wall_boxes(layout: Layout) -> list[dict]:
    """يحوّل كل مقطع حائط لصندوق، مقطوع عند الفتحات."""
    boxes: list[dict] = []

    for wall in layout.walls:
        cuts = sorted(
            (
                o for o in layout.openings
                if o.axis == wall.axis and abs(o.coord - wall.coord) < 1e-3
                and o.end > wall.start and o.start < wall.end
            ),
            key=lambda o: o.start,
        )

        def box(a: float, b: float, z0: float, z1: float) -> None:
            if b - a < 1e-3 or z1 - z0 < 1e-3:
                return
            if wall.axis == "v":
                boxes.append({
                    "cx": wall.coord, "cy": (a + b) / 2, "cz": (z0 + z1) / 2,
                    "sx": wall.thickness, "sy": b - a, "sz": z1 - z0,
                    "exterior": wall.exterior,
                })
            else:
                boxes.append({
                    "cx": (a + b) / 2, "cy": wall.coord, "cz": (z0 + z1) / 2,
                    "sx": b - a, "sy": wall.thickness, "sz": z1 - z0,
                    "exterior": wall.exterior,
                })

        cursor = wall.start
        for o in cuts:
            box(cursor, max(cursor, o.start), 0.0, SLAB_HEIGHT)
            # الجزء اللي فوق وتحت الفتحة
            top = o.sill + o.height
            if o.kind == "window":
                box(o.start, o.end, 0.0, o.sill)
            box(o.start, o.end, min(top, SLAB_HEIGHT), SLAB_HEIGHT)
            cursor = max(cursor, o.end)
        box(cursor, wall.end, 0.0, SLAB_HEIGHT)

    return boxes


def build_model(layout: Layout) -> dict:
    """JSON جاهز للعرض بـ Three.js."""
    return {
        "units": "m",
        "wallHeight": SLAB_HEIGHT,
        "plot": {
            "x": layout.plot.x, "y": layout.plot.y,
            "w": layout.plot.w, "h": layout.plot.h,
        },
        "walls": _wall_boxes(layout),
        "floors": [
            {
                "id": r.spec_id,
                "nameAr": r.name_ar,
                "nameEn": r.name_en,
                "x": r.net_rect.x, "y": r.net_rect.y,
                "w": r.net_rect.w, "h": r.net_rect.h,
                "colour": ZONE_COLOUR.get(r.zone.value, "#DDE3EA"),
                "unroofed": r.kind in UNROOFED,
                "area": round(r.net_area, 2),
            }
            for r in layout.rooms
        ],
        "openings": [
            {
                "kind": o.kind,
                "axis": o.axis,
                "coord": o.coord,
                "start": o.start,
                "width": o.width,
                "sill": o.sill,
                "height": o.height,
            }
            for o in layout.openings
        ],
        "entrySide": layout.entry_side,
        "northAngle": layout.north_angle,
    }


# ---------------------------------------------------------------------------
# مجسّم المبنى متعدد الأدوار
# ---------------------------------------------------------------------------


def build_building_model(req, floors) -> dict:
    """مجسّم المبنى: كل دور بيتبني على منسوبه الرأسي."""
    from .knowledge import FLOOR_TO_FLOOR

    levels = []
    base_level = min((f.level for f in floors), default=0)
    for f in floors:
        model = build_model(f.plate)
        model["level"] = f.level
        model["baseZ"] = round((f.level - base_level) * FLOOR_TO_FLOOR, 3)
        model["labelAr"] = f.label_ar
        model["labelEn"] = f.label_en
        model["use"] = f.use.value
        model["units"] = [
            {
                "id": u.unit_id, "nameAr": u.name_ar, "nameEn": u.name_en,
                "x": u.rect.x, "y": u.rect.y, "w": u.rect.w, "h": u.rect.h,
                "area": round(u.area, 2),
            }
            for u in f.units
        ]
        levels.append(model)

    return {
        "units": "m",
        "kind": "building",
        "floorHeight": FLOOR_TO_FLOOR,
        "floorCount": len(floors),
        "plot": levels[0]["plot"] if levels else {},
        "levels": levels,
    }
