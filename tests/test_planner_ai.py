"""اختبارات مُخطِّط الـ AI — تنظيف وتصحيح ناتج الموديل.

الموديل ممكن يرجّع برنامج فيه مشاكل (فراغين مركزيين، مساحة تحت الحد الأدنى،
attach_to بيشاور على حاجة مش موجودة). المحرك الهندسي بيفترض ثوابت معيّنة،
فـ sanitise() لازم يفرضها قبل ما الناتج يوصله.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from celestai.engine import solve
from celestai.models import (
    ArchitecturalProgram,
    BuildingType,
    DesignRequest,
    RoomKind,
    RoomSpec,
)
from celestai.planner.ai import HUB_KINDS, sanitise
from celestai.planner.rules import normalise_program

REQ = DesignRequest(area=120, building_type=BuildingType.APARTMENT)


def _spec(rid, kind, area, **kw):
    return RoomSpec(
        id=rid, name_ar="", name_en="", kind=kind, target_area=area, **kw
    )


def _program(rooms, **kw):
    return ArchitecturalProgram(
        building_type=BuildingType.APARTMENT, rooms=rooms, source="ai", **kw
    )


# ---------------------------------------------------------------------------


def test_hub_is_moved_to_the_front():
    p = sanitise(
        _program([
            _spec("living", RoomKind.LIVING, 22),
            _spec("hall", RoomKind.RECEPTION, 25),
            _spec("bed", RoomKind.BEDROOM, 14),
        ]),
        REQ,
    )
    assert p.rooms[0].id == "hall"
    assert p.rooms[0].kind in HUB_KINDS


def test_missing_hub_is_created_from_the_largest_room():
    p = sanitise(
        _program([
            _spec("living", RoomKind.LIVING, 30),
            _spec("bed", RoomKind.BEDROOM, 14),
        ]),
        REQ,
    )
    assert p.rooms[0].kind in HUB_KINDS
    assert p.rooms[0].id == "living"


def test_extra_hubs_are_demoted():
    p = sanitise(
        _program([
            _spec("hall_a", RoomKind.RECEPTION, 26),
            _spec("hall_b", RoomKind.RECEPTION, 18),
            _spec("bed", RoomKind.BEDROOM, 14),
        ]),
        REQ,
    )
    hubs = [r for r in p.rooms if r.kind in HUB_KINDS]
    assert len(hubs) == 1
    assert p.rooms[0].id == "hall_a"


def test_undersized_rooms_are_raised_to_code_minimum():
    p = sanitise(
        _program([
            _spec("hall", RoomKind.RECEPTION, 24),
            _spec("bed", RoomKind.BEDROOM, 3.0),      # أقل بكتير من 9 م²
        ]),
        REQ,
    )
    bed = next(r for r in p.rooms if r.id == "bed")
    assert bed.target_area >= 9.0


def test_absurd_min_width_is_clamped_to_the_rooms_own_size():
    """min_width أكبر من ضلع المربع المكافئ بيخلي التوزيع مستحيل."""
    p = sanitise(
        _program([
            _spec("hall", RoomKind.RECEPTION, 24),
            _spec("bath", RoomKind.BATH, 4.0, min_width=9.0),
        ]),
        REQ,
    )
    bath = next(r for r in p.rooms if r.id == "bath")
    assert bath.min_width <= (bath.target_area ** 0.5) * 1.05


def test_dangling_attach_to_is_dropped():
    p = sanitise(
        _program([
            _spec("hall", RoomKind.RECEPTION, 24),
            _spec("bath", RoomKind.BATH, 5, attach_to="ghost_room"),
        ]),
        REQ,
    )
    assert next(r for r in p.rooms if r.id == "bath").attach_to is None


def test_attach_to_hub_is_dropped():
    p = sanitise(
        _program([
            _spec("hall", RoomKind.RECEPTION, 24),
            _spec("bath", RoomKind.BATH, 5, attach_to="hall"),
        ]),
        REQ,
    )
    assert next(r for r in p.rooms if r.id == "bath").attach_to is None


def test_chained_attachments_are_broken():
    """ملحق لملحق: المحرك بيدعم مستوى واحد بس."""
    p = sanitise(
        _program([
            _spec("hall", RoomKind.RECEPTION, 24),
            _spec("bed", RoomKind.BEDROOM, 16),
            _spec("bath", RoomKind.BATH, 5, attach_to="bed"),
            _spec("wc", RoomKind.WC, 2.5, attach_to="bath"),
        ]),
        REQ,
    )
    assert next(r for r in p.rooms if r.id == "bath").attach_to == "bed"
    assert next(r for r in p.rooms if r.id == "wc").attach_to is None


def test_only_small_service_rooms_can_be_attached():
    p = sanitise(
        _program([
            _spec("hall", RoomKind.RECEPTION, 24),
            _spec("bed", RoomKind.BEDROOM, 16),
            _spec("kitchen", RoomKind.KITCHEN, 10, attach_to="bed"),
        ]),
        REQ,
    )
    assert next(r for r in p.rooms if r.id == "kitchen").attach_to is None


def test_duplicate_ids_are_made_unique():
    p = sanitise(
        _program([
            _spec("hall", RoomKind.RECEPTION, 24),
            _spec("bed", RoomKind.BEDROOM, 14),
            _spec("bed", RoomKind.BEDROOM, 12),
        ]),
        REQ,
    )
    assert len({r.id for r in p.rooms}) == len(p.rooms)


def test_blank_names_are_filled_from_the_standards():
    p = sanitise(
        _program([
            _spec("hall", RoomKind.RECEPTION, 24),
            _spec("k", RoomKind.KITCHEN, 10),
        ]),
        REQ,
    )
    kitchen = next(r for r in p.rooms if r.id == "k")
    assert kitchen.name_ar == "مطبخ"
    assert kitchen.name_en == "Kitchen"


def test_adjacency_to_unknown_rooms_is_dropped():
    p = sanitise(
        _program(
            [
                _spec("hall", RoomKind.RECEPTION, 24),
                _spec("kitchen", RoomKind.KITCHEN, 10),
            ],
            adjacency=[("kitchen", "ghost"), ("kitchen", "hall")],
        ),
        REQ,
    )
    assert p.adjacency == [("kitchen", "hall")]


def test_negative_areas_are_rejected_at_the_model_layer():
    """خط الدفاع الأول: Pydantic بيرفض مساحة صفر أو سالبة قبل ما توصل للمحرك."""
    with pytest.raises(Exception):
        _spec("x", RoomKind.BEDROOM, 0)


def test_empty_program_is_rejected():
    from celestai.planner.ai import PlannerError

    with pytest.raises(PlannerError):
        sanitise(_program([]), REQ)


# ---------------------------------------------------------------------------
# التكامل: برنامج زي اللي الموديل بيرجّعه لازم يعدّي المحرك كله
# ---------------------------------------------------------------------------


def test_a_realistic_ai_program_solves_end_to_end():
    program = _program(
        [
            _spec("hall", RoomKind.RECEPTION, 24),
            _spec("living", RoomKind.LIVING, 21),
            _spec("kitchen", RoomKind.KITCHEN, 11),
            _spec("bed_master", RoomKind.MASTER_BEDROOM, 19),
            _spec("bed_2", RoomKind.BEDROOM, 14),
            _spec("bed_3", RoomKind.KIDS_BEDROOM, 12),
            _spec("bath_1", RoomKind.BATH, 5, attach_to="bed_master"),
            _spec("wc", RoomKind.WC, 3),
            _spec("home_office", RoomKind.OFFICE_ROOM, 11),
        ],
        design_notes=["ملاحظة من الموديل"],
    )
    program = normalise_program(sanitise(program, REQ), 120)
    layout = solve(program, REQ)[0]

    covered = sum(r.rect.area for r in layout.rooms)
    assert covered == pytest.approx(layout.plot.area, rel=1e-3)

    served = {o.room_id for o in layout.openings if o.kind in ("door", "entry")}
    for r in layout.rooms:
        assert r.spec_id in served, f"{r.name_ar} من غير باب"


def test_planner_falls_back_to_rules_without_credentials(monkeypatch):
    """من غير مفتاح API لازم نرجع للقواعد المدمجة مع تحذير — مش استثناء."""
    import celestai.planner.ai as ai

    # الاختبار لازم يبقى مستقل عن ملف .env المحلي للمطوّر.
    monkeypatch.delenv("CELESTAI_AI_PROVIDER", raising=False)
    from celestai.ai import settings
    settings.reset_runtime_for_tests()
    monkeypatch.setattr(ai, "credentials_available", lambda: False)
    program, warning = ai.build_program(REQ, 120.0, 13.0, 9.2)

    assert program.source == "rules"
    assert warning and "ANTHROPIC_API_KEY" in warning
    assert program.rooms[0].kind in HUB_KINDS


def test_planner_falls_back_when_the_model_call_fails(monkeypatch):
    """أي فشل في الـ API ما ينفعش يوقّف الأداة."""
    import celestai.planner.ai as ai

    monkeypatch.setattr(ai, "credentials_available", lambda: True)

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(ai, "_client", boom)
    program, warning = ai.build_program(REQ, 120.0, 13.0, 9.2)

    assert program.source == "rules"
    assert warning and "تعذّر" in warning


# ---------------------------------------------------------------------------
# اختيار المزوّد — أي مزوّد متوافق مع OpenAI (Groq، OpenRouter، موديل محلي...)
# ---------------------------------------------------------------------------


def test_provider_defaults_to_anthropic(monkeypatch):
    import celestai.planner.ai as ai

    monkeypatch.delenv("CELESTAI_AI_PROVIDER", raising=False)
    assert ai._provider() == "anthropic"


@pytest.mark.parametrize("value", ["openai", "OpenAI", "groq", "GROQ", "openai_compatible", "compatible"])
def test_provider_aliases_map_to_openai(monkeypatch, value):
    import celestai.planner.ai as ai

    monkeypatch.setenv("CELESTAI_AI_PROVIDER", value)
    assert ai._provider() == "openai"


def test_unknown_provider_value_falls_back_to_anthropic(monkeypatch):
    import celestai.planner.ai as ai

    monkeypatch.setenv("CELESTAI_AI_PROVIDER", "something_else")
    assert ai._provider() == "anthropic"


def test_credentials_check_follows_active_provider(monkeypatch):
    """لما المزوّد openai، مفتاح Anthropic ميكفيش والعكس صحيح."""
    import celestai.planner.ai as ai

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CELESTAI_AI_PROVIDER", "openai")

    assert ai.credentials_available() is False
    assert ai.active_provider_label() is None

    monkeypatch.setenv("OPENAI_API_KEY", "gsk_fake")
    assert ai.credentials_available() is True
    assert ai.active_provider_label() == "openai"

    # مفتاح Anthropic لوحده ميكفيش لما المزوّد المفعّل openai
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    assert ai.credentials_available() is False


def test_openai_model_uses_provider_default_then_env_override(monkeypatch):
    import celestai.planner.ai as ai

    monkeypatch.setenv("CELESTAI_AI_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("CELESTAI_AI_MODEL", raising=False)
    assert ai._openai_model() == "gpt-5-mini"

    monkeypatch.setenv("CELESTAI_AI_MODEL", "llama-3.3-70b-versatile")
    assert ai._openai_model() == "llama-3.3-70b-versatile"


@pytest.mark.parametrize(
    "raw,expected_start",
    [
        ('{"a": 1}', "{"),
        ('```json\n{"a": 1}\n```', "{"),
        ('```\n{"a": 1}\n```', "{"),
        ('Sure! Here you go:\n{"a": 1}\nHope that helps.', "{"),
    ],
)
def test_strip_json_fences(raw, expected_start):
    import celestai.planner.ai as ai

    cleaned = ai._strip_json_fences(raw)
    assert cleaned.startswith(expected_start)
    assert cleaned.endswith("}")
    import json

    json.loads(cleaned)  # لازم يبقى JSON صالح بعد التنظيف


def _fake_openai_client(content: str):
    """عميل OpenAI-compatible وهمي بيرجّع نص جاهز، من غير أي اتصال شبكة فعلي."""

    class _Message:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Message(content)

    class _Response:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    class _Completions:
        def __init__(self, content):
            self._content = content
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return _Response(self._content)

    class _Chat:
        def __init__(self, content):
            self.completions = _Completions(content)

    class _Client:
        def __init__(self, content):
            self.chat = _Chat(content)

    return _Client(content)


def _canned_program_json() -> str:
    program = ArchitecturalProgram(
        rooms=[
            _spec("hall", RoomKind.RECEPTION, 24),
            _spec("living", RoomKind.LIVING, 20),
            _spec("kitchen", RoomKind.KITCHEN, 10),
            _spec("bed_1", RoomKind.BEDROOM, 14),
            _spec("bath_1", RoomKind.BATH, 4),
        ],
        source="ai",
    )
    return program.model_dump_json()


def test_build_program_via_openai_compatible_provider(monkeypatch):
    """المسار العام (Groq وغيره) لازم يوصل لبرنامج سليم بالظبط زي مسار Anthropic."""
    import celestai.planner.ai as ai

    monkeypatch.setenv("CELESTAI_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "gsk_fake")
    monkeypatch.setenv("CELESTAI_AI_MODEL", "llama-3.3-70b-versatile")

    fake_client = _fake_openai_client(_canned_program_json())
    monkeypatch.setattr(ai, "_openai_client", lambda: fake_client)

    program, warning = ai.build_program(REQ, 120.0, 13.0, 9.2)

    assert warning is None
    assert program.source == "ai"
    assert program.rooms[0].kind in HUB_KINDS


def test_planner_reuses_an_identical_successful_response(monkeypatch):
    """تكرار نفس التصميم يحفظ استدعاء كامل من غير تغيير البرنامج الناتج."""
    import celestai.planner.ai as ai

    monkeypatch.setenv("CELESTAI_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "gsk_fake")
    monkeypatch.setenv("CELESTAI_AI_MODEL", "llama-3.3-70b-versatile")

    fake_client = _fake_openai_client(_canned_program_json())
    monkeypatch.setattr(ai, "_openai_client", lambda: fake_client)

    first, first_warning = ai.build_program(REQ, 120.0, 13.0, 9.2)
    second, second_warning = ai.build_program(REQ, 120.0, 13.0, 9.2)

    assert first_warning is None and second_warning is None
    assert first.model_dump() == second.model_dump()
    assert fake_client.chat.completions.calls == 1


def test_build_program_via_openai_wraps_json_in_markdown_fences(monkeypatch):
    """بعض الموديلات المجانية بتحط الرد جوه ```json رغم التعليمات — لازم نتعامل معاه."""
    import celestai.planner.ai as ai

    monkeypatch.setenv("CELESTAI_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "gsk_fake")
    monkeypatch.setenv("CELESTAI_AI_MODEL", "llama-3.3-70b-versatile")

    fenced = "Here's the program:\n```json\n" + _canned_program_json() + "\n```"
    fake_client = _fake_openai_client(fenced)
    monkeypatch.setattr(ai, "_openai_client", lambda: fake_client)

    program, warning = ai.build_program(REQ, 120.0, 13.0, 9.2)

    assert warning is None
    assert program.source == "ai"


def test_build_program_via_openai_falls_back_on_invalid_json(monkeypatch):
    """رد مش JSON صالح لازم يرجّعنا للقواعد بتحذير واضح، مش استثناء غير متوقع."""
    import celestai.planner.ai as ai

    monkeypatch.setenv("CELESTAI_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "gsk_fake")
    monkeypatch.setenv("CELESTAI_AI_MODEL", "llama-3.3-70b-versatile")

    fake_client = _fake_openai_client("سيبني أفكر شوية وأرجعلك")
    monkeypatch.setattr(ai, "_openai_client", lambda: fake_client)

    program, warning = ai.build_program(REQ, 120.0, 13.0, 9.2)

    assert program.source == "rules"
    assert warning is not None


def test_build_program_via_openai_without_model_env_falls_back(monkeypatch):
    """مزوّد openai من غير CELESTAI_AI_MODEL لازم يرجع للقواعد، مش يطلع خطأ للمستخدم."""
    import celestai.planner.ai as ai

    monkeypatch.setenv("CELESTAI_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "gsk_fake")
    monkeypatch.delenv("CELESTAI_AI_MODEL", raising=False)

    program, warning = ai.build_program(REQ, 120.0, 13.0, 9.2)

    assert program.source == "rules"
    assert warning is not None


def test_openai_schema_suffix_is_valid_json_schema():
    from celestai.planner.prompts import openai_schema_suffix

    suffix = openai_schema_suffix()
    assert "JSON Schema" in suffix
    # الـ schema بيبدأ بعد السطر اللي فيه "JSON Schema:" — قبل كده فيه backticks
    # جوه النص التوجيهي بتشاور على `{` و`}` كحروف مش كبداية الـ JSON فعليًا
    import json

    marker = "JSON Schema:\n"
    start = suffix.index(marker) + len(marker)
    json.loads(suffix[start:])
