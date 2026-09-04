"""اختبارات الطبقات التحليلية الحتمية — كلها بتشتغل من غير AI.

المبدأ: الحاجات دي **مش محتاجة موديل**. لو اختبار هنا احتاج مفتاح API،
يبقى فيه حاجة غلط في التصميم.
"""

from __future__ import annotations

import math

import pytest

from celestai.analysis.quantities import PriceBook, boq_markdown, take_off
from celestai.analysis.solar import (
    CITIES,
    analyse_solar,
    facade_irradiation,
    solar_markdown,
    sun_position,
)
from celestai.engine.solver import solve
from celestai.knowledge import orientation_penalty
from celestai.models import BuildingType, DesignRequest, RoomKind
from celestai.planner.rules import build_program, normalise_program


def _layout(area=120, bt=BuildingType.APARTMENT, **kw):
    req = DesignRequest(area=area, building_type=bt, use_ai=False, **kw)
    program = normalise_program(build_program(req), area)
    return req, solve(program, req)[0]


# ---------------------------------------------------------------------------
# د-1 · الكميات
# ---------------------------------------------------------------------------


def test_take_off_produces_items_without_ai():
    _req, layout = _layout()
    boq = take_off(layout)
    assert boq.items, "لازم يطلّع بنود"
    assert not boq.priced, "من غير جدول أسعار ميعرضش أسعار"
    assert boq.subtotal is None
    assert all(i.quantity > 0 for i in boq.items)


def test_take_off_never_invents_prices():
    """أهم اختبار في الملف: من غير جدول أسعار، مفيش رقم فلوس خالص."""
    _req, layout = _layout()
    boq = take_off(layout)
    assert all(i.unit_rate is None for i in boq.items)
    assert boq.low is None and boq.high is None
    md = boq_markdown(boq, "ar")
    assert "مفيش أسعار" in md


def test_priced_take_off_gives_a_range_not_a_point(tmp_path):
    import json

    book = tmp_path / "prices.json"
    book.write_text(json.dumps({
        "currency": "EGP", "date": "2026-01-01",
        "rates": {"BLK-EXT": 2400, "BLK-INT": 2100, "PLS": 180, "FLR-DRY": 650},
    }), encoding="utf-8")

    _req, layout = _layout()
    boq = take_off(layout, prices=PriceBook.load(book))
    assert boq.priced
    assert boq.subtotal and boq.subtotal > 0
    assert boq.low < boq.subtotal < boq.high, "التقدير المبدئي لازم يكون نطاق"


def test_quantities_scale_with_floors():
    _req, layout = _layout()
    one = take_off(layout, floors=1)
    three = take_off(layout, floors=3)
    a = next(i for i in one.items if i.code == "PLS")
    b = next(i for i in three.items if i.code == "PLS")
    assert b.quantity == pytest.approx(a.quantity * 3, rel=1e-6)


def test_openings_are_deducted_from_walls():
    """الفتحات لازم تتخصم — حيطة كلها شباك مالهاش مباني."""
    _req, layout = _layout()
    boq = take_off(layout)
    plaster = next(i for i in boq.items if i.code == "PLS")
    wall_area = sum(w.length for w in layout.walls) * 3.0 * 2
    assert plaster.quantity < wall_area * 1.05, "المحارة مخصمتش الفتحات"


# ---------------------------------------------------------------------------
# د-2 · الشمس
# ---------------------------------------------------------------------------


def test_sun_is_higher_in_summer_than_winter():
    """اختبار عقل: الشمس في القاهرة أعلى الظهر في يونيو عن ديسمبر."""
    summer, _ = sun_position(30.04, 172, 12.0)
    winter, _ = sun_position(30.04, 355, 12.0)
    assert summer > winter
    assert math.degrees(summer) > 70
    assert math.degrees(winter) < 45


def test_west_facade_is_the_worst_in_summer():
    """الأساس اللي كل التوجيه مبني عليه."""
    lat = 30.04
    west = facade_irradiation("west", lat, 172)
    north = facade_irradiation("north", lat, 172)
    assert west > north * 1.5


def test_south_gains_more_in_winter_than_summer():
    """الواجهة الجنوبية: شمس منخفضة شتاءً بتدخل، وعالية صيفًا فبتتظلّل."""
    lat = 30.04
    assert facade_irradiation("south", lat, 355) > facade_irradiation("south", lat, 172)


def test_orientation_penalty_ranks_bedrooms_worse_on_west():
    assert (orientation_penalty(RoomKind.BEDROOM, "west")
            > orientation_penalty(RoomKind.BEDROOM, "north"))
    # المطبخ بيولّد حرارة أصلًا فأقل حساسية من غرفة النوم
    assert (orientation_penalty(RoomKind.KITCHEN, "west")
            < orientation_penalty(RoomKind.BEDROOM, "west"))
    assert orientation_penalty(RoomKind.STORAGE, "west") == 0.0


def test_solar_report_runs_without_ai():
    _req, layout = _layout()
    report = analyse_solar(layout, "cairo")
    assert report.latitude == pytest.approx(30.04)
    assert 0.0 <= report.summer_load_index <= 1.5
    assert report.advice is None, "من غير AI مفيش سرد — والأرقام لسه موجودة"
    assert "التوجيه" in solar_markdown(report, "ar")


@pytest.mark.parametrize("city", sorted(CITIES))
def test_every_city_produces_a_sane_report(city):
    _req, layout = _layout()
    report = analyse_solar(layout, city)
    assert report.summer_load_index >= 0.0
    assert all(w.summer_wh >= 0 for w in report.windows)


def test_unknown_city_falls_back_to_cairo():
    _req, layout = _layout()
    assert analyse_solar(layout, "atlantis").city == "cairo"


# ---------------------------------------------------------------------------
# هـ-1 · الجدوى
# ---------------------------------------------------------------------------


def test_feasibility_search_is_deterministic_and_ranked():
    from celestai.analysis.feasibility import study_feasibility

    study = study_feasibility(300, min_floors=2, max_floors=3, limit=6)
    assert study.scenarios
    scores = [s.score for s in study.scenarios]
    assert scores == sorted(scores, reverse=True), "لازم تكون مرتّبة"
    assert study.best is not None
    assert study.best.total_units > 0
    assert study.advice is None, "البحث حتمي — السرد اختياري"


def test_feasibility_repeats_identically():
    from celestai.analysis.feasibility import study_feasibility

    a = study_feasibility(300, min_floors=2, max_floors=2, limit=4)
    b = study_feasibility(300, min_floors=2, max_floors=2, limit=4)
    assert [s.scenario_id for s in a.scenarios] == [s.scenario_id for s in b.scenarios]
    assert [round(s.score, 6) for s in a.scenarios] == \
           [round(s.score, 6) for s in b.scenarios]


def test_objectives_normalise():
    from celestai.analysis.feasibility import Objectives

    w = Objectives(sellable=2, compliance=2, efficiency=1, cost=1, daylight=0).normalised()
    assert sum([w.sellable, w.compliance, w.efficiency, w.cost, w.daylight]) == \
        pytest.approx(1.0)
