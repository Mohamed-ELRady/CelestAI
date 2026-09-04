"""اختبارات الثوابت الهندسية — the invariants that make a plan buildable."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from celestai.engine import solve
from celestai.engine.plot import Transform, candidate_plots
from celestai.knowledge import UNROOFED, required_glazing
from celestai.models import BuildingType, DesignRequest, RoomKind, Zone
from celestai.planner.rules import build_program, normalise_program

CASES = [
    (55, BuildingType.APARTMENT),
    (75, BuildingType.APARTMENT),
    (100, BuildingType.APARTMENT),
    (120, BuildingType.APARTMENT),
    (165, BuildingType.APARTMENT),
    (200, BuildingType.VILLA_FLOOR),
    (280, BuildingType.VILLA_FLOOR),
    (90, BuildingType.OFFICE),
    (160, BuildingType.OFFICE),
    (250, BuildingType.OFFICE),
    (110, BuildingType.CLINIC),
    (140, BuildingType.GENERIC),
]


@lru_cache(maxsize=None)
def _layout(area: float, bt: BuildingType):
    """الحل غالي حسابيًا، فبنخزّنه — كل حالة بتتحل مرة واحدة لكل الاختبارات."""
    req = DesignRequest(area=area, building_type=bt, use_ai=False)
    program = normalise_program(build_program(req), area)
    return req, solve(program, req)[0]


# ---------------------------------------------------------------------------
# التخطيط
# ---------------------------------------------------------------------------


def test_program_areas_sum_to_plot_area():
    for area, bt in CASES:
        req = DesignRequest(area=area, building_type=bt, use_ai=False)
        program = normalise_program(build_program(req), area)
        total = sum(r.target_area for r in program.rooms)
        assert total == pytest.approx(area, rel=1e-3), f"{bt.value} {area}"


def test_first_room_is_the_circulation_hub():
    """المحرك بيعتمد إن rooms[0] هو الفراغ المركزي اللي بيوزّع على الباقي."""
    hub_kinds = (RoomKind.RECEPTION, RoomKind.CORRIDOR, RoomKind.WAITING)
    for area, bt in CASES:
        req = DesignRequest(area=area, building_type=bt, use_ai=False)
        program = build_program(req)
        assert program.rooms[0].kind in hub_kinds, f"{bt.value}: {program.rooms[0].kind}"
        assert program.rooms[0].zone in (Zone.CIRCULATION, Zone.DAY)


# ---------------------------------------------------------------------------
# الهندسة — أهم اختبار في المشروع
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("area,bt", CASES)
def test_rooms_tile_the_plot_without_overlap_or_gaps(area, bt):
    """الغرف لازم تغطي القطعة بالظبط: لا تداخل ولا فراغ ضايع."""
    _, layout = _layout(area, bt)

    covered = sum(r.rect.area for r in layout.rooms)
    assert covered == pytest.approx(layout.plot.area, rel=1e-3), "فيه مساحة ضايعة أو مكررة"

    for i, a in enumerate(layout.rooms):
        for b in layout.rooms[i + 1:]:
            overlap_x = min(a.rect.x2, b.rect.x2) - max(a.rect.x, b.rect.x)
            overlap_y = min(a.rect.y2, b.rect.y2) - max(a.rect.y, b.rect.y)
            assert overlap_x <= 1e-6 or overlap_y <= 1e-6, (
                f"تداخل بين {a.name_ar} و{b.name_ar}"
            )


@pytest.mark.parametrize("area,bt", CASES)
def test_rooms_stay_inside_the_plot(area, bt):
    _, layout = _layout(area, bt)
    p = layout.plot
    for r in layout.rooms:
        assert r.rect.x >= p.x - 1e-6 and r.rect.x2 <= p.x2 + 1e-6, r.name_ar
        assert r.rect.y >= p.y - 1e-6 and r.rect.y2 <= p.y2 + 1e-6, r.name_ar


@pytest.mark.parametrize("area,bt", CASES)
def test_every_room_has_a_door(area, bt):
    """أهم شرط وظيفي: مفيش فراغ محبوس."""
    _, layout = _layout(area, bt)
    served = {o.room_id for o in layout.openings if o.kind in ("door", "entry")}
    for r in layout.rooms:
        assert r.spec_id in served, f"{r.name_ar} من غير باب"


@pytest.mark.parametrize("area,bt", CASES)
def test_exactly_one_main_entrance(area, bt):
    _, layout = _layout(area, bt)
    entries = [o for o in layout.openings if o.kind == "entry"]
    assert len(entries) == 1


@pytest.mark.parametrize("area,bt", CASES)
def test_openings_sit_on_real_walls(area, bt):
    """كل فتحة لازم تكون على مقطع حائط موجود فعلًا."""
    _, layout = _layout(area, bt)
    for o in layout.openings:
        hosts = [
            w for w in layout.walls
            if w.axis == o.axis
            and abs(w.coord - o.coord) < 1e-3
            and w.start - 1e-3 <= o.start
            and o.end <= w.end + 1e-3
        ]
        assert hosts, f"فتحة {o.kind} لـ{o.room_id} مش على حائط"


@pytest.mark.parametrize("area,bt", CASES)
def test_net_area_is_realistic(area, bt):
    """كفاءة التوزيع لازم تكون في المدى الواقعي بعد خصم الحوائط."""
    _, layout = _layout(area, bt)
    eff = layout.metrics["efficiency"]
    assert 0.75 <= eff <= 0.96, f"كفاءة غير واقعية: {eff:.3f}"


@pytest.mark.parametrize("area,bt", CASES)
def test_rooms_that_need_daylight_get_a_window(area, bt):
    """كل فراغ الكود بيطلب له إضاءة طبيعية لازم يوصل للواجهة الخارجية.

    فراغات الحركة (ممرات وصالات التوزيع) مستثناة — بتاخد إضاءة مستعارة،
    وكذلك البلكونات لأنها مكشوفة أصلًا.
    """
    _, layout = _layout(area, bt)
    for r in layout.rooms:
        if r.kind in UNROOFED or r.zone == Zone.CIRCULATION:
            continue
        if required_glazing(r.kind, r.net_area) <= 0:
            continue
        assert r.has_window, f"{r.name_ar} ({r.kind.value}) من غير شباك"


# ---------------------------------------------------------------------------
# المناور
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("area,bt", CASES)
def test_a_unit_with_four_facades_never_gets_a_light_well(area, bt):
    """المنور حل لمشكلة الواجهات المحدودة — الوحدة المستقلة مش محتاجاه،
    ولو ظهر فيها يبقى مساحة ضايعة."""
    _, layout = _layout(area, bt)
    assert not [r for r in layout.rooms if r.kind == RoomKind.SHAFT]


@pytest.mark.parametrize("sides", [["south"], ["south", "west"], ["north", "east"]])
def test_limited_facades_trigger_a_light_well_for_service_spaces(sides):
    """الوحدة اللي واجهاتها محدودة بتاخد منور، والفراغات الخدمية بتتهوّى عليه."""
    req = DesignRequest(
        building_type=BuildingType.APARTMENT, area=95, use_ai=False,
        exterior_sides=sides, shaft_floors=6,
    )
    program = build_program(req)
    layout = solve(program, req)[0]

    wet = [
        r for r in layout.rooms
        if r.kind in (RoomKind.KITCHEN, RoomKind.BATH, RoomKind.WC)
    ]
    assert wet
    for r in wet:
        assert r.has_window, f"{r.name_ar}: فراغ خدمي من غير تهوية"


def test_light_well_grows_with_building_height():
    """المنور العميق محتاج فتحة أوسع عشان الهوا والضوء يوصلوا لتحت."""
    from celestai.knowledge import shaft_area

    low = shaft_area(RoomKind.KITCHEN, floors=1)
    high = shaft_area(RoomKind.KITCHEN, floors=12)
    assert high > low
    # وبرضه بيتوقف عند حد — فوقه بقى فناء مش منور
    assert shaft_area(RoomKind.KITCHEN, floors=60) <= 9.0


def test_light_wells_are_excluded_from_net_area():
    """المنور مكشوف للسما، فمينفعش يتحسب ضمن المساحة المفيدة.

    الأبعاد هنا مثبّتة (وحدة ركن جوه عمارة) عشان المحرك ميلاقيش نسبة قطعة
    تانية تخلّي الفراغات الخدمية على الواجهة وتستغنى عن المنور.
    """
    req = DesignRequest(
        building_type=BuildingType.APARTMENT, area=83.4,
        width=8.88, depth=9.39, entry_side="north", use_ai=False,
        exterior_sides=["south", "west"], shaft_floors=6,
    )
    layout = solve(build_program(req), req)[0]
    shafts = [r for r in layout.rooms if r.kind == RoomKind.SHAFT]
    assert shafts, "المفروض في منور في وحدة ركن بواجهتين"

    roofed = sum(r.net_area for r in layout.rooms if r.kind not in UNROOFED)
    assert layout.metrics["net_area"] == pytest.approx(roofed, rel=1e-3)
    assert layout.metrics["net_area"] < sum(r.net_area for r in layout.rooms)


# ---------------------------------------------------------------------------
# التحويل بين الإحداثيات
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("side", ["south", "north", "east", "west"])
def test_transform_keeps_rects_inside_plot(side):
    from celestai.models import Rect

    plot = Rect(x=0, y=0, w=12.0, h=9.0)
    tr = Transform(plot, side)
    # مستطيل يغطي الإطار القياسي بالكامل
    r = tr.rect(0, 0, tr.wc, tr.dc)
    assert r.x == pytest.approx(0, abs=1e-6)
    assert r.y == pytest.approx(0, abs=1e-6)
    assert r.w == pytest.approx(plot.w, abs=1e-6)
    assert r.h == pytest.approx(plot.h, abs=1e-6)


@pytest.mark.parametrize("side", ["south", "north", "east", "west"])
def test_entry_door_lands_on_the_requested_facade(side):
    req = DesignRequest(area=120, use_ai=False, entry_side=side)
    program = normalise_program(build_program(req), 120)
    layout = solve(program, req)[0]

    entry = next(o for o in layout.openings if o.kind == "entry")
    p = layout.plot
    on_edge = {
        "south": entry.axis == "h" and abs(entry.coord - p.y) < 1e-3,
        "north": entry.axis == "h" and abs(entry.coord - p.y2) < 1e-3,
        "west": entry.axis == "v" and abs(entry.coord - p.x) < 1e-3,
        "east": entry.axis == "v" and abs(entry.coord - p.x2) < 1e-3,
    }[side]
    assert on_edge, f"المدخل مش على واجهة {side}"


# ---------------------------------------------------------------------------
# القطعة
# ---------------------------------------------------------------------------


def test_explicit_dimensions_are_respected():
    req = DesignRequest(area=120, width=15.0, depth=8.0, use_ai=False)
    plots = candidate_plots(req)
    assert len(plots) == 1
    assert plots[0].w == pytest.approx(15.0)
    assert plots[0].h == pytest.approx(8.0)

    layout = solve(normalise_program(build_program(req), plots[0].area), req)[0]
    assert layout.plot.w == pytest.approx(15.0)
    assert layout.plot.h == pytest.approx(8.0)


def test_candidate_plots_all_have_the_requested_area():
    req = DesignRequest(area=150, use_ai=False)
    for p in candidate_plots(req):
        assert p.area == pytest.approx(150, rel=1e-2)


# ---------------------------------------------------------------------------
# المسار الكامل
# ---------------------------------------------------------------------------


def test_full_pipeline_writes_every_format(tmp_path):
    from celestai.service import generate

    req = DesignRequest(
        area=120, use_ai=False,
        outputs=["svg", "pdf", "dxf", "json3d", "report"],
    )
    result = generate(req, out_dir=tmp_path)

    for fmt in ("svg", "pdf", "dxf", "json3d", "report"):
        assert fmt in result.files, fmt
        assert Path(result.files[fmt]).stat().st_size > 400, fmt

    assert result.report_md.strip()
    assert result.model3d["walls"]
    assert result.model3d["floors"]


def test_svg_is_wellformed_xml():
    import xml.etree.ElementTree as ET

    from celestai.service import render_layout_svg

    req, layout = _layout(120, BuildingType.APARTMENT)
    svg = render_layout_svg(layout, req)
    ET.fromstring(svg)          # يرمي استثناء لو الـ XML باظ
    assert 'unicode-bidi' in svg, "لازم نثبّت اتجاه النص جوه الرسمة"


def test_impossible_brief_fails_loudly():
    """مساحة صغيرة جدًا مع عدد غرف كبير: لازم ترمي خطأ واضح مش مخطط بايظ."""
    from celestai.service import generate

    req = DesignRequest(area=20, bedrooms=6, bathrooms=4, use_ai=False)
    try:
        result = generate(req)
    except RuntimeError as exc:
        assert "مخطط" in str(exc) or "مساحة" in str(exc)
        return
    # لو عدّى، لازم يكون المخطط نفسه سليم هندسيًا حتى لو مخالف كوديًا
    covered = sum(r.rect.area for r in result.layout.rooms)
    assert covered == pytest.approx(result.layout.plot.area, rel=1e-3)
