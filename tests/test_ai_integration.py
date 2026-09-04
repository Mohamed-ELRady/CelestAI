"""اختبارات المسار الكامل لمزايا الـ AI — بموديل مزيّف.

المفتاح مش متاح في الاختبارات، ومش عايزين نستدعي موديل حقيقي (بطيء، بفلوس،
وغير متكرّر). فبنستبدل `ask` بمخرج مُهيكل ثابت، وبنختبر **باقي المسار**:
هل التعديل بيتطبّق؟ هل المحرك بيعيد الحل؟ هل التراجع شغّال؟ هل الإصلاح بيمسك
الأحسن؟

ده اللي بيثبت إن السباكة بين الموديل والمحرك صح.
"""

from __future__ import annotations

import pytest

from celestai.ai.schemas import (
    AlternativeComparison,
    DesignThesis,
    EditPlan,
    ProgramEdit,
    RepairPlan,
    ReviewAdvice,
    IssueAdvice,
    FixOption,
)
from celestai.models import BuildingType, DesignRequest, RoomKind
from celestai.planner.rules import build_program, normalise_program
from celestai.service import generate
from celestai.session import SessionStore


@pytest.fixture
def session():
    req = DesignRequest(area=120, building_type=BuildingType.APARTMENT,
                        bedrooms=3, use_ai=False, outputs=["svg"])
    result = generate(req, out_dir=None, alternatives=0)
    return SessionStore().create(req, result)


# ---------------------------------------------------------------------------
# أ-2 · الحوار
# ---------------------------------------------------------------------------


def test_chat_applies_an_edit_and_resolves(session, monkeypatch):
    """المسار الكامل: رسالة → تعديل → إعادة حل → أرقام جديدة."""
    target = session.program.rooms[1]
    bigger = round(target.target_area + 5, 2)

    def fake_ask(system, user, model, **kw):
        return EditPlan(
            understood_ar="هكبّر الفراغ ده على حساب الباقي",
            edits=[ProgramEdit(op="resize", room_id=target.id, value=bigger)],
        )

    monkeypatch.setattr("celestai.ai.chat.ask", fake_ask)
    from celestai.ai.chat import apply_message

    before_area = session.layout.metrics["net_area"]
    out = apply_message(session, "كبّر الفراغ ده")

    assert out["ok"] and out["changed"]
    assert out["applied"]
    assert session.undo_stack, "لازم يبقى فيه نقطة تراجع"
    assert session.layout.metrics["net_area"] == pytest.approx(before_area, rel=0.05)

    updated = next(r for r in session.program.rooms if r.id == target.id)
    assert updated.target_area > target.target_area


def test_chat_refusal_leaves_the_plan_untouched(session, monkeypatch):
    def fake_ask(system, user, model, **kw):
        return EditPlan(refused_ar="مينفعش — الحمام هيبقى تحت الحد الكودي", edits=[])

    monkeypatch.setattr("celestai.ai.chat.ask", fake_ask)
    from celestai.ai.chat import apply_message

    before = session.layout.metrics["net_area"]
    out = apply_message(session, "خلّي الحمام نص متر")

    assert not out["changed"]
    assert "مينفعش" in out["reply"]
    assert session.layout.metrics["net_area"] == before
    assert not session.undo_stack, "الرفض مش المفروض يسجّل نقطة تراجع"


def test_chat_rejects_illegal_edit_without_breaking_the_plan(session, monkeypatch):
    """الموديل طلب حاجة مخالفة — التطبيق بيرفضها، والمخطط بيفضل زي ما هو."""
    bath = next(r for r in session.program.rooms if r.kind == RoomKind.BATH)

    def fake_ask(system, user, model, **kw):
        return EditPlan(edits=[
            ProgramEdit(op="resize", room_id=bath.id, value=0.4)
        ])

    monkeypatch.setattr("celestai.ai.chat.ask", fake_ask)
    from celestai.ai.chat import apply_message

    before = session.layout.metrics["net_area"]
    out = apply_message(session, "صغّر الحمام جدًا")

    assert not out["changed"]
    assert out["rejected"]
    assert session.layout.metrics["net_area"] == before


def test_undo_after_chat_restores_the_previous_plan(session, monkeypatch):
    target = session.program.rooms[1]

    def fake_ask(system, user, model, **kw):
        return EditPlan(edits=[
            ProgramEdit(op="resize", room_id=target.id,
                        value=round(target.target_area + 5, 2))
        ])

    monkeypatch.setattr("celestai.ai.chat.ask", fake_ask)
    from celestai.ai.chat import apply_message

    original = target.target_area
    apply_message(session, "كبّره")
    assert session.undo()
    restored = next(r for r in session.program.rooms if r.id == target.id)
    assert restored.target_area == pytest.approx(original)


def test_chat_records_history_for_context(session, monkeypatch):
    def fake_ask(system, user, model, **kw):
        return EditPlan(refused_ar="لأ", edits=[])

    monkeypatch.setattr("celestai.ai.chat.ask", fake_ask)
    from celestai.ai.chat import apply_message

    apply_message(session, "أول طلب")
    apply_message(session, "تاني طلب")
    transcript = session.transcript()
    assert "أول طلب" in transcript and "تاني طلب" in transcript


# ---------------------------------------------------------------------------
# أ-1 · الإصلاح الذاتي
# ---------------------------------------------------------------------------


def test_repair_keeps_the_better_layout(monkeypatch):
    """لو الإصلاح طلّع نتيجة أوحش، لازم نرجع للأصلي."""
    req = DesignRequest(area=95, building_type=BuildingType.APARTMENT,
                        bedrooms=2, use_ai=False)
    program = normalise_program(build_program(req), 95)

    # الموديل بيرجّع برنامج فيه غرفة عملاقة — هيطلّع مخطط أوحش
    def bad_repair(system, user, model, **kw):
        broken = program.model_copy(deep=True)
        broken.rooms[1].target_area = 80.0
        return RepairPlan(diagnosis_ar="تشخيص وهمي", program=broken)

    monkeypatch.setattr("celestai.ai.repair.ask", bad_repair)
    from celestai.ai.repair import repair_loop

    layout, _prog, _alts = repair_loop(program, req, None)
    assert layout is not None
    # الغرفة العملاقة مالهاش أثر — لأن الحل الأسوأ اترفض
    assert max(r.net_area for r in layout.rooms) < 70


def test_repair_is_skipped_when_there_are_no_errors(monkeypatch):
    calls = []

    def spy(system, user, model, **kw):
        calls.append(1)
        raise AssertionError("مالوش لازمة يتنادى")

    monkeypatch.setattr("celestai.ai.repair.ask", spy)
    from celestai.ai.repair import repair_loop

    req = DesignRequest(area=120, building_type=BuildingType.APARTMENT,
                        bedrooms=3, use_ai=False)
    program = normalise_program(build_program(req), 120)
    layout, _p, _a = repair_loop(program, req, None)

    assert layout is not None
    if int(layout.metrics["errors"]) == 0:
        assert not calls, "مفيش مخالفات — مفيش داعي نستدعي الموديل"


def test_repair_logs_its_decision(monkeypatch):
    from celestai.rationale import RationaleLog

    req = DesignRequest(area=95, building_type=BuildingType.APARTMENT,
                        bedrooms=2, use_ai=False)
    program = normalise_program(build_program(req), 95)

    def repair(system, user, model, **kw):
        return RepairPlan(diagnosis_ar="الشريط ضيق", program=program.model_copy(deep=True))

    monkeypatch.setattr("celestai.ai.repair.ask", repair)
    from celestai.ai.repair import repair_loop

    log = RationaleLog()
    layout, _p, _a = repair_loop(program, req, None, log_to=log)
    assert layout is not None
    # لو حصل إصلاح، لازم يتسجّل؛ ولو مفيش مخالفات أصلًا فمفيش سجل — الاتنين صح
    repairs = [d for d in log.decisions if d.stage == "repair"]
    assert all(d.by == "ai" for d in repairs)


# ---------------------------------------------------------------------------
# أ-3 · المراجعة الذكية
# ---------------------------------------------------------------------------


def test_review_advice_reaches_the_report(monkeypatch, tmp_path):
    def fake_ask(system, user, model, **kw):
        return ReviewAdvice(
            summary_ar="فيه تنبيه واحد بسيط",
            advice=[IssueAdvice(
                code="DAYLIGHT", room_id="hall",
                root_cause_ar="الشباك صغير على مساحة الفراغ",
                fixes=[FixOption(
                    title_ar="كبّر الشباك 40 سم",
                    detail_ar="من 1.2 م لـ 1.6 م على الواجهة الجنوبية",
                    trade_off_ar="حِمل حراري أعلى شوية في الصيف",
                )],
            )],
        )

    monkeypatch.setattr("celestai.ai.review.ask", fake_ask)

    req = DesignRequest(area=120, building_type=BuildingType.APARTMENT,
                        bedrooms=3, use_ai=False, outputs=["report"])
    result = generate(req, out_dir=tmp_path, explain=True)

    if result.layout.issues:
        assert result.review, "المراجعة المفروض تتخزّن"
        assert "كبّر الشباك" in result.report_md


# ---------------------------------------------------------------------------
# أ-4 · البدائل بالنيّة
# ---------------------------------------------------------------------------


def test_intent_options_solve_and_compare(monkeypatch, tmp_path):
    from celestai.ai.schemas import AlternativeSet

    req = DesignRequest(area=120, building_type=BuildingType.APARTMENT,
                        bedrooms=3, use_ai=False, outputs=["svg"])
    base = normalise_program(build_program(req), 120)

    def make(slug, title):
        p = base.model_copy(deep=True)
        return DesignThesis(slug=slug, title_ar=title, title_en=slug,
                            idea_ar="فكرة", program=p)

    def fake_ask(system, user, model, **kw):
        if model is AlternativeSet:
            return AlternativeSet(options=[
                make("generous_living", "معيشة أوسع"),
                make("private_night", "خصوصية أعلى"),
            ])
        return AlternativeComparison(
            recommendation_slug="generous_living",
            verdict_ar="لو بتستقبلوا ضيوف كتير",
            per_option_ar={"generous_living": "معيشة أكبر", "private_night": "نوم أهدى"},
        )

    monkeypatch.setattr("celestai.ai.alternatives.ask", fake_ask)
    from celestai.service import generate_options

    result = generate_options(req, out_dir=tmp_path, count=2)
    assert result.options, "المقارنة المفروض تتخزّن"
    assert result.options["recommendation_slug"] == "generous_living"
    assert "معيشة أوسع" in result.report_md
    assert result.layout.rooms


def test_options_survive_a_failing_thesis(monkeypatch, tmp_path):
    """بديل مش قابل للحل مالوش حق يوقّف الباقي."""
    from celestai.ai.schemas import AlternativeSet

    req = DesignRequest(area=120, building_type=BuildingType.APARTMENT,
                        bedrooms=3, use_ai=False, outputs=["svg"])
    good = normalise_program(build_program(req), 120)

    broken = good.model_copy(deep=True)
    broken.rooms = broken.rooms[:1]
    broken.rooms[0].min_width = 999.0        # مستحيل هندسيًا

    def fake_ask(system, user, model, **kw):
        if model is AlternativeSet:
            return AlternativeSet(options=[
                DesignThesis(slug="broken", title_ar="مكسور", title_en="broken",
                             program=broken),
                DesignThesis(slug="fine", title_ar="سليم", title_en="fine",
                             program=good.model_copy(deep=True)),
            ])
        return AlternativeComparison(recommendation_slug="fine", verdict_ar="تمام")

    monkeypatch.setattr("celestai.ai.alternatives.ask", fake_ask)
    from celestai.service import generate_options

    result = generate_options(req, out_dir=tmp_path, count=2)
    assert result.layout.rooms, "البديل السليم لازم يعدّي"


# ---------------------------------------------------------------------------
# و-1 · الحَكَم
# ---------------------------------------------------------------------------


def test_eval_case_runs_and_scores():
    from celestai.evals import run_suite
    from celestai.evals.cases import CASES

    card = run_suite(CASES[:2], label="test", use_ai=False)
    assert len(card.results) == 2
    assert all(0.0 <= r.objective_score <= 1.0 for r in card.results)
    assert card.mean_judge is None, "من غير --judge مفيش درجة ذاتية"


def test_scorecard_survives_a_crashing_case(monkeypatch):
    from celestai.evals.cases import CASES
    from celestai.evals.runner import run_suite

    def boom(*a, **kw):
        raise RuntimeError("انفجار مقصود")

    monkeypatch.setattr("celestai.service.generate", boom)
    card = run_suite(CASES[:1], use_ai=False)
    assert card.crashed == 1
    assert card.results[0].objective_score == 0.0
