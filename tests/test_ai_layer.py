"""اختبارات طبقة الـ AI — من غير أي استدعاء للموديل.

بنختبر حاجتين:
  1. **الانهيار الآمن** — كل ميزة AI لازم تفشل بهدوء من غير مفتاح، والمخطط
     والأرقام يفضلوا كاملين. دي أهم خاصية في التصميم كله.
  2. **المنطق الحتمي** — تطبيق التعديلات، المُرصِّف، الجلسات، سجل القرارات،
     وفهرس الأكواد. كلها كود عادي وبيتختبر زي أي كود.
"""

from __future__ import annotations

import pytest

from celestai.ai.client import AIUnavailable, Image, strip_json_fences, telemetry
from celestai.ai.edits import apply_edits
from celestai.ai.schemas import ProgramEdit
from celestai.models import BuildingType, DesignRequest, RoomKind
from celestai.planner.rules import build_program, normalise_program
from celestai.rationale import RationaleLog
from celestai.session import SessionStore


@pytest.fixture
def program():
    req = DesignRequest(area=120, building_type=BuildingType.APARTMENT,
                        bedrooms=3, use_ai=False)
    return normalise_program(build_program(req), 120)


# ---------------------------------------------------------------------------
# الانهيار الآمن من غير مفتاح
# ---------------------------------------------------------------------------


@pytest.fixture
def no_keys(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent-celestai-test")
    monkeypatch.delenv("CELESTAI_AI_PROVIDER", raising=False)


def test_ask_raises_cleanly_without_keys(no_keys):
    from celestai.ai.client import ask
    from celestai.ai.schemas import ReviewAdvice

    with pytest.raises(AIUnavailable):
        ask("sys", "user", ReviewAdvice)


def test_every_ai_feature_returns_none_without_keys(no_keys):
    """مفيش ميزة واحدة المفروض ترمي استثناء لو مفيش مفتاح."""
    from celestai.ai.furnish import furnish
    from celestai.ai.review import explain_issues
    from celestai.ai.vision import read_site_document, read_sketch
    from celestai.engine.solver import solve

    req = DesignRequest(area=110, building_type=BuildingType.APARTMENT, use_ai=False)
    prog = normalise_program(build_program(req), 110)
    layout = solve(prog, req)[0]

    assert explain_issues(layout, prog, req) is None
    assert furnish(layout) is None
    assert read_sketch([]) is None
    assert read_site_document([]) is None


def test_generate_still_works_with_every_flag_and_no_keys(no_keys, tmp_path):
    """العَلَم بيتفعّل، الـ AI مش متاح، والنتيجة لازم تفضل كاملة."""
    from celestai.service import generate

    req = DesignRequest(area=120, building_type=BuildingType.APARTMENT,
                        bedrooms=3, use_ai=False, outputs=["svg"])
    result = generate(
        req, out_dir=tmp_path, repair=True, explain=True,
        solar_city="cairo", finishes_tier="standard", furnish=True,
    )
    assert result.layout.rooms
    assert result.solar, "التحليل الشمسي حتمي — لازم يشتغل"
    assert result.rationale, "سجل القرارات حتمي — لازم يشتغل"
    assert result.review == {}, "المراجعة محتاجة AI — لازم تفضل فاضية"
    assert result.finishes == {}
    assert result.furniture == {}


def test_repair_loop_falls_back_to_trimming(no_keys):
    from celestai.ai.repair import repair_loop

    req = DesignRequest(area=95, building_type=BuildingType.APARTMENT,
                        bedrooms=2, use_ai=False)
    prog = normalise_program(build_program(req), 95)
    layout, program, _alts = repair_loop(prog, req, None)
    assert layout is not None
    assert program.rooms


def test_options_fall_back_to_plain_generate(no_keys, tmp_path):
    from celestai.service import generate_options

    req = DesignRequest(area=120, building_type=BuildingType.APARTMENT,
                        bedrooms=3, use_ai=False, outputs=["svg"])
    result = generate_options(req, out_dir=tmp_path, count=3)
    assert result.layout.rooms
    assert result.options == {}, "من غير AI مفيش مقارنة — والمخطط لسه موجود"


# ---------------------------------------------------------------------------
# تطبيق التعديلات
# ---------------------------------------------------------------------------


def test_resize_applies_and_keeps_id(program):
    room = program.rooms[2]
    out = apply_edits(program, [
        ProgramEdit(op="resize", room_id=room.id, value=room.target_area + 4)
    ])
    assert out.changed
    changed = next(r for r in out.program.rooms if r.id == room.id)
    assert changed.target_area > room.target_area


def test_resize_below_code_minimum_is_rejected(program):
    bath = next(r for r in program.rooms if r.kind == RoomKind.BATH)
    out = apply_edits(program, [
        ProgramEdit(op="resize", room_id=bath.id, value=0.5)
    ])
    assert not out.changed
    assert out.rejected


def test_hub_cannot_be_removed(program):
    out = apply_edits(program, [
        ProgramEdit(op="remove", room_id=program.rooms[0].id)
    ])
    assert not out.changed
    assert out.rejected


def test_removing_a_room_redistributes_its_area(program):
    victim = program.rooms[-1]
    before = sum(r.target_area for r in program.rooms)
    out = apply_edits(program, [ProgramEdit(op="remove", room_id=victim.id)])
    assert out.changed
    after = sum(r.target_area for r in out.program.rooms)
    assert after == pytest.approx(before, rel=0.02), "المساحة الكلية لازم تفضل ثابتة"


def test_adding_a_room_takes_area_from_the_others(program):
    before = sum(r.target_area for r in program.rooms)
    out = apply_edits(program, [
        ProgramEdit(op="add", room_id="study", kind=RoomKind.OFFICE_ROOM, value=9.0)
    ])
    assert out.changed
    after = sum(r.target_area for r in out.program.rooms)
    assert after == pytest.approx(before, rel=0.03)
    assert any(r.kind == RoomKind.OFFICE_ROOM for r in out.program.rooms)


def test_only_wet_rooms_and_storage_can_be_en_suite(program):
    bedroom = next(r for r in program.rooms if r.kind == RoomKind.BEDROOM)
    kitchen = next(r for r in program.rooms if r.kind == RoomKind.KITCHEN)
    out = apply_edits(program, [
        ProgramEdit(op="attach", room_id=kitchen.id, target_id=bedroom.id)
    ])
    assert not out.changed and out.rejected


def test_unknown_room_is_rejected_not_crashed(program):
    out = apply_edits(program, [
        ProgramEdit(op="resize", room_id="does_not_exist", value=20)
    ])
    assert not out.changed and out.rejected


def test_edits_never_mutate_the_original(program):
    before = [(r.id, r.target_area) for r in program.rooms]
    apply_edits(program, [
        ProgramEdit(op="resize", room_id=program.rooms[1].id, value=99)
    ])
    assert [(r.id, r.target_area) for r in program.rooms] == before


# ---------------------------------------------------------------------------
# الجلسات والتراجع
# ---------------------------------------------------------------------------


def _session():
    from celestai.service import generate

    req = DesignRequest(area=110, building_type=BuildingType.APARTMENT,
                        bedrooms=2, use_ai=False, outputs=["svg"])
    result = generate(req, out_dir=None, alternatives=0)
    return SessionStore(), req, result


def test_session_roundtrip_and_expiry():
    store, req, result = _session()
    session = store.create(req, result)
    assert store.get(session.session_id) is session
    store.drop(session.session_id)
    assert store.get(session.session_id) is None


def test_undo_and_redo_restore_the_layout():
    store, req, result = _session()
    session = store.create(req, result)

    assert not session.undo(), "مفيش حاجة نرجعها في الأول"

    snap = session.snapshot()
    original = session.layout.metrics["net_area"]
    session.push_undo(snap)

    # نحاكي تعديل
    session.result.layout = session.result.layout.model_copy(deep=True)
    session.result.layout.metrics["net_area"] = 1.0

    assert session.undo()
    assert session.layout.metrics["net_area"] == original
    assert session.redo()
    assert session.layout.metrics["net_area"] == 1.0


def test_pushing_undo_clears_redo():
    store, req, result = _session()
    session = store.create(req, result)
    session.push_undo(session.snapshot())
    session.undo()
    assert session.redo_stack
    session.push_undo(session.snapshot())
    assert not session.redo_stack


# ---------------------------------------------------------------------------
# سجل القرارات
# ---------------------------------------------------------------------------


def test_rationale_log_groups_and_renders():
    log = RationaleLog()
    log.add("program", "برنامج فيه 9 فراغ", what_en="9 spaces", by="ai")
    log.add("plot", "قطعة 12×10", what_en="12x10 plot", why_ar="أقل مخالفات")
    assert len(log) == 2
    assert set(log.by_stage()) == {"program", "plot"}
    md = log.to_markdown("ar")
    assert "دفتر التصميم" in md and "برنامج فيه 9 فراغ" in md
    assert "12x10" in log.to_markdown("en")


def test_empty_rationale_renders_nothing():
    from celestai.rationale import narrate

    assert narrate(RationaleLog()) == ""


# ---------------------------------------------------------------------------
# المُرصِّف الحتمي للأثاث
# ---------------------------------------------------------------------------


def test_furniture_packer_respects_room_bounds():
    from celestai.ai.furnish import pack_room
    from celestai.ai.schemas import FurniturePiece
    from celestai.engine.solver import solve

    req = DesignRequest(area=120, building_type=BuildingType.APARTMENT,
                        bedrooms=3, use_ai=False)
    layout = solve(normalise_program(build_program(req), 120), req)[0]
    room = max(
        (r for r in layout.rooms if r.kind == RoomKind.BEDROOM),
        key=lambda r: r.net_area,
    )

    pieces = [
        FurniturePiece(name_ar="سرير", width=1.6, depth=2.0, priority=1),
        FurniturePiece(name_ar="دولاب", width=1.8, depth=0.6, priority=2),
    ]
    placed, _dropped = pack_room(room, pieces, layout.openings)
    n = room.net_rect
    for p in placed:
        assert p.rect.x >= n.x - 1e-6 and p.rect.y >= n.y - 1e-6
        assert p.rect.x2 <= n.x2 + 1e-6 and p.rect.y2 <= n.y2 + 1e-6


def test_furniture_packer_drops_what_does_not_fit():
    from celestai.ai.furnish import pack_room
    from celestai.ai.schemas import FurniturePiece
    from celestai.engine.solver import solve

    req = DesignRequest(area=120, building_type=BuildingType.APARTMENT, use_ai=False)
    layout = solve(normalise_program(build_program(req), 120), req)[0]
    small = min(layout.rooms, key=lambda r: r.net_area)

    absurd = [
        FurniturePiece(name_ar=f"قطعة {i}", width=2.5, depth=2.0, priority=4)
        for i in range(8)
    ]
    placed, dropped = pack_room(small, absurd, layout.openings)
    assert dropped, "لازم يقول إيه اللي مدخلش بدل ما يحشره"
    assert len(placed) < len(absurd)


# ---------------------------------------------------------------------------
# العميل والتليمتري
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected_repair", [
    ('{"a": 1}', False),
    ('```json\n{"a": 1}\n```', True),
    ('Here is the answer:\n{"a": 1}\nHope that helps', True),
])
def test_strip_json_fences(raw, expected_repair):
    import json

    cleaned, repaired = strip_json_fences(raw)
    assert json.loads(cleaned) == {"a": 1}
    assert repaired is expected_repair


def test_telemetry_counts_and_resets():
    telemetry.reset()
    telemetry.record("anthropic", "review", 1.2)
    telemetry.record("anthropic", "review", 0.8, failed=True)
    telemetry.record("anthropic", "chat", 0.5, repaired=True)
    snap = telemetry.snapshot()["anthropic"]
    assert snap["calls"] == 3 and snap["failures"] == 1 and snap["repairs"] == 1
    assert snap["failure_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert snap["tasks"] == {"review": 2, "chat": 1}
    telemetry.reset()
    assert telemetry.snapshot() == {}


def test_image_rejects_oversized_and_unknown_types():
    from celestai.ai.client import validate_images

    with pytest.raises(ValueError):
        validate_images([Image(data=b"x", media_type="image/tiff")])
    with pytest.raises(ValueError):
        validate_images([Image(data=b"x" * (6 * 1024 * 1024))])


def test_image_from_data_url():
    import base64

    payload = base64.b64encode(b"fake").decode()
    img = Image.from_data_url(f"data:image/png;base64,{payload}")
    assert img.data == b"fake" and img.media_type == "image/png"


# ---------------------------------------------------------------------------
# الأكواد
# ---------------------------------------------------------------------------


def test_builtin_codes_and_review_flags():
    from celestai.codes import available_codes, get_code

    ids = {c["id"] for c in available_codes()}
    assert "eg" in ids
    assert get_code("eg").reviewed is True, "المصري متختبر فمراجَع"
    assert get_code("gulf").reviewed is False, "المتغيّرات غير مراجَعة"
    assert get_code("nonexistent").code_id == "eg", "أي كود مجهول يرجع للمصري"


def test_code_corpus_retrieval_ranks_by_relevance():
    from celestai.codes import CodeCorpus

    c = CodeCorpus()
    n = c.add_text(
        "3-1 الحد الأدنى لمساحة غرفة النوم تسعة أمتار مربعة وأقل بُعد 2.70 متر.\n\n"
        "3-2 مساحة الشبابيك لا تقل عن عُشر مساحة أرضية الفراغ للإضاءة الطبيعية.\n\n"
        "4-1 عرض الممر لا يقل عن 1.10 متر في المباني السكنية.\n",
        source="test-code",
    )
    assert n == 3
    hits = c.search("مساحة غرفة النوم")
    assert hits and hits[0][0].clause_id == "3-1"
    assert c.search("الشبابيك الإضاءة")[0][0].clause_id == "3-2"


def test_empty_corpus_searches_safely():
    from celestai.codes import CodeCorpus

    assert CodeCorpus().search("أي حاجة") == []


def test_codebook_roundtrips_through_disk(tmp_path):
    from celestai.codes import CodeBook, get_code

    path = get_code("eg").save(tmp_path / "eg.json")
    loaded = CodeBook.load(path)
    assert loaded.code_id == "eg"
    assert loaded.standards[RoomKind.BEDROOM].min_area == \
        get_code("eg").standards[RoomKind.BEDROOM].min_area


# ---------------------------------------------------------------------------
# ذاكرة الأسلوب
# ---------------------------------------------------------------------------


def test_style_memory_roundtrip_and_forget(tmp_path, monkeypatch):
    from celestai.ai.schemas import StylePreference
    from celestai.ai.style import StyleMemory

    monkeypatch.setenv("CELESTAI_STYLE_DIR", str(tmp_path))
    m = StyleMemory()
    m.preferences = [
        StylePreference(key="open_kitchen", statement_ar="بيفضّل المطبخ مفتوح"),
    ]
    m.save()

    again = StyleMemory.load()
    assert len(again.preferences) == 1
    assert again.forget("open_kitchen")
    assert not again.forget("open_kitchen")


def test_disabled_style_injects_nothing():
    from celestai.ai.schemas import StylePreference
    from celestai.ai.style import StyleMemory

    m = StyleMemory(preferences=[StylePreference(key="k", statement_ar="حاجة")])
    assert m.prompt_block()
    m.enabled = False
    assert m.prompt_block() == ""


def test_style_needs_several_signals_before_learning(no_keys):
    from celestai.ai.style import StyleMemory, learn

    m = StyleMemory()
    m.record("asked: كبّر الصالة")
    assert learn(m).preferences == [], "إشارة واحدة مش أسلوب"


# ---------------------------------------------------------------------------
# ب-3 · الصوت
# ---------------------------------------------------------------------------


def test_speech_is_off_unless_configured(monkeypatch):
    from celestai.ai.speech import SpeechUnavailable, stt_available, transcribe

    monkeypatch.delenv("CELESTAI_STT_MODEL", raising=False)
    assert not stt_available()
    with pytest.raises(SpeechUnavailable):
        transcribe(b"audio")


def test_tidy_brief_keeps_meaning():
    from celestai.ai.speech import tidy_brief

    out = tidy_brief("  عايز   شقة يعني تلات غرف   نوم  ")
    assert "تلات غرف نوم" in out
    assert "  " not in out
