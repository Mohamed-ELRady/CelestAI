"""مُخطِّط بالذكاء الاصطناعي — AI-powered architectural programming.

الموديل بيحوّل الطلب (مساحة + وصف حر) لبرنامج معماري منظّم (JSON)، والمحرك الهندسي
بعد كده بيوزّعه على القطعة. لو مفيش مفتاح API أو حصل أي خطأ، بنرجع للمُخطِّط القواعدي.

بيدعم مزوّدين:
  • Anthropic (Claude) — الافتراضي، عن طريق `client.messages.parse` (structured output مضمون).
  • أي مزوّد متوافق مع OpenAI — Groq، OpenRouter، Together، أو حتى موديل محلي عن طريق
    خادم متوافق مع OpenAI زي Ollama. بيتفعّل بمتغيّر البيئة CELESTAI_AI_PROVIDER=openai.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from ..knowledge import HABITABLE, WET_ROOMS, profile, standard
from ..models import ArchitecturalProgram, DesignRequest, RoomKind, RoomSpec
from ..ai import settings
from . import rules
from .prompts import SYSTEM, openai_schema_suffix, user_prompt

log = logging.getLogger("celestai.planner")

HUB_KINDS = {RoomKind.RECEPTION, RoomKind.WAITING, RoomKind.CORRIDOR}


class PlannerError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# اختيار المزوّد
# ---------------------------------------------------------------------------

def _provider() -> str:
    """يرجّع محوّل المزوّد الفعّال (Anthropic أو OpenAI-compatible)."""
    return settings.current().adapter


def _anthropic_credentials_available() -> bool:
    if settings.current().api_key:
        return True
    # بروفايل مخزَّن من `ant auth login`
    cfg = os.environ.get("ANTHROPIC_CONFIG_DIR") or os.path.expanduser("~/.config/anthropic")
    return os.path.isdir(os.path.join(cfg, "credentials"))


def _openai_credentials_available() -> bool:
    return bool(settings.current().api_key)


def credentials_available() -> bool:
    """بيتأكد إن فيه مفتاح صالح للمزوّد المُفعَّل حاليًا."""
    if _provider() == "openai":
        return _openai_credentials_available()
    if _provider() == "anthropic":
        return _anthropic_credentials_available()
    return False


def active_provider_label() -> Optional[str]:
    """اسم المزوّد النشط — للعرض في الواجهة، أو None لو مفيش مفتاح خالص."""
    if not credentials_available():
        return None
    return _provider()


# ---------------------------------------------------------------------------
# عملاء الـ API
# ---------------------------------------------------------------------------


def _client():
    """عميل Anthropic."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise PlannerError("مكتبة anthropic غير مثبّتة") from exc
    # الـ SDK بيقرأ ANTHROPIC_API_KEY أو ANTHROPIC_AUTH_TOKEN أو بروفايل `ant auth login`
    key = settings.current().api_key
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def _openai_client():
    """عميل متوافق مع OpenAI — بيشتغل مع أي مزوّد بيدعم نفس الـ API شكل
    (Groq, OpenRouter, Together, خادم Ollama المحلي، ...إلخ) عن طريق تغيير base_url بس.
    """
    try:
        import openai
    except ImportError as exc:  # pragma: no cover
        raise PlannerError("مكتبة openai غير مثبّتة") from exc
    config = settings.current()
    return openai.OpenAI(api_key=config.api_key, base_url=config.base_url or None)


def _openai_model() -> str:
    model = settings.current().model.strip()
    if not model:
        raise PlannerError(
            "لازم تحدد CELESTAI_AI_MODEL باسم الموديل عند استخدام مزوّد متوافق مع OpenAI"
        )
    return model


def _strip_json_fences(text: str) -> str:
    """يشيل أي ```json fences أو نص زيادة حوالين الـ JSON — بعض الموديلات المجانية
    بتضيفهم رغم التعليمات الصريحة في البرومبت."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


# ---------------------------------------------------------------------------
# تنظيف وتصحيح ناتج الموديل
# ---------------------------------------------------------------------------


def sanitise(program: ArchitecturalProgram, req: DesignRequest) -> ArchitecturalProgram:
    """يصحّح أي مخالفات في ناتج الموديل قبل ما يوصل للمحرك الهندسي."""
    prof = profile(req.building_type)
    rooms: list[RoomSpec] = []
    seen: set[str] = set()

    for r in program.rooms:
        if r.target_area <= 0:
            continue
        rid = r.id.strip().lower().replace(" ", "_") or f"space_{len(rooms)}"
        while rid in seen:
            rid += "_x"
        r.id = rid
        seen.add(rid)

        st = standard(r.kind)
        # المساحة مينفعش تقل عن الحد الأدنى الكودي
        r.target_area = round(max(r.target_area, st.min_area), 3)
        # أقل بُعد لازم يكون منطقي بالنسبة للمساحة (مربع الفراغ)
        max_sensible = (r.target_area ** 0.5) * 1.02
        r.min_width = round(min(max(r.min_width, st.min_width * 0.9), max_sensible), 2)
        r.needs_window = r.needs_window or r.kind in HABITABLE
        r.is_wet = r.is_wet or r.kind in WET_ROOMS
        r.zone = st.zone
        if not r.name_ar.strip():
            r.name_ar = st.name_ar
        if not r.name_en.strip():
            r.name_en = st.name_en
        rooms.append(r)

    if not rooms:
        raise PlannerError("الموديل رجّع برنامج فاضي")

    # لازم يكون فيه فراغ مركزي واحد بالظبط
    hubs = [r for r in rooms if r.kind in HUB_KINDS]
    if not hubs:
        biggest = max(rooms, key=lambda r: r.target_area)
        biggest.kind = prof.hub_kind
        biggest.name_ar = standard(prof.hub_kind).name_ar
        biggest.name_en = standard(prof.hub_kind).name_en
        hubs = [biggest]
    elif len(hubs) > 1:
        hubs.sort(key=lambda r: r.target_area, reverse=True)
        for extra in hubs[1:]:
            extra.kind = RoomKind.LIVING
            extra.zone = standard(RoomKind.LIVING).zone
        hubs = hubs[:1]

    hub = hubs[0]
    # نخلّي الفراغ المركزي أول عنصر في القائمة (المحرك بيعتمد على كده)
    rooms.remove(hub)
    rooms.insert(0, hub)

    # attach_to لازم يشاور على غرفة موجودة ومش هي نفسها ومش الفراغ المركزي
    ids = {r.id for r in rooms}
    for r in rooms:
        if r.attach_to and (r.attach_to not in ids or r.attach_to == r.id or r.attach_to == hub.id):
            r.attach_to = None
        # الملحقات لازم تكون فراغات صحية صغيرة بس
        if r.attach_to and r.kind not in (RoomKind.BATH, RoomKind.WC, RoomKind.STORAGE):
            r.attach_to = None

    # منع التسلسل: ملحق لملحق
    attached = {r.id for r in rooms if r.attach_to}
    for r in rooms:
        if r.attach_to in attached:
            r.attach_to = None

    program.rooms = rooms
    program.adjacency = [
        (a, b) for a, b in program.adjacency if a in ids and b in ids and a != b
    ]
    program.building_type = req.building_type
    return program


# ---------------------------------------------------------------------------
# استدعاء كل مزوّد
# ---------------------------------------------------------------------------


def _build_program_anthropic(
    req: DesignRequest, system: str, usable_area: float, plot_w: float, plot_d: float
) -> ArchitecturalProgram:
    client = _client()
    response = client.messages.parse(
        model=req.model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[
            {"role": "user", "content": user_prompt(req, usable_area, plot_w, plot_d)}
        ],
        output_format=ArchitecturalProgram,
    )
    if response.stop_reason == "refusal":
        raise PlannerError("الموديل رفض الطلب")
    program = response.parsed_output
    if program is None:
        raise PlannerError("الموديل مرجّعش برنامج صالح")
    return program


def _build_program_openai(
    req: DesignRequest, system: str, usable_area: float, plot_w: float, plot_d: float
) -> ArchitecturalProgram:
    """مسار عام لأي مزوّد متوافق مع OpenAI. مفيش ضمان structured-output زي Anthropic،
    فبنحط شكل الـ JSON صراحة في البرومبت ونتحقق من الرد بعدين بـ Pydantic."""
    client = _openai_client()
    model = _openai_model()
    messages = [
        {"role": "system", "content": system + openai_schema_suffix()},
        {"role": "user", "content": user_prompt(req, usable_area, plot_w, plot_d)},
    ]
    try:
        response = client.chat.completions.create(
            model=model, messages=messages, response_format={"type": "json_object"}
        )
    except Exception:  # noqa: BLE001 — مش كل مزوّد بيدعم response_format
        response = client.chat.completions.create(model=model, messages=messages)

    content = _strip_json_fences((response.choices[0].message.content or "").strip())
    if not content:
        raise PlannerError("الموديل رجّع رد فاضي")
    try:
        return ArchitecturalProgram.model_validate_json(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise PlannerError(f"الموديل رجّع JSON غير صالح: {exc}") from exc


# ---------------------------------------------------------------------------
# نقطة الدخول
# ---------------------------------------------------------------------------


def _fallback_note(req: DesignRequest, reason: str) -> str:
    """رسالة توضّح ليه رجعنا للقواعد — بلغة الطلب عشان تتعرض في التقرير."""
    is_openai = _provider() == "openai"
    key_name = "OPENAI_API_KEY" if is_openai else "ANTHROPIC_API_KEY"

    if req.lang_key == "en":
        provider_label = "The configured AI provider" if is_openai else "Claude"
        if reason == "no_key":
            return (f"No {key_name} found — the programme was generated with "
                    "the built-in rule planner.")
        return (f"{provider_label} was unavailable ({reason}) — the programme was "
                "generated with the built-in rule planner.")

    provider_label_ar = "المزوّد المُعدّ" if is_openai else "الذكاء الاصطناعي"
    if reason == "no_key":
        return f"مفيش مفتاح {key_name} — اتولّد البرنامج بالقواعد الهندسية المدمجة."
    return f"تعذّر استخدام {provider_label_ar} ({reason}) — اتولّد البرنامج بالقواعد المدمجة."


def build_program(
    req: DesignRequest,
    usable_area: float,
    plot_w: float,
    plot_d: float,
) -> tuple[ArchitecturalProgram, Optional[str]]:
    """يرجّع (البرنامج، رسالة تحذير لو رجعنا للقواعد)."""
    if not req.use_ai:
        return rules.build_program(req), None
    if not credentials_available():
        return rules.build_program(req), _fallback_note(req, "no_key")

    prof = profile(req.building_type)
    system = (
        SYSTEM.replace("{hub_share}", f"{prof.circulation_share:.0%}")
        .replace("{notes_language}",
                 "English" if req.lang_key == "en" else "Egyptian Arabic")
    )

    try:
        if _provider() == "openai":
            program = _build_program_openai(req, system, usable_area, plot_w, plot_d)
        else:
            program = _build_program_anthropic(req, system, usable_area, plot_w, plot_d)
        program.source = "ai"
        return sanitise(program, req), None

    except Exception as exc:  # noqa: BLE001 — أي فشل يرجّعنا للقواعد
        log.warning("فشل التخطيط بالـ AI (%s) — الرجوع للمُخطِّط القواعدي", exc)
        return rules.build_program(req), _fallback_note(req, type(exc).__name__)
