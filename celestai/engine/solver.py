"""الحل الكامل: من البرنامج المعماري للمخطط النهائي."""

from __future__ import annotations

from ..knowledge import UNROOFED
from ..models import (
    ArchitecturalProgram,
    DesignRequest,
    Layout,
    Opening,
    PlacedRoom,
    Rect,
)
from .layout import (
    CanonicalPlan,
    Placement,
    _canonical_candidates,
    _fill_placements,
    build_walls,
    wall_thickness_at,
)
from .openings import canonical_openings
from .plot import Transform, candidate_entry_sides, candidate_plots
from .validate import issue_penalty, validate


def _net_rect(rect: Rect, walls) -> Rect:
    left = wall_thickness_at(walls, "v", rect.x, rect.y, rect.y2) / 2
    right = wall_thickness_at(walls, "v", rect.x2, rect.y, rect.y2) / 2
    bottom = wall_thickness_at(walls, "h", rect.y, rect.x, rect.x2) / 2
    top = wall_thickness_at(walls, "h", rect.y2, rect.x, rect.x2) / 2
    return Rect(
        x=round(rect.x + left, 4),
        y=round(rect.y + bottom, 4),
        w=round(max(rect.w - left - right, 0.05), 4),
        h=round(max(rect.h - bottom - top, 0.05), 4),
    )


def materialise(
    plan: CanonicalPlan, transform: Transform, req: DesignRequest, plot: Rect
) -> Layout:
    _fill_placements(plan)

    # 1) تحويل المستطيلات للإحداثيات الفعلية
    actual: list[Placement] = []
    for pl in plan.placements:
        r = transform.rect(pl.x, pl.y, pl.w, pl.h)
        actual.append(Placement(pl.spec, r.x, r.y, r.w, r.h))

    # 2) الحوائط
    walls = build_walls(actual, plot)

    # 3) الفتحات
    openings: list[Opening] = []
    for o in canonical_openings(plan):
        axis, coord, start, swing, hinge = transform.opening(
            o.axis, o.coord, o.start, o.width, o.swing, o.hinge
        )
        openings.append(
            Opening(
                kind=o.kind, axis=axis, coord=round(coord, 4), start=round(start, 4),
                width=o.width, room_id=o.room_id, swing=swing, hinge=hinge,
                sill=o.sill, height=o.height,
            )
        )

    # 4) الغرف
    glazing: dict[str, float] = {}
    for o in openings:
        if o.kind == "window":
            glazing[o.room_id] = glazing.get(o.room_id, 0.0) + o.width * o.height

    rooms: list[PlacedRoom] = []
    for pl in actual:
        rect = Rect(x=pl.x, y=pl.y, w=pl.w, h=pl.h)
        rooms.append(
            PlacedRoom(
                spec_id=pl.spec.id,
                name_ar=pl.spec.name_ar,
                name_en=pl.spec.name_en,
                kind=pl.spec.kind,
                zone=pl.spec.zone,
                rect=rect,
                net_rect=_net_rect(rect, walls),
                target_area=pl.spec.target_area,
                is_wet=pl.spec.is_wet,
                has_window=glazing.get(pl.spec.id, 0.0) > 0,
                daylight_area=round(glazing.get(pl.spec.id, 0.0), 3),
            )
        )

    layout = Layout(
        plot=plot,
        rooms=rooms,
        walls=walls,
        openings=openings,
        entry_side=transform.side,
        north_angle=req.north_angle,
        score=plan.score,
    )

    layout.issues = validate(layout)

    net_total = sum(r.net_area for r in rooms if r.kind not in UNROOFED)
    circ = sum(r.net_area for r in rooms if r.spec_id == plan.hub.id)
    layout.metrics = {
        "gross_area": round(plot.area, 2),
        "net_area": round(net_total, 2),
        "efficiency": round(net_total / plot.area, 4) if plot.area else 0.0,
        "circulation_area": round(circ, 2),
        "circulation_share": round(circ / plot.area, 4) if plot.area else 0.0,
        "rooms": float(len(rooms)),
        "plot_width": round(plot.w, 2),
        "plot_depth": round(plot.h, 2),
        "wall_length": round(sum(w.length for w in walls), 2),
        "glazing_area": round(sum(glazing.values()), 2),
        "errors": float(sum(1 for i in layout.issues if i.severity == "error")),
        "warnings": float(sum(1 for i in layout.issues if i.severity == "warning")),
    }
    layout.score = plan.score - issue_penalty(layout.issues)
    return layout


def solve(
    program: ArchitecturalProgram, req: DesignRequest, plot: Rect | None = None
) -> list[Layout]:
    """يرجّع المخططات مرتّبة من الأفضل للأسوأ."""
    from ..planner.rules import normalise_program

    plots = [plot] if plot is not None else candidate_plots(req)
    layouts: list[Layout] = []

    for candidate in plots:
        normalise_program(program, candidate.area)
        for side in candidate_entry_sides(req, candidate):
            tr = Transform(candidate, side)
            exterior = frozenset(tr.canonical_sides(req.exterior_sides))
            facades = tr.facade_map()
            for plan in _canonical_candidates(
                program, tr.wc, tr.dc, req, exterior, facades
            ):
                try:
                    layouts.append(materialise(plan, tr, req, candidate))
                except Exception:  # noqa: BLE001 — مرشّح فاشل ميوقفش الباقي
                    continue

    if not layouts:
        raise RuntimeError(
            "تعذّر إنتاج مخطط صالح بالمساحة/الأبعاد دي — جرّب تكبّر المساحة "
            "أو تقلّل عدد الغرف."
        )

    layouts.sort(key=lambda ly: ly.score, reverse=True)

    # نشيل المخططات المتطابقة تقريبًا عشان البدائل تبقى مختلفة فعلًا
    unique: list[Layout] = []
    seen: set[tuple] = set()
    for ly in layouts:
        key = (
            ly.entry_side,
            round(ly.plot.w, 1),
            tuple(round(r.rect.x, 1) for r in ly.rooms),
            tuple(round(r.rect.y, 1) for r in ly.rooms),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(ly)

    return unique


# ---------------------------------------------------------------------------
# نقل المخطط لإحداثيات أكبر — عشان نركّب وحدة جوه دور
# ---------------------------------------------------------------------------


def translate_layout(layout: Layout, dx: float, dy: float) -> Layout:
    """يرجّع نسخة من المخطط بعد إزاحتها.

    الوحدة بتتخطط في إحداثياتها المحلية (من 0,0)، وبعدين بتتنقل لمكانها في
    الدور — فبيبقى عندنا نظام إحداثيات واحد للمبنى كله، والرسم الموجود
    بيشتغل عليه من غير أي تعديل.
    """
    moved = layout.model_copy(deep=True)

    def shift(r: Rect) -> Rect:
        return Rect(x=round(r.x + dx, 4), y=round(r.y + dy, 4), w=r.w, h=r.h)

    moved.plot = shift(layout.plot)
    for room in moved.rooms:
        room.rect = shift(room.rect)
        room.net_rect = shift(room.net_rect)

    for wall in moved.walls:
        # الحائط الرأسي (v) إحداثيه x وامتداده على y، والعكس للأفقي
        along, across = (dy, dx) if wall.axis == "v" else (dx, dy)
        wall.coord = round(wall.coord + across, 4)
        wall.start = round(wall.start + along, 4)
        wall.end = round(wall.end + along, 4)

    for o in moved.openings:
        along, across = (dy, dx) if o.axis == "v" else (dx, dy)
        o.coord = round(o.coord + across, 4)
        o.start = round(o.start + along, 4)

    return moved
