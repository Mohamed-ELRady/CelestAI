"""مُخطِّط قواعدي — Deterministic program generator.

بيشتغل من غير أي اتصال بالإنترنت، وبيُستخدم كـ fallback لو الـ AI مش متاح،
وكمان كنقطة بداية بيتبني عليها ناتج الـ AI.
"""

from __future__ import annotations

import math

from ..knowledge import HABITABLE, WET_ROOMS, profile, standard
from ..models import (
    ArchitecturalProgram,
    BuildingType,
    DesignRequest,
    RoomKind,
    RoomSpec,
    Zone,
)


def _spec(
    rid: str,
    kind: RoomKind,
    area: float,
    *,
    priority: int = 3,
    attach_to: str | None = None,
    name_ar: str | None = None,
    name_en: str | None = None,
    min_width: float | None = None,
) -> RoomSpec:
    st = standard(kind)
    return RoomSpec(
        id=rid,
        name_ar=name_ar or st.name_ar,
        name_en=name_en or st.name_en,
        kind=kind,
        target_area=round(max(area, st.min_area), 2),
        min_width=min_width if min_width is not None else st.min_width,
        zone=st.zone,
        needs_window=kind in HABITABLE,
        is_wet=kind in WET_ROOMS,
        priority=priority,
        attach_to=attach_to,
    )


# ---------------------------------------------------------------------------
# اشتقاق عدد الغرف من المساحة
# ---------------------------------------------------------------------------


def _infer_bedrooms(area: float) -> int:
    if area < 60:
        return 1
    if area < 90:
        return 2
    if area < 130:
        return 3
    if area < 190:
        return 4
    return 5


def _infer_bathrooms(area: float, bedrooms: int) -> int:
    if area < 70:
        return 1
    if area < 120:
        return 2
    return min(3, max(2, bedrooms - 1))


# ---------------------------------------------------------------------------
# برامج حسب نوع المبنى
# ---------------------------------------------------------------------------


def _residential_program(req: DesignRequest, villa: bool = False) -> list[RoomSpec]:
    area = req.area
    beds = req.bedrooms if req.bedrooms is not None else _infer_bedrooms(area)
    baths = req.bathrooms if req.bathrooms is not None else _infer_bathrooms(area, beds)
    recs = req.receptions if req.receptions is not None else (2 if area >= 140 else 1)

    prof = profile(BuildingType.VILLA_FLOOR if villa else BuildingType.APARTMENT)
    rooms: list[RoomSpec] = []

    # الفراغ المركزي (الصالة) — بيمتص نسبة الحركة
    hub_area = area * prof.circulation_share
    rooms.append(_spec("hub", RoomKind.RECEPTION, hub_area, priority=1))

    # المتبقي بيتوزع على باقي الفراغات
    remaining = area - hub_area

    # أوزان نسبية
    weights: list[tuple[str, RoomKind, float, int]] = []

    if recs >= 1:
        weights.append(("living", RoomKind.LIVING, 1.55, 1))
    if recs >= 2:
        weights.append(("dining", RoomKind.DINING, 1.05, 2))

    weights.append(("kitchen", RoomKind.KITCHEN, 0.95, 1))

    for i in range(beds):
        if i == 0 and area >= 95:
            weights.append(("bed_master", RoomKind.MASTER_BEDROOM, 1.45, 1))
        elif i == 0:
            weights.append(("bed_master", RoomKind.BEDROOM, 1.35, 1))
        elif i == beds - 1 and beds >= 3:
            weights.append((f"bed_{i}", RoomKind.KIDS_BEDROOM, 1.00, 2))
        else:
            weights.append((f"bed_{i}", RoomKind.BEDROOM, 1.15, 2))

    for i in range(baths):
        if i == 0 and beds >= 1:
            weights.append(("bath_master", RoomKind.BATH, 0.42, 2))
        elif i == baths - 1 and baths >= 2 and area >= 100:
            weights.append(("wc_guest", RoomKind.WC, 0.22, 3))
        else:
            weights.append((f"bath_{i}", RoomKind.BATH, 0.38, 2))

    if villa and area >= 150:
        weights.append(("stair", RoomKind.STAIR, 0.55, 1))
    if area >= 110:
        weights.append(("balcony", RoomKind.BALCONY, 0.42, 4))
    if area >= 160:
        weights.append(("laundry", RoomKind.LAUNDRY, 0.28, 4))

    total_w = sum(w for _, _, w, _ in weights)
    for rid, kind, w, prio in weights:
        rooms.append(_spec(rid, kind, remaining * w / total_w, priority=prio))

    # الحمام الرئيسي ملحق بغرفة النوم الرئيسية
    master_bath = next((r for r in rooms if r.id == "bath_master"), None)
    if master_bath and any(r.id == "bed_master" for r in rooms):
        master_bath.attach_to = "bed_master"
        master_bath.name_ar = "حمام الماستر"
        master_bath.name_en = "Master Bath"

    return rooms


def _office_program(req: DesignRequest) -> list[RoomSpec]:
    area = req.area
    prof = profile(BuildingType.OFFICE)
    rooms: list[RoomSpec] = [
        _spec("hub", RoomKind.CORRIDOR, area * prof.circulation_share, priority=1,
              name_ar="ممر التوزيع", name_en="Circulation Spine")
    ]
    remaining = area - area * prof.circulation_share

    weights: list[tuple[str, RoomKind, float, int]] = [
        ("reception", RoomKind.WAITING, 0.85, 1),
        ("open_office", RoomKind.OPEN_OFFICE, 3.20, 1),
        ("meeting", RoomKind.MEETING, 1.25, 2),
        ("pantry", RoomKind.PANTRY, 0.45, 3),
        ("wc_1", RoomKind.WC, 0.24, 2),
    ]
    n_private = max(1, min(4, int(area // 70)))
    for i in range(n_private):
        weights.append((f"office_{i}", RoomKind.OFFICE_ROOM, 0.85, 2))
    if area >= 180:
        weights.append(("wc_2", RoomKind.WC, 0.24, 3))
        weights.append(("storage", RoomKind.STORAGE, 0.30, 4))

    total_w = sum(w for _, _, w, _ in weights)
    for rid, kind, w, prio in weights:
        rooms.append(_spec(rid, kind, remaining * w / total_w, priority=prio))
    return rooms


def _clinic_program(req: DesignRequest) -> list[RoomSpec]:
    area = req.area
    prof = profile(BuildingType.CLINIC)
    rooms = [_spec("hub", RoomKind.WAITING, area * prof.circulation_share, priority=1,
                   name_ar="صالة الانتظار", name_en="Waiting Hall")]
    remaining = area - area * prof.circulation_share

    n_exam = max(1, min(4, int(area // 45)))
    weights: list[tuple[str, RoomKind, float, int]] = [
        ("reception", RoomKind.OFFICE_ROOM, 0.70, 1),
        ("wc_1", RoomKind.WC, 0.28, 2),
        ("storage", RoomKind.STORAGE, 0.30, 4),
    ]
    for i in range(n_exam):
        weights.append((f"exam_{i}", RoomKind.EXAM_ROOM, 1.40, 1))
    if area >= 120:
        weights.append(("pantry", RoomKind.PANTRY, 0.35, 4))

    total_w = sum(w for _, _, w, _ in weights)
    for rid, kind, w, prio in weights:
        rooms.append(_spec(rid, kind, remaining * w / total_w, priority=prio))
    return rooms


def _generic_program(req: DesignRequest) -> list[RoomSpec]:
    area = req.area
    prof = profile(BuildingType.GENERIC)
    n = max(2, min(8, int(round(math.sqrt(area) / 3))))
    rooms = [_spec("hub", RoomKind.CORRIDOR, area * prof.circulation_share, priority=1,
                   name_ar="ممر", name_en="Corridor")]
    remaining = area - area * prof.circulation_share
    for i in range(n):
        rooms.append(
            _spec(f"space_{i}", RoomKind.OFFICE_ROOM, remaining / n, priority=2,
                  name_ar=f"فراغ {i + 1}", name_en=f"Space {i + 1}")
        )
    return rooms


# ---------------------------------------------------------------------------
# نقطة الدخول
# ---------------------------------------------------------------------------

_BUILDERS = {
    BuildingType.APARTMENT: lambda r: _residential_program(r, villa=False),
    BuildingType.VILLA_FLOOR: lambda r: _residential_program(r, villa=True),
    BuildingType.OFFICE: _office_program,
    BuildingType.CLINIC: _clinic_program,
    BuildingType.GENERIC: _generic_program,
}


def build_program(req: DesignRequest) -> ArchitecturalProgram:
    """يبني البرنامج المعماري بالقواعد فقط (بدون AI)."""
    rooms = _BUILDERS.get(req.building_type, _generic_program)(req)
    prof = profile(req.building_type)

    adjacency: list[tuple[str, str]] = []
    for a_kind, b_kind in prof.adjacency:
        a = next((r.id for r in rooms if r.kind == a_kind), None)
        b = next((r.id for r in rooms if r.kind == b_kind), None)
        if a and b and a != b:
            adjacency.append((a, b))

    n_beds = sum(1 for r in rooms if r.zone == Zone.NIGHT)
    n_baths = sum(1 for r in rooms if r.kind in (RoomKind.BATH, RoomKind.WC))

    notes_ar = [
        "التوزيع قائم على فراغ مركزي يوزّع على كل الغرف مباشرة بدون ممرات ضائعة.",
        "الفراغات الرطبة مجمّعة قدر الإمكان لتقصير مواسير السباكة.",
        "كل فراغ معيشة أو نوم له واجهة خارجية للتهوية والإضاءة الطبيعية.",
    ]
    notes_en = [
        "The plan is organised around a central space that serves every room "
        "directly, with no wasted corridors.",
        "Wet rooms are grouped together to keep plumbing runs short.",
        "Every living and sleeping space has an external façade for daylight "
        "and cross-ventilation.",
    ]

    return ArchitecturalProgram(
        building_type=req.building_type,
        summary_ar=(
            f"{prof.label_ar} بمساحة {req.area:.0f} م² — "
            f"{len(rooms)} فراغ، منهم {n_beds} فراغ ليلي و{n_baths} فراغ صحي، "
            f"موزّعين حول {rooms[0].name_ar} مركزية."
        ),
        summary_en=(
            f"{prof.label_en} of {req.area:.0f} m² — {len(rooms)} spaces "
            f"organised around a central {rooms[0].name_en.lower()}."
        ),
        rooms=rooms,
        adjacency=adjacency,
        design_notes=notes_en if req.lang_key == "en" else notes_ar,
        source="rules",
    )


def normalise_program(program: ArchitecturalProgram, total_area: float) -> ArchitecturalProgram:
    """يعيد ضبط المساحات المستهدفة عشان مجموعها يساوي مساحة القطعة بالظبط."""
    rooms = [r for r in program.rooms if r.target_area > 0]
    if not rooms:
        raise ValueError("البرنامج المعماري فاضي")
    total = sum(r.target_area for r in rooms)
    factor = total_area / total
    for r in rooms:
        st = standard(r.kind)
        r.target_area = round(max(r.target_area * factor, st.min_area * 0.75), 3)
    # جولة تانية للتقريب النهائي
    total = sum(r.target_area for r in rooms)
    factor = total_area / total
    for r in rooms:
        r.target_area = round(r.target_area * factor, 3)
    program.rooms = rooms
    return program
