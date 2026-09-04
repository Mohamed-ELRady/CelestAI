"""اختبارات المبنى متعدد الأدوار — the invariants a stack of floors must satisfy."""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from celestai.engine.building import compose_building
from celestai.knowledge import (
    LIFT_THRESHOLD_FLOORS,
    SHAFT_MIN_AREA,
    SHAFT_MIN_WIDTH,
    WALL_PARTY,
)
from celestai.models import BuildingRequest, FloorSpec, FloorUse, RoomKind

ARABIC = re.compile(r"[؀-ۿ]")


def _req(area=400, floors=None, **kw):
    return BuildingRequest(
        area=area,
        floors=floors or [FloorSpec(level=1, use=FloorUse.APARTMENTS, units=4)],
        use_ai=False,
        **kw,
    )


@lru_cache(maxsize=None)
def _mixed(area: float = 420.0, levels: int = 4):
    """مبنى مختلط الاستخدام — الحل غالي فبنخزّنه."""
    specs = [FloorSpec(level=0, use=FloorUse.RETAIL, units=4)]
    specs += [
        FloorSpec(level=i, use=FloorUse.APARTMENTS, units=4)
        for i in range(1, levels)
    ]
    return compose_building(_req(area, specs))


# ---------------------------------------------------------------------------
# النواة الرأسية — لازم تكون في نفس المكان في كل الأدوار
# ---------------------------------------------------------------------------


def test_core_is_identical_on_every_floor():
    """النواة بتخترق المبنى رأسيًا، فمينفعش تتحرك من دور للتاني."""
    floors = _mixed()
    ref = [
        (c.kind, round(c.rect.x, 3), round(c.rect.y, 3),
         round(c.rect.w, 3), round(c.rect.h, 3))
        for c in floors[0].core
    ]
    for f in floors[1:]:
        got = [
            (c.kind, round(c.rect.x, 3), round(c.rect.y, 3),
             round(c.rect.w, 3), round(c.rect.h, 3))
            for c in f.core
        ]
        assert got == ref, f"النواة اتحركت في {f.label_ar}"


def test_every_floor_has_a_stair():
    for f in _mixed():
        assert any(c.kind == "stair" for c in f.core), f.label_ar


def test_lift_appears_only_in_tall_buildings():
    short = compose_building(_req(floors=[
        FloorSpec(level=i, use=FloorUse.APARTMENTS, units=2) for i in range(2)
    ]))
    tall = compose_building(_req(floors=[
        FloorSpec(level=i, use=FloorUse.APARTMENTS, units=2)
        for i in range(LIFT_THRESHOLD_FLOORS + 2)
    ]))
    assert not any(c.kind == "lift" for c in short[0].core)
    assert any(c.kind == "lift" for c in tall[0].core)


def test_all_floors_share_one_footprint():
    floors = _mixed()
    first = floors[0].plot
    for f in floors[1:]:
        assert (round(f.plot.w, 3), round(f.plot.h, 3)) == (
            round(first.w, 3), round(first.h, 3)
        )


# ---------------------------------------------------------------------------
# تقسيم الدور
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("units", [1, 2, 4])
def test_units_and_core_tile_the_floor_without_overlap(units):
    """الوحدات + النواة لازم يغطوا الدور بالظبط من غير تداخل."""
    floors = compose_building(_req(
        floors=[FloorSpec(level=1, use=FloorUse.APARTMENTS, units=units)]
    ))
    f = floors[0]
    covered = sum(u.rect.area for u in f.units) + sum(c.rect.area for c in f.core)
    assert covered == pytest.approx(f.plot.area, rel=1e-3)

    boxes = [u.rect for u in f.units] + [c.rect for c in f.core]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            ox = min(a.x2, b.x2) - max(a.x, b.x)
            oy = min(a.y2, b.y2) - max(a.y, b.y)
            assert ox <= 1e-6 or oy <= 1e-6, "تداخل بين عنصرين في الدور"


def test_units_stay_inside_the_footprint():
    for f in _mixed():
        p = f.plot
        for u in f.units:
            assert u.rect.x >= p.x - 1e-6 and u.rect.x2 <= p.x2 + 1e-6
            assert u.rect.y >= p.y - 1e-6 and u.rect.y2 <= p.y2 + 1e-6


def test_every_unit_has_at_least_one_external_facade():
    """وحدة محبوسة بالكامل جوه المبنى مش قابلة للسكن."""
    for f in _mixed():
        for u in f.units:
            assert u.exterior_sides, f"{u.name_ar} من غير أي واجهة"


def test_unit_entry_side_is_never_an_external_facade():
    """باب الوحدة بيفتح على البسطة الداخلية، مش على الواجهة الخارجية."""
    for f in _mixed():
        if f.use == FloorUse.RETAIL:
            continue        # المحلات بتفتح على الشارع مباشرة
        for u in f.units:
            assert u.entry_side not in u.exterior_sides, (
                f"{u.name_ar}: بابه على واجهة خارجية بدل البسطة"
            )


def test_retail_units_open_onto_the_street():
    floors = compose_building(_req(
        floors=[FloorSpec(level=0, use=FloorUse.RETAIL, units=4)]
    ))
    for u in floors[0].units:
        assert u.entry_side in u.exterior_sides, f"{u.name_ar}: محل من غير واجهة شارع"


def test_floor_efficiency_is_realistic():
    """النواة لازم تاخد نسبة معقولة — مش ثلث الدور ولا صفر."""
    for f in _mixed():
        eff = f.metrics["efficiency"]
        assert 0.68 <= eff <= 0.95, f"{f.label_ar}: كفاءة غير واقعية {eff:.2f}"


# ---------------------------------------------------------------------------
# التوزيع الداخلي للوحدات
# ---------------------------------------------------------------------------


def test_planned_units_keep_rooms_inside_their_own_boundary():
    """غرف الشقة مينفعش تخرج بره حدود الشقة — ده بيثبت إن النقل شغّال صح."""
    for f in _mixed():
        for u in f.units:
            if u.layout is None:
                continue
            for room in u.layout.rooms:
                assert room.rect.x >= u.rect.x - 1e-3
                assert room.rect.x2 <= u.rect.x2 + 1e-3
                assert room.rect.y >= u.rect.y - 1e-3
                assert room.rect.y2 <= u.rect.y2 + 1e-3


def _touches_shaft(o, layout) -> bool:
    """الشباك واقع على حائط منور؟ (شباك المنور شرعي جوه الوحدة)"""
    for r in layout.rooms:
        if r.kind != RoomKind.SHAFT:
            continue
        if o.axis == "v" and (abs(o.coord - r.rect.x) < 1e-3
                              or abs(o.coord - r.rect.x2) < 1e-3):
            if min(o.end, r.rect.y2) - max(o.start, r.rect.y) > -1e-3:
                return True
        if o.axis == "h" and (abs(o.coord - r.rect.y) < 1e-3
                              or abs(o.coord - r.rect.y2) < 1e-3):
            if min(o.end, r.rect.x2) - max(o.start, r.rect.x) > -1e-3:
                return True
    return False


def test_no_windows_on_party_walls():
    """أهم اختبار في الميزة: الحائط المشترك مع الجار مبياخدش شبابيك.

    الشباك المسموح: على محيط المبنى (واجهة خارجية) أو على منور جوه الوحدة.
    أي شباك غير كده معناه إننا بنطلّ على شقة الجار.
    """
    for f in _mixed():
        p = f.plot
        for u in f.units:
            if u.layout is None:
                continue
            for o in u.layout.openings:
                if o.kind != "window":
                    continue
                on_perimeter = (
                    (o.axis == "v" and (abs(o.coord - p.x) < 1e-3
                                        or abs(o.coord - p.x2) < 1e-3))
                    or (o.axis == "h" and (abs(o.coord - p.y) < 1e-3
                                           or abs(o.coord - p.y2) < 1e-3))
                )
                assert on_perimeter or _touches_shaft(o, u.layout), (
                    f"{u.name_ar}: شباك على حائط مشترك عند "
                    f"{o.axis}={o.coord:.2f} (المحيط {p.x:.2f}–{p.x2:.2f} / "
                    f"{p.y:.2f}–{p.y2:.2f})"
                )


def test_light_wells_solve_the_blind_kitchen_problem():
    """وحدة الركن ليها واجهتين بس، فالمطبخ والحمّامات بتتخدم بمنور.

    الاختبار ده هو سبب وجود الميزة: قبلها كانت المطابخ الداخلية بتطلع
    «فراغ داخلي بدون تهوية طبيعية».
    """
    floors = _mixed()
    blind = [
        u for f in floors for u in f.units
        if u.layout is not None and len(u.exterior_sides) <= 2
    ]
    assert blind, "المفروض في وحدات ركن بواجهتين"

    for u in blind:
        for r in u.layout.rooms:
            if r.kind in (RoomKind.KITCHEN, RoomKind.BATH, RoomKind.WC):
                assert r.has_window, (
                    f"{u.name_ar} — {r.name_ar}: فراغ خدمي من غير تهوية طبيعية"
                )


def test_light_wells_are_open_shafts_not_rooms():
    """المنور مكشوف للسما ومالوش باب، ومش بيتحسب ضمن المساحة الصافية."""
    for f in _mixed():
        for u in f.units:
            if u.layout is None:
                continue
            shafts = [r for r in u.layout.rooms if r.kind == RoomKind.SHAFT]
            doors = {o.room_id for o in u.layout.openings if o.kind in ("door", "entry")}
            for s in shafts:
                assert s.spec_id not in doors, f"{s.name_ar}: مالهوش يبقى ليه باب"
                assert s.net_rect.area >= SHAFT_MIN_AREA - 0.05, (
                    f"{s.name_ar}: {s.net_rect.area:.2f} م² أقل من الحد الأدنى"
                )
                assert min(s.net_rect.w, s.net_rect.h) >= SHAFT_MIN_WIDTH - 0.02


def test_light_wells_line_up_vertically():
    """المنور بيخترق المبنى رأسيًا، فلازم يبقى في نفس المكان في كل دور سكني."""
    floors = [f for f in _mixed() if f.use == FloorUse.APARTMENTS]
    assert len(floors) >= 2

    def key(fp):
        return sorted(
            (round(r.rect.x, 2), round(r.rect.y, 2),
             round(r.rect.w, 2), round(r.rect.h, 2))
            for u in fp.units if u.layout
            for r in u.layout.rooms if r.kind == RoomKind.SHAFT
        )

    ref = key(floors[0])
    assert ref, "المفروض في مناور في الأدوار السكنية"
    for f in floors[1:]:
        assert key(f) == ref, f"المناور اتحركت في {f.label_ar}"


def test_bedrooms_are_never_lit_by_a_light_well():
    """الكود بيطلب واجهة خارجية حقيقية لغرف النوم والمعيشة — المنور مش بديل."""
    habitable = {RoomKind.BEDROOM, RoomKind.MASTER_BEDROOM,
                 RoomKind.KIDS_BEDROOM, RoomKind.LIVING}
    for f in _mixed():
        p = f.plot
        for u in f.units:
            if u.layout is None:
                continue
            ids = {r.spec_id for r in u.layout.rooms if r.kind in habitable}
            for o in u.layout.openings:
                if o.kind != "window" or o.room_id not in ids:
                    continue
                on_perimeter = (
                    (o.axis == "v" and (abs(o.coord - p.x) < 1e-3
                                        or abs(o.coord - p.x2) < 1e-3))
                    or (o.axis == "h" and (abs(o.coord - p.y) < 1e-3
                                           or abs(o.coord - p.y2) < 1e-3))
                )
                assert on_perimeter, (
                    f"{u.name_ar}: فراغ معيشة/نوم بياخد ضوءه من منور بدل واجهة"
                )


def test_planned_units_always_keep_a_bathroom_and_kitchen():
    """التقليم مينفعش يشيل آخر حمام أو مطبخ — شقة من غيرهم مش شقة."""
    floors = compose_building(_req(area=300, floors=[
        FloorSpec(level=1, use=FloorUse.APARTMENTS, units=4)
    ]))
    for u in floors[0].units:
        if u.layout is None:
            continue
        kinds = {r.kind.value for r in u.layout.rooms}
        assert kinds & {"bath", "wc"}, f"{u.name_ar} من غير حمام"
        assert "kitchen" in kinds, f"{u.name_ar} من غير مطبخ"


def test_party_walls_are_thicker_than_internal_partitions():
    floors = compose_building(_req(
        floors=[FloorSpec(level=1, use=FloorUse.APARTMENTS, units=4)]
    ))
    f = floors[0]
    boundaries = {round(u.rect.x, 3) for u in f.units} | {
        round(u.rect.x2, 3) for u in f.units
    }
    edge = {round(f.plot.x, 3), round(f.plot.x2, 3)}
    interior_boundaries = boundaries - edge
    party = [
        w for w in f.plate.walls
        if w.axis == "v" and not w.exterior and round(w.coord, 3) in interior_boundaries
    ]
    assert party, "مفيش حوائط فاصلة اتلقت"
    assert all(w.thickness >= WALL_PARTY - 1e-6 for w in party)


# ---------------------------------------------------------------------------
# تسمية الأدوار والاستخدامات
# ---------------------------------------------------------------------------


def test_floor_uses_are_respected():
    specs = [
        FloorSpec(level=0, use=FloorUse.RETAIL, units=4),
        FloorSpec(level=1, use=FloorUse.OFFICES, units=2),
        FloorSpec(level=2, use=FloorUse.APARTMENTS, units=2),
    ]
    floors = compose_building(_req(floors=specs))
    assert [f.use for f in floors] == [
        FloorUse.RETAIL, FloorUse.OFFICES, FloorUse.APARTMENTS
    ]


def test_floors_are_sorted_by_level():
    specs = [
        FloorSpec(level=2, use=FloorUse.APARTMENTS, units=2),
        FloorSpec(level=0, use=FloorUse.RETAIL, units=2),
        FloorSpec(level=1, use=FloorUse.OFFICES, units=2),
    ]
    floors = compose_building(_req(floors=specs))
    assert [f.level for f in floors] == [0, 1, 2]


def test_floor_labels_switch_language():
    floors = _mixed()
    assert ARABIC.search(floors[0].label_ar)
    assert not ARABIC.search(floors[0].label_en)
    assert "Ground" in floors[0].label_en


# ---------------------------------------------------------------------------
# المسار الكامل
# ---------------------------------------------------------------------------


def test_full_building_pipeline_writes_every_format(tmp_path):
    from celestai.service import generate_building

    req = _req(area=400, floors=[
        FloorSpec(level=0, use=FloorUse.RETAIL, units=4),
        FloorSpec(level=1, use=FloorUse.APARTMENTS, units=4),
    ])
    req.outputs = ["svg", "pdf", "dxf", "json3d", "report"]
    result = generate_building(req, out_dir=tmp_path)

    assert "pdf" in result.files and "report" in result.files
    assert "svg_L0" in result.files and "svg_L1" in result.files
    for path in result.files.values():
        assert Path(path).stat().st_size > 400, path

    assert result.metrics["floors"] == 2
    assert result.metrics["units"] == 8
    assert result.model3d["kind"] == "building"
    assert len(result.model3d["levels"]) == 2


def test_building_report_follows_the_language():
    from celestai.report import build_building_report

    floors = _mixed()
    ar = build_building_report(_req(), floors)
    en_req = _req()
    en_req.language = "en"
    en = build_building_report(en_req, floors)

    assert ARABIC.search(ar)
    leftovers = [l for l in en.splitlines() if ARABIC.search(l)]
    assert not leftovers, f"نصوص عربية في التقرير الإنجليزي: {leftovers[:3]}"


def test_floor_plate_svg_is_wellformed():
    import xml.etree.ElementTree as ET

    from celestai.drafting import render_svg
    from celestai.drafting.floorplate import compose_floor_plate

    svg = render_svg(compose_floor_plate(_mixed()[1], title="اختبار"))
    ET.fromstring(svg)


def test_impossible_building_fails_loudly():
    """مساحة دور صغيرة مع وحدات كتير: لازم خطأ واضح أو مخطط سليم هندسيًا."""
    from celestai.service import generate_building

    req = _req(area=60, floors=[
        FloorSpec(level=1, use=FloorUse.APARTMENTS, units=8)
    ])
    try:
        result = generate_building(req)
    except RuntimeError as exc:
        assert "مساحة" in str(exc) or "المبنى" in str(exc)
        return
    f = result.floors[0]
    covered = sum(u.rect.area for u in f.units) + sum(c.rect.area for c in f.core)
    assert covered == pytest.approx(f.plot.area, rel=1e-3)
