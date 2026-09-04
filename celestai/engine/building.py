"""محرك تقسيم المبنى — من مساحة دور لوحدات مخططة بالكامل.

الفكرة المعمارية:
    كل دور فيه **نواة رأسية** (سلم + مصعد + بسطة) في نفس المكان في كل الأدوار،
    لأنها بتخترق المبنى من تحت لفوق. الباقي بينقسم لوحدات حوالين النواة، وكل
    وحدة بتلمس البسطة من ناحية (فبتاخد بابها منها) وواجهة خارجية أو أكتر
    (فبتاخد شبابيكها منها).

    بعد ما الوحدة تاخد مستطيلها، بتتخطط جواها بنفس محرك الوحدة المستقلة —
    بس مع فرق واحد مهم: بنقوله أنهي أضلاعها مطلّة على الخارج فعلًا، لأن
    الحائط المشترك مع الجار مش بياخد شبابيك.

    ده بيخلي الشقة في النص (واجهة واحدة) تطلع مخالفات إضاءة صريحة في
    المراجعة الكودية بدل ما نرسم شبابيك على حائط مشترك ونعدّيها.
"""

from __future__ import annotations

import math

from ..knowledge import (
    DOOR_ENTRY_WIDTH,
    LANDING_MIN_WIDTH,
    LIFT_DEPTH,
    LIFT_THRESHOLD_FLOORS,
    STAIR_LENGTH,
    STAIR_WIDTH,
    WALL_PARTY,
    floor_label,
    unit_standard,
)
from ..models import (
    BuildingRequest,
    CoreElement,
    DesignRequest,
    FloorPlan,
    FloorSpec,
    FloorUse,
    Issue,
    Layout,
    Opening,
    Rect,
    RoomKind,
    UnitPlan,
)
from .layout import Placement, build_walls
from .plot import candidate_plots

# الاستخدامات اللي وحداتها بتتوزّع حوالين بسطة مشتركة
CORE_SERVED = {FloorUse.APARTMENTS, FloorUse.OFFICES, FloorUse.CLINICS}
# الاستخدامات اللي بتتخطط جواها غرف بالمحرك
PLANNED_INTERNALLY = {FloorUse.APARTMENTS, FloorUse.OFFICES, FloorUse.CLINICS}


# ---------------------------------------------------------------------------
# أدوات مساعدة
# ---------------------------------------------------------------------------


def _opposite(side: str) -> str:
    return {"north": "south", "south": "north", "east": "west", "west": "east"}[side]


def _exterior_sides(rect: Rect, plot: Rect, tol: float = 1e-3) -> list[str]:
    """أنهي أضلاع المستطيل واقعة على محيط المبنى (يعني مطلّة على الخارج)."""
    sides: list[str] = []
    if abs(rect.x - plot.x) < tol:
        sides.append("west")
    if abs(rect.x2 - plot.x2) < tol:
        sides.append("east")
    if abs(rect.y - plot.y) < tol:
        sides.append("south")
    if abs(rect.y2 - plot.y2) < tol:
        sides.append("north")
    return sides


def _net(rect: Rect, inset: float = WALL_PARTY / 2) -> Rect:
    return Rect(
        x=round(rect.x + inset, 4),
        y=round(rect.y + inset, 4),
        w=round(max(rect.w - 2 * inset, 0.05), 4),
        h=round(max(rect.h - 2 * inset, 0.05), 4),
    )


def _auto_units(area: float, use: FloorUse) -> int:
    """عدد الوحدات المنطقي لمساحة الدور دي.

    بنحدّه بأربعة لأن التوزيع حوالين نواة مركزية بيدّي واجهتين لكل وحدة عند
    أربع وحدات؛ فوق كده الوحدات الوسطانية بتبقى بواجهة واحدة بس.
    """
    if use not in CORE_SERVED:
        st = unit_standard(use.value)
        return max(1, min(8, int(area // st.ideal_area) or 1))
    st = unit_standard(use.value)
    usable = area * 0.82          # بعد خصم النواة والبسطة
    n = max(1, min(4, int(round(usable / st.ideal_area))))
    # النواة في نفس المكان في كل الأدوار، فالشريطين متساويين — والعدد الزوجي
    # هو اللي بيدّي وحدات متساوية. العدد الفردي بيخلي وحدة ضعف اللي جنبها.
    if n == 3 and usable / 4 >= st.min_area:
        n = 4
    return n


# ---------------------------------------------------------------------------
# النواة الرأسية
# ---------------------------------------------------------------------------


def core_band(
    plot: Rect, floors: int, entry_side: str, edge: bool = False
) -> tuple[Rect, list[CoreElement]]:
    """يحسب شريط النواة (بسطة + مصعد + سلم) عمودي على واجهة المدخل.

    عرض الشريط = عرض بيت السلم نفسه، وهو كمان عرض كافي للبسطة. السلم والمصعد
    بياخدوا طولهم على امتداد الشريط عند الطرف البعيد عن المدخل، والباقي بسطة
    توزيع بتوصل لأبواب الوحدات.

    الترتيب ده بيخلي النواة تاخد نسبة واقعية من الدور (10–18%) بدل ما تاكل
    ثلثه لو حطينا السلم والمصعد جنب بعض بالعرض.

    `edge=True` بتلزق الشريط في واجهة جانبية بدل نص الدور — ده اللي بيتعمل لما
    يكون فيه وحدة واحدة في الدور، عشان تفضل مستطيل واحد متصل مش نصّين.
    """
    horizontal = entry_side in ("east", "west")   # الشريط ماشي على المحور x
    needs_lift = floors >= LIFT_THRESHOLD_FLOORS

    span = plot.w if horizontal else plot.h       # طول الشريط
    cross = plot.h if horizontal else plot.w      # البُعد اللي بنقتطع منه العرض

    width = min(STAIR_WIDTH, cross * 0.30)
    width = max(width, LANDING_MIN_WIDTH)

    inset = 0.0 if edge else (cross - width) / 2
    if horizontal:
        band = Rect(x=plot.x, y=plot.y + inset, w=plot.w, h=width)
    else:
        band = Rect(x=plot.x + inset, y=plot.y, w=width, h=plot.h)

    # تقسيم طول الشريط: بسطة من ناحية المدخل، بعدين المصعد، وبعده السلم
    stair_run = min(STAIR_LENGTH, span * 0.42)
    lift_run = min(LIFT_DEPTH, span * 0.16) if needs_lift else 0.0
    landing_run = span - stair_run - lift_run
    if landing_run < LANDING_MIN_WIDTH:           # دور صغير: نضحّي بجزء من السلم
        stair_run = max(span - lift_run - LANDING_MIN_WIDTH, span * 0.35)
        landing_run = span - stair_run - lift_run

    # الطرف البعيد عن المدخل هو اللي بياخد السلم
    far_at_end = entry_side in ("south", "west")
    runs = [("landing", landing_run)]
    if needs_lift:
        runs.append(("lift", lift_run))
    runs.append(("stair", stair_run))
    if not far_at_end:
        runs.reverse()

    elements: list[CoreElement] = []
    offset = 0.0
    for kind, run in runs:
        if run <= 0.05:
            continue
        if horizontal:
            rect = Rect(x=round(band.x + offset, 4), y=band.y, w=round(run, 4), h=band.h)
        else:
            rect = Rect(x=band.x, y=round(band.y + offset, 4), w=band.w, h=round(run, 4))
        elements.append(_element(kind, rect))
        offset += run

    return band, elements


_CORE_NAMES = {
    "stair": ("بيت السلم", "Stair"),
    "lift": ("المصعد", "Lift"),
    "landing": ("بسطة التوزيع", "Landing"),
    "shaft": ("منور", "Shaft"),
}


def _element(kind: str, rect: Rect) -> CoreElement:
    ar, en = _CORE_NAMES[kind]
    return CoreElement(
        kind=kind, name_ar=ar, name_en=en, rect=rect, net_rect=_net(rect)
    )


# ---------------------------------------------------------------------------
# تقسيم الدور لوحدات
# ---------------------------------------------------------------------------


def _split_strip(strip: Rect, count: int, along_x: bool) -> list[Rect]:
    """يقسّم شريط لعدد متساوٍ من الوحدات."""
    out: list[Rect] = []
    if count <= 0:
        return out
    if along_x:
        step = strip.w / count
        for i in range(count):
            x = strip.x + i * step
            w = step if i < count - 1 else strip.x2 - x
            out.append(Rect(x=round(x, 4), y=strip.y, w=round(w, 4), h=strip.h))
    else:
        step = strip.h / count
        for i in range(count):
            y = strip.y + i * step
            h = step if i < count - 1 else strip.y2 - y
            out.append(Rect(x=strip.x, y=round(y, 4), w=strip.w, h=round(h, 4)))
    return out


def _unit_rects_around_core(
    plot: Rect, band: Rect, count: int, entry_side: str
) -> list[tuple[Rect, str]]:
    """يرجّع مستطيلات الوحدات + جهة باب كل وحدة (الجهة اللي بتلمس البسطة)."""
    horizontal = entry_side in ("east", "west")
    rects: list[tuple[Rect, str]] = []

    if horizontal:
        below = Rect(x=plot.x, y=plot.y, w=plot.w, h=band.y - plot.y)
        above = Rect(x=plot.x, y=band.y2, w=plot.w, h=plot.y2 - band.y2)
        strips = [(below, "north"), (above, "south")]   # جهة الباب = ناحية البسطة
        along_x = True
    else:
        left = Rect(x=plot.x, y=plot.y, w=band.x - plot.x, h=plot.h)
        right = Rect(x=band.x2, y=plot.y, w=plot.x2 - band.x2, h=plot.h)
        strips = [(left, "east"), (right, "west")]
        along_x = False

    # نوزّع العدد على الشريطين بالتساوي، والزيادة تروح للشريط الأكبر
    strips = [(s, side) for s, side in strips if (s.w > 1.5 and s.h > 1.5)]
    if not strips:
        return rects
    # شريط من غير وحدة = مساحة ميتة، فالعدد ميقلّش عن عدد الشرايط
    count = max(count, len(strips))
    if len(strips) == 1:
        counts = [count]
    else:
        first = math.ceil(count / 2)
        counts = [first, count - first]
        if strips[0][0].area < strips[1][0].area:
            counts.reverse()

    for (strip, door_side), n in zip(strips, counts):
        for r in _split_strip(strip, max(n, 0), along_x):
            rects.append((r, door_side))
    return rects


def _retail_unit_rects(plot: Rect, band: Rect, count: int, entry_side: str
                       ) -> list[tuple[Rect, str]]:
    """المحلات بتفتح على الشارع مباشرة، مش على بسطة داخلية."""
    horizontal = entry_side in ("east", "west")
    if horizontal:
        below = Rect(x=plot.x, y=plot.y, w=plot.w, h=band.y - plot.y)
        above = Rect(x=plot.x, y=band.y2, w=plot.w, h=plot.y2 - band.y2)
        strips = [(below, "south"), (above, "north")]   # الباب على الشارع
        along_x = True
    else:
        left = Rect(x=plot.x, y=plot.y, w=band.x - plot.x, h=plot.h)
        right = Rect(x=band.x2, y=plot.y, w=plot.x2 - band.x2, h=plot.h)
        strips = [(left, "west"), (right, "east")]
        along_x = False

    strips = [(s, side) for s, side in strips if (s.w > 1.5 and s.h > 1.5)]
    if not strips:
        return []
    count = max(count, len(strips))
    first = math.ceil(count / 2)
    counts = [first, count - first] if len(strips) > 1 else [count]

    out: list[tuple[Rect, str]] = []
    for (strip, door_side), n in zip(strips, counts):
        for r in _split_strip(strip, max(n, 0), along_x):
            out.append((r, door_side))
    return out


# ---------------------------------------------------------------------------
# تخطيط دور واحد
# ---------------------------------------------------------------------------


def _unit_request(
    base: BuildingRequest, rect: Rect, use: FloorUse, entry_side: str,
    exterior: list[str],
) -> DesignRequest:
    """يبني طلب تصميم للوحدة، بنفس اللغة والوصف الحر بتوع المبنى."""
    from ..models import BuildingType

    kind = {
        FloorUse.APARTMENTS: BuildingType.APARTMENT,
        FloorUse.OFFICES: BuildingType.OFFICE,
        FloorUse.CLINICS: BuildingType.CLINIC,
    }.get(use, BuildingType.GENERIC)

    return DesignRequest(
        building_type=kind,
        area=round(rect.area, 2),
        width=round(rect.w, 2),
        depth=round(rect.h, 2),
        entry_side=entry_side,
        north_angle=base.north_angle,
        brief=base.brief,
        language=base.language,
        outputs=["svg"],
        use_ai=False,          # البرنامج بيتبني مرة واحدة للمبنى، مش لكل وحدة
        model=base.model,
        exterior_sides=exterior or ["north"],
        # المنور بيخترق كل الأدوار، فبيتحسب على ارتفاع المبنى كله
        shaft_floors=base.floor_count,
    )


def _plan_unit(
    base: BuildingRequest, rect: Rect, use: FloorUse, door_side: str,
    plot: Rect, index: int, level: int,
) -> UnitPlan:
    """يخطط وحدة واحدة جوه الدور."""
    from ..planner.rules import build_program, normalise_program
    from ..service import solve_with_trimming
    from .solver import translate_layout

    st = unit_standard(use.value)
    exterior = _exterior_sides(rect, plot)
    unit_id = f"L{level}U{index + 1}"
    name_ar = f"{st.name_ar} {index + 1}"
    name_en = f"{st.name_en} {index + 1}"

    unit = UnitPlan(
        unit_id=unit_id, name_ar=name_ar, name_en=name_en, use=use,
        rect=rect, net_rect=_net(rect), exterior_sides=exterior,
        entry_side=door_side,
    )

    if use not in PLANNED_INTERNALLY or rect.area < st.min_area * 0.6:
        return unit

    req = _unit_request(base, rect, use, door_side, exterior)
    try:
        program = normalise_program(build_program(req), rect.area)
        # القطعة محددة بالظبط (أبعاد الوحدة)، فمفيش بحث عن نِسَب تانية —
        # لكن حلقة التقليم شغّالة، وهي مهمة هنا أكتر من الوحدة المستقلة لأن
        # الشقة اللي واجهاتها محدودة مش هتستوعب نفس عدد الغرف.
        local_plot = Rect(x=0.0, y=0.0, w=rect.w, h=rect.h)
        best, _program, _alts = solve_with_trimming(program, req, local_plot)
    except RuntimeError:
        return unit

    if best is None:
        return unit

    placed = translate_layout(best, rect.x, rect.y)
    unit.layout = placed
    unit.issues = list(placed.issues)
    return unit


def compose_floor(
    base: BuildingRequest, spec: FloorSpec, plot: Rect, entry_side: str, floors: int,
    edge_core: bool = False,
) -> FloorPlan:
    """يبني دور كامل: نواة + وحدات + مخطط مدمج جاهز للرسم."""
    band, core = core_band(plot, floors, entry_side, edge=edge_core)

    count = spec.units or _auto_units(plot.area, spec.use)
    if spec.use == FloorUse.RETAIL:
        rects = _retail_unit_rects(plot, band, count, entry_side)
    elif spec.use in CORE_SERVED:
        rects = _unit_rects_around_core(plot, band, count, entry_side)
    else:
        rects = []                                   # جراج/خدمات = بلاطة مفتوحة

    units = [
        _plan_unit(base, r, spec.use, side, plot, i, spec.level)
        for i, (r, side) in enumerate(rects)
    ]

    plate = _merge_plate(plot, units, core, entry_side, base.north_angle)
    issues = _floor_issues(units, spec, count)

    shafts = [
        r.rect for u in units if u.layout
        for r in u.layout.rooms if r.kind == RoomKind.SHAFT
    ]

    unit_area = sum(u.area for u in units)
    core_area = sum(c.net_rect.area for c in core)
    return FloorPlan(
        level=spec.level,
        use=spec.use,
        label_ar=spec.label or floor_label(spec.level, "ar"),
        label_en=spec.label or floor_label(spec.level, "en"),
        plot=plot,
        units=units,
        core=core,
        plate=plate,
        shafts=shafts,
        metrics={
            "gross_area": round(plot.area, 2),
            "units": float(len(units)),
            "unit_area": round(unit_area, 2),
            "core_area": round(core_area, 2),
            "shafts": float(len(shafts)),
            "shaft_area": round(sum(r.area for r in shafts), 2),
            "efficiency": round(unit_area / plot.area, 4) if plot.area else 0.0,
            "avg_unit_area": round(unit_area / len(units), 2) if units else 0.0,
            "errors": float(sum(1 for i in issues if i.severity == "error")),
            "warnings": float(sum(1 for i in issues if i.severity == "warning")),
        },
        issues=issues,
    )


def _floor_issues(units: list[UnitPlan], spec: FloorSpec, requested: int) -> list[Issue]:
    """مراجعة على مستوى الدور، فوق مراجعة كل وحدة على حدة."""
    issues: list[Issue] = []
    st = unit_standard(spec.use.value)

    for u in units:
        if u.area < st.min_area:
            issues.append(Issue(
                severity="error", code="UNIT_TOO_SMALL", room_id=u.unit_id,
                message_ar=(f"{u.name_ar}: مساحتها {u.area:.1f} م² أقل من الحد "
                            f"المعقول {st.min_area:.0f} م² لـ{st.label_ar}."),
                message_en=(f"{u.name_en}: {u.area:.1f} m² is below the "
                            f"{st.min_area:.0f} m² practical minimum for {st.label_en.lower()}."),
            ))
        short = min(u.net_rect.w, u.net_rect.h)
        if short < st.min_width:
            issues.append(Issue(
                severity="error", code="UNIT_TOO_NARROW", room_id=u.unit_id,
                message_ar=(f"{u.name_ar}: أقل بُعد {short:.2f} م أضيق من "
                            f"{st.min_width:.2f} م اللازمة للتوزيع الداخلي."),
                message_en=(f"{u.name_en}: {short:.2f} m clear width is below the "
                            f"{st.min_width:.2f} m needed to plan it internally."),
            ))
        if not u.exterior_sides:
            issues.append(Issue(
                severity="error", code="UNIT_NO_FACADE", room_id=u.unit_id,
                message_ar=f"{u.name_ar}: وحدة داخلية بدون أي واجهة خارجية.",
                message_en=f"{u.name_en}: landlocked unit with no external façade.",
            ))
        elif len(u.exterior_sides) == 1 and spec.use in CORE_SERVED:
            issues.append(Issue(
                severity="warning", code="UNIT_SINGLE_ASPECT", room_id=u.unit_id,
                message_ar=(f"{u.name_ar}: واجهة واحدة بس، فالتهوية المتقاطعة "
                            "مش متاحة والإضاءة محدودة."),
                message_en=(f"{u.name_en}: single-aspect unit — no cross-ventilation "
                            "and limited daylight."),
            ))
        # مخالفات التوزيع الداخلي بتتنقل لمستوى الدور
        for issue in u.issues:
            if issue.severity == "error":
                issues.append(Issue(
                    severity="error", code=issue.code, room_id=u.unit_id,
                    message_ar=f"{u.name_ar} — {issue.message_ar}",
                    message_en=f"{u.name_en} — {issue.message_en}",
                ))

    areas = [u.area for u in units]
    if len(areas) >= 2 and min(areas) > 0 and max(areas) / min(areas) > 1.45:
        issues.append(Issue(
            severity="warning", code="UNIT_SIZES_UNEVEN",
            message_ar=(
                f"وحدات الدور متفاوتة (من {min(areas):.0f} لـ{max(areas):.0f} م²) — "
                "النواة لازم تفضل في نفس المكان في كل الأدوار، فالعدد الفردي "
                "بيخلي وحدة تاخد ضعف اللي جنبها. عدد زوجي بيوزّع بالتساوي."
            ),
            message_en=(
                f"Unit sizes vary widely ({min(areas):.0f}–{max(areas):.0f} m²) — "
                "the core must stay in the same place on every floor, so an odd "
                "unit count leaves one unit twice the size of its neighbour. "
                "An even count divides evenly."
            ),
        ))

    if requested and len(units) < requested:
        issues.append(Issue(
            severity="warning", code="UNITS_REDUCED",
            message_ar=(f"اتطلب {requested} وحدة والمساحة استوعبت {len(units)} بس."),
            message_en=(f"{requested} units requested, only {len(units)} fit."),
        ))
    elif requested and len(units) > requested:
        issues.append(Issue(
            severity="warning", code="UNITS_SPLIT",
            message_ar=(f"اتطلب {requested} وحدة والدور اتقسم لـ{len(units)} — النواة "
                        "المركزية بتفصل الدور لشريطين، وشريط من غير وحدة بيبقى "
                        "مساحة ميتة. لو عايز وحدة واحدة، خلّي كل الأدوار وحدة واحدة "
                        "عشان النواة تتزحلق على الواجهة."),
            message_en=(f"{requested} unit(s) requested but the floor split into "
                        f"{len(units)} — the central core divides the plate into two "
                        "strips, and an empty strip would be dead space. For one unit "
                        "per floor, set every floor to one unit so the core can move "
                        "to the façade."),
        ))
    return issues


# ---------------------------------------------------------------------------
# دمج الدور في مخطط واحد قابل للرسم
# ---------------------------------------------------------------------------


def _merge_plate(
    plot: Rect, units: list[UnitPlan], core: list[CoreElement],
    entry_side: str, north_angle: float,
) -> Layout:
    """يجمع كل وحدات الدور + النواة في Layout واحد.

    الحوائط بتتبني من كل المستطيلات مرة واحدة، فالحائط الفاصل بين وحدتين
    بيتحسب صح كحائط مشترك بدل ما يتكرر مرتين.
    """
    from ..models import PlacedRoom
    from ..planner.rules import _spec  # noqa: PLC0415

    rooms: list[PlacedRoom] = []
    openings: list[Opening] = []
    placements: list[Placement] = []

    core_kind = {
        "stair": RoomKind.STAIR, "lift": RoomKind.STORAGE,
        "landing": RoomKind.CORRIDOR, "shaft": RoomKind.STORAGE,
    }

    for i, el in enumerate(core):
        spec = _spec(f"core_{el.kind}_{i}", core_kind[el.kind], max(el.rect.area, 0.5),
                     name_ar=el.name_ar, name_en=el.name_en)
        placements.append(Placement(spec, el.rect.x, el.rect.y, el.rect.w, el.rect.h))

    for u in units:
        if u.layout is not None:
            for r in u.layout.rooms:
                placements.append(Placement(
                    _spec(f"{u.unit_id}_{r.spec_id}", r.kind, max(r.rect.area, 0.5),
                          name_ar=r.name_ar, name_en=r.name_en),
                    r.rect.x, r.rect.y, r.rect.w, r.rect.h,
                ))
            openings.extend(u.layout.openings)
        else:
            placements.append(Placement(
                _spec(u.unit_id, RoomKind.OPEN_OFFICE, max(u.rect.area, 0.5),
                      name_ar=u.name_ar, name_en=u.name_en),
                u.rect.x, u.rect.y, u.rect.w, u.rect.h,
            ))

    walls = build_walls(placements, plot)
    walls = _thicken_party_walls(walls, units, plot)

    for pl in placements:
        rect = Rect(x=pl.x, y=pl.y, w=pl.w, h=pl.h)
        rooms.append(PlacedRoom(
            spec_id=pl.spec.id, name_ar=pl.spec.name_ar, name_en=pl.spec.name_en,
            kind=pl.spec.kind, zone=pl.spec.zone, rect=rect, net_rect=_net(rect, 0.06),
            target_area=pl.spec.target_area,
            has_window=True, daylight_area=0.0,
        ))

    openings.append(_building_entrance(plot, core, entry_side))
    openings.extend(_unit_doors_for_unplanned(units))

    plate = Layout(
        plot=plot, rooms=rooms, walls=walls, openings=openings,
        entry_side=entry_side, north_angle=north_angle,
    )
    net_total = sum(u.area for u in units)
    plate.metrics = {
        "gross_area": round(plot.area, 2),
        "net_area": round(net_total, 2),
        "efficiency": round(net_total / plot.area, 4) if plot.area else 0.0,
        "plot_width": round(plot.w, 2),
        "plot_depth": round(plot.h, 2),
        "rooms": float(len(rooms)),
        "units": float(len(units)),
    }
    return plate


def _thicken_party_walls(walls, units: list[UnitPlan], plot: Rect):
    """الحائط الفاصل بين وحدتين بيبقى أسمك — عزل صوتي وإنشائي."""
    lines_v = {round(u.rect.x, 3) for u in units} | {round(u.rect.x2, 3) for u in units}
    lines_h = {round(u.rect.y, 3) for u in units} | {round(u.rect.y2, 3) for u in units}
    edge = {round(plot.x, 3), round(plot.x2, 3), round(plot.y, 3), round(plot.y2, 3)}

    for w in walls:
        if w.exterior:
            continue
        pool = lines_v if w.axis == "v" else lines_h
        if round(w.coord, 3) in pool and round(w.coord, 3) not in edge:
            w.thickness = max(w.thickness, WALL_PARTY)
    return walls


def _building_entrance(plot: Rect, core: list[CoreElement], entry_side: str) -> Opening:
    """مدخل المبنى الرئيسي، على البسطة من واجهة المدخل."""
    landing = next((c for c in core if c.kind == "landing"), core[-1])
    w = DOOR_ENTRY_WIDTH * 1.3

    if entry_side in ("south", "north"):
        coord = plot.y if entry_side == "south" else plot.y2
        centre = min(max(landing.rect.cx, plot.x + w), plot.x2 - w)
        return Opening(kind="entry", axis="h", coord=round(coord, 4),
                       start=round(centre - w / 2, 4), width=round(w, 4),
                       room_id="core_entrance",
                       swing=1 if entry_side == "south" else -1, hinge=1,
                       height=2.4)
    coord = plot.x if entry_side == "west" else plot.x2
    centre = min(max(landing.rect.cy, plot.y + w), plot.y2 - w)
    return Opening(kind="entry", axis="v", coord=round(coord, 4),
                   start=round(centre - w / 2, 4), width=round(w, 4),
                   room_id="core_entrance",
                   swing=1 if entry_side == "west" else -1, hinge=1, height=2.4)


def _unit_doors_for_unplanned(units: list[UnitPlan]) -> list[Opening]:
    """الوحدات اللي مش بنخطط جواها (محلات/خدمات) محتاجة بابها يترسم يدويًا."""
    out: list[Opening] = []
    for u in units:
        if u.layout is not None:
            continue
        r = u.rect
        w = min(DOOR_ENTRY_WIDTH * 1.6, (r.w if u.entry_side in ("north", "south") else r.h) * 0.5)
        if w < 0.8:
            continue
        if u.entry_side in ("north", "south"):
            coord = r.y2 if u.entry_side == "north" else r.y
            out.append(Opening(
                kind="entry", axis="h", coord=round(coord, 4),
                start=round(r.cx - w / 2, 4), width=round(w, 4), room_id=u.unit_id,
                swing=-1 if u.entry_side == "north" else 1, hinge=1, height=2.4))
        else:
            coord = r.x2 if u.entry_side == "east" else r.x
            out.append(Opening(
                kind="entry", axis="v", coord=round(coord, 4),
                start=round(r.cy - w / 2, 4), width=round(w, 4), room_id=u.unit_id,
                swing=-1 if u.entry_side == "east" else 1, hinge=1, height=2.4))
    return out


# ---------------------------------------------------------------------------
# نقطة الدخول
# ---------------------------------------------------------------------------


def _building_penalty(floors: list[FloorPlan]) -> float:
    """تقييم المبنى ككل — أقل قيمة أحسن.

    اتجاه النواة قرار على مستوى المبنى كله (لأنها بتخترقه رأسيًا)، فبنجرّب
    الاتجاهين وناخد اللي بيدّي وحدات أقرب للمربع وأقل مخالفات.
    """
    pen = 0.0
    for f in floors:
        pen += f.metrics.get("errors", 0) * 3.0
        pen += f.metrics.get("warnings", 0) * 0.5
        pen += (1.0 - f.metrics.get("efficiency", 0.0)) * 12.0
        for u in f.units:
            n = u.net_rect
            short, long = min(n.w, n.h), max(n.w, n.h)
            aspect = long / max(short, 0.05)
            if aspect > 1.7:                    # وحدة مستطيلة = توزيع داخلي أصعب
                pen += (aspect - 1.7) * 4.0
    return pen


def compose_building(req: BuildingRequest) -> list[FloorPlan]:
    """يبني كل أدوار المبنى على نفس البصمة ونفس النواة."""
    from ..models import BuildingType

    probe = DesignRequest(
        building_type=BuildingType.APARTMENT, area=req.area,
        width=req.width, depth=req.depth, entry_side=req.entry_side,
    )
    plot = candidate_plots(probe)[0]
    specs = sorted(req.floors, key=lambda f: f.level)

    sides = (
        [req.entry_side] if req.entry_side != "auto"
        else ["south", "west", "north", "east"]
    )

    # النواة في نفس المكان في كل الأدوار، فقرار «نص الدور ولا على الواجهة»
    # بيتاخد للمبنى كله: على الواجهة بس لو كل دور فيه وحدة واحدة.
    unit_counts = [
        (s.units or _auto_units(plot.area, s.use))
        for s in specs if s.use in CORE_SERVED or s.use == FloorUse.RETAIL
    ]
    edge_core = bool(unit_counts) and max(unit_counts) <= 1

    best: list[FloorPlan] | None = None
    best_pen = float("inf")
    for side in sides:
        try:
            floors = [
                compose_floor(req, s, plot, side, len(specs), edge_core) for s in specs
            ]
        except Exception:  # noqa: BLE001 — اتجاه فاشل ميوقفش الباقي
            continue
        pen = _building_penalty(floors)
        if pen < best_pen:
            best, best_pen = floors, pen

    if best is None:
        raise RuntimeError(
            "تعذّر تقسيم المبنى بالمساحة دي — جرّب مساحة دور أكبر أو وحدات أقل."
        )
    _check_shaft_continuity(best)
    return best


def _shaft_key(r: Rect) -> tuple[float, float, float, float]:
    return (round(r.x, 2), round(r.y, 2), round(r.w, 2), round(r.h, 2))


def _check_shaft_continuity(floors: list[FloorPlan]) -> None:
    """المنور لازم يفضل مفتوح من دوره لحد السطح.

    أي دور فوقه بيبني مكان منور دور تحته بيقفله، فالفراغات اللي تحت تفقد
    تهويتها. مبنغيّرش الهندسة — بنقول المشكلة صراحةً في المراجعة.
    """
    open_below: dict[tuple[float, float, float, float], int] = {}
    for f in floors:                                   # مرتّبين من تحت لفوق
        here = {_shaft_key(r) for r in f.shafts}
        blocked = sorted(k for k in open_below if k not in here)
        if blocked:
            src = ", ".join(str(v) for v in sorted({open_below[k] for k in blocked}))
            n = len(blocked)
            word = "منور" if n == 1 else "مناور"
            f.issues.append(Issue(
                severity="warning", code="SHAFT_BLOCKED",
                message_ar=(
                    f"{n} {word} جايين من منسوب {src} مش متكمّلين في "
                    f"{f.label_ar} — المنور لازم يفضل مفتوح لحد السطح، "
                    "فلازم يتحجز مكانه في الدور ده."
                ),
                message_en=(
                    f"{len(blocked)} light well(s) from a lower floor (level {src}) "
                    f"are not carried through {f.label_en} — a shaft must stay open "
                    "to the sky, so its footprint has to be reserved on this floor."
                ),
            ))
        for k in here:
            open_below.setdefault(k, f.level)
