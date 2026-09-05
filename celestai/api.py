"""واجهة HTTP — FastAPI service + static web app."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .knowledge import PROFILES
from .models import BuildingRequest, DesignRequest
from .ai.client import active_provider_label, credentials_available
from .ai.cache import response_cache
from .ai import settings as ai_settings
from .service import (
    generate,
    generate_building,
    generate_options,
    render_floor_svg,
    render_layout_svg,
)
from .session import sessions

WEB_DIR = Path(__file__).parent / "web"
JOBS_ROOT = Path(tempfile.gettempdir()) / "celestai-jobs"
JOBS_ROOT.mkdir(exist_ok=True)

app = FastAPI(
    title="CelestAI",
    version=__version__,
    description="من مساحة إلى مخطط هندسي — area in, architectural floor plan out.",
)

_JOBS: dict[str, dict[str, str]] = {}
MAX_JOBS = 40


# ---------------------------------------------------------------------------
# نماذج الاستجابة
# ---------------------------------------------------------------------------


class IssueOut(BaseModel):
    severity: str
    code: str
    message: str
    room_id: str = ""


class DesignResponse(BaseModel):
    job_id: str
    svg: str
    alternatives: list[str]
    report_md: str
    model3d: dict[str, Any]
    metrics: dict[str, float]
    issues: list[IssueOut]
    program: dict[str, Any]
    downloads: dict[str, str]
    ai_used: bool
    #: معرّف الجلسة — لازم للحوار والتراجع (أ-2)
    session_id: str = ""
    #: مخرجات الطبقات التحليلية، فاضية لو مطلبتهاش
    boq: dict[str, Any] = {}
    solar: dict[str, Any] = {}
    review: dict[str, Any] = {}
    finishes: dict[str, Any] = {}
    furniture: dict[str, Any] = {}
    options: dict[str, Any] = {}
    rationale: list[dict[str, Any]] = []


class DesignOptions(BaseModel):
    """الأعلام الاختيارية للتوليد — كلها مقفولة افتراضيًا."""

    repair: bool = False              # أ-1 الإصلاح الذاتي
    explain: bool = False             # أ-3 شرح المخالفات
    solar_city: str = ""              # د-2 التحليل الشمسي
    finishes_tier: str = ""           # د-3 المواصفات
    furnish: bool = False             # د-4 الفرش
    intent_options: int = 0           # أ-4 بدائل بالنيّة (0 = مقفول)
    prices_path: str = ""             # د-1 جدول أسعار


class DesignEnvelope(BaseModel):
    request: DesignRequest
    options: DesignOptions = DesignOptions()


# ---------------------------------------------------------------------------
# نقاط النهاية
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    from .ai.client import supports_vision
    from .ai.speech import stt_available

    available = credentials_available()
    config = ai_settings.current()
    preset = ai_settings.PROVIDERS.get(config.provider_id)
    return {
        "status": "ok",
        "version": __version__,
        "ai_available": available,
        "ai_provider": active_provider_label(),  # "anthropic" | "openai" | None
        "ai_provider_id": config.provider_id,
        "ai_provider_name": preset.name_en if preset else "Offline",
        "ai_provider_name_ar": preset.name_ar if preset else "بدون AI",
        "ai_provider_name_en": preset.name_en if preset else "Offline",
        "ai_model": config.model or None,
        "ai_config_source": config.source,
        # قدرات الواجهة بتتحكم بيها: مبنعرضش زرار لحاجة مش شغالة
        "features": {
            "chat": available,          # أ-2
            "repair": available,        # أ-1
            "explain": available,       # أ-3
            "options": available,       # أ-4
            "vision": supports_vision(),  # ب-1 · ب-2
            "voice": stt_available(),   # ب-3
            "finishes": available,      # د-3
            "furnish": available,       # د-4
            "code_qa": available,       # ج-2
            "boq": True,                # د-1 — حتمي، شغال دايمًا
            "solar": True,              # د-2 — حتمي، شغال دايمًا
            "feasibility": True,        # هـ-1 — البحث حتمي
        },
    }


# ---------------------------------------------------------------------------
# إعدادات مزوّد الذكاء الاصطناعي — BYOK من داخل الواجهة
# ---------------------------------------------------------------------------


class AISettingsIn(BaseModel):
    provider_id: str
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    vision: bool | None = None
    remember: bool = False


def _settings_values(payload: AISettingsIn) -> dict[str, Any]:
    return {
        "provider_id": payload.provider_id,
        "api_key": payload.api_key,
        "model": payload.model,
        "base_url": payload.base_url,
        "vision": payload.vision,
        "remember": payload.remember,
    }


@app.get("/api/ai/settings")
def get_ai_settings() -> dict[str, Any]:
    """إعدادات آمنة للعرض — مفتاح الـ API نفسه لا يخرج من الخادم أبدًا."""
    state = ai_settings.public_state()
    state["ai_available"] = credentials_available()
    state["savings"] = response_cache.snapshot()
    return state


@app.post("/api/ai/settings")
def save_ai_settings(payload: AISettingsIn) -> dict[str, Any]:
    try:
        ai_settings.configure(**_settings_values(payload))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state = ai_settings.public_state()
    state["ai_available"] = credentials_available()
    state["savings"] = response_cache.snapshot()
    return state


@app.delete("/api/ai/settings")
def disconnect_ai() -> dict[str, Any]:
    ai_settings.disconnect(forget_saved=True)
    response_cache.clear()
    state = ai_settings.public_state()
    state["ai_available"] = False
    state["savings"] = response_cache.snapshot()
    return state


@app.post("/api/ai/settings/test")
def test_ai_settings(payload: AISettingsIn) -> dict[str, Any]:
    """اختبار قراءة قائمة النماذج بدون إرسال brief أو توليد مدفوع."""
    config = None
    try:
        config = ai_settings.preview(**_settings_values(payload))
        if config.adapter == "anthropic":
            import anthropic

            page = anthropic.Anthropic(api_key=config.api_key).models.list(limit=30)
            models = [item.id for item in page.data]
        elif config.adapter == "openai":
            import openai

            page = openai.OpenAI(
                api_key=config.api_key, base_url=config.base_url or None,
            ).models.list()
            models = [item.id for item in page.data[:80]]
        else:
            return {"ok": True, "models": [], "model_found": False}
    except Exception as exc:  # noqa: BLE001 — خطأ المزوّد لازم يرجع مفهوم للواجهة
        detail = str(exc)
        secrets = [payload.api_key.strip()]
        if config is not None:
            secrets.append(config.api_key)
        for secret in secrets:
            if secret:
                detail = detail.replace(secret, "[redacted]")
        raise HTTPException(
            status_code=422,
            detail=f"تعذّر الاتصال بالمزوّد: {type(exc).__name__}: {detail[:500]}",
        ) from exc
    return {
        "ok": True,
        "models": models,
        "model_found": config.model in models,
    }


@app.get("/api/building-types")
def building_types() -> list[dict]:
    return [
        {
            "value": bt.value,
            "label_ar": p.label_ar,
            "label_en": p.label_en,
            "hub_ar": p.hub_kind.value,
        }
        for bt, p in PROFILES.items()
    ]


def _prune_jobs() -> None:
    """يمسح أقدم المهام عشان المجلد المؤقت ما يكبرش بلا حدود."""
    while len(_JOBS) > MAX_JOBS:
        oldest = next(iter(_JOBS))
        _JOBS.pop(oldest, None)
        shutil.rmtree(JOBS_ROOT / oldest, ignore_errors=True)


def _issues_out(result, lang: str) -> list[IssueOut]:
    return [
        IssueOut(
            severity=i.severity,
            code=i.code,
            message=i.message_ar if lang == "ar" else i.message_en,
            room_id=i.room_id,
        )
        for i in result.layout.issues
    ]


def _design_response(result, req: DesignRequest, job_id: str,
                     session_id: str = "") -> DesignResponse:
    return DesignResponse(
        job_id=job_id,
        session_id=session_id,
        svg=render_layout_svg(result.layout, req),
        alternatives=[
            render_layout_svg(
                alt, req,
                title=(f"Option {i + 1}" if req.language == "en" else f"بديل {i + 1}"),
            )
            for i, alt in enumerate(result.alternatives)
        ],
        report_md=result.report_md,
        model3d=result.model3d,
        metrics=result.layout.metrics,
        issues=_issues_out(result, req.language),
        program=result.program.model_dump(mode="json"),
        downloads={
            fmt: f"/api/download/{job_id}/{fmt}"
            for fmt in result.files
            if not fmt.startswith("alt")
        },
        ai_used=result.program.source == "ai",
        boq=result.boq,
        solar=result.solar,
        review=result.review,
        finishes=result.finishes,
        furniture=result.furniture,
        options=result.options,
        rationale=result.rationale,
    )


@app.post("/api/design", response_model=DesignResponse)
def design(payload: DesignRequest | DesignEnvelope) -> DesignResponse:
    """التوليد. بيقبل `DesignRequest` لوحده (زي الأول) أو مغلّف بأعلام التحليل."""
    if isinstance(payload, DesignEnvelope):
        req, opts = payload.request, payload.options
    else:
        req, opts = payload, DesignOptions()

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_ROOT / job_id

    prices = None
    if opts.prices_path:
        from .analysis.quantities import PriceBook

        try:
            prices = PriceBook.load(opts.prices_path)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail=f"جدول أسعار غير صالح: {exc}"
            ) from exc

    from .rationale import RationaleLog

    log = RationaleLog()
    try:
        if opts.intent_options >= 2:
            result = generate_options(
                req, out_dir=job_dir, count=opts.intent_options, repair=opts.repair
            )
        else:
            result = generate(
                req, out_dir=job_dir,
                repair=opts.repair,
                explain=opts.explain,
                solar_city=opts.solar_city,
                prices=prices,
                finishes_tier=opts.finishes_tier,
                furnish=opts.furnish,
                rationale=log,
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"فشل التوليد: {exc}") from exc

    _JOBS[job_id] = result.files
    _prune_jobs()

    session = sessions.create(req, result, log)
    return _design_response(result, req, job_id, session.session_id)


# ---------------------------------------------------------------------------
# أ-2 · الحوار التصميمي
# ---------------------------------------------------------------------------


class ChatIn(BaseModel):
    session_id: str
    message: str


class ChatOut(BaseModel):
    ok: bool
    reply: str
    applied: list[str] = []
    rejected: list[str] = []
    changed: bool = False
    svg: str = ""
    metrics: dict[str, float] = {}
    issues: list[IssueOut] = []
    can_undo: bool = False
    can_redo: bool = False


def _chat_state(session, payload: dict) -> ChatOut:
    req = session.request
    return ChatOut(
        ok=payload.get("ok", True),
        reply=payload.get("reply", ""),
        applied=payload.get("applied", []),
        rejected=payload.get("rejected", []),
        changed=payload.get("changed", False),
        svg=render_layout_svg(session.layout, req) if payload.get("changed") else "",
        metrics=session.layout.metrics,
        issues=_issues_out(session.result, req.language),
        can_undo=bool(session.undo_stack),
        can_redo=bool(session.redo_stack),
    )


@app.post("/api/chat", response_model=ChatOut)
def chat(payload: ChatIn) -> ChatOut:
    """تعديل المخطط بالكلام. المخطط مبيتغيّرش غير لو التعديل نجح فعلًا."""
    session = sessions.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="الجلسة انتهت — ابدأ تصميم جديد")
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="الرسالة فاضية")

    from .ai.chat import apply_message

    return _chat_state(session, apply_message(session, payload.message))


@app.post("/api/chat/undo", response_model=ChatOut)
def chat_undo(payload: ChatIn) -> ChatOut:
    session = sessions.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="الجلسة انتهت")
    ok = session.undo()
    ar = session.request.lang_key != "en"
    return _chat_state(session, {
        "ok": ok, "changed": ok,
        "reply": ("رجّعت خطوة." if ok else "مفيش حاجة أرجعها.") if ar
                 else ("Undone." if ok else "Nothing to undo."),
    })


@app.post("/api/chat/redo", response_model=ChatOut)
def chat_redo(payload: ChatIn) -> ChatOut:
    session = sessions.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="الجلسة انتهت")
    ok = session.redo()
    ar = session.request.lang_key != "en"
    return _chat_state(session, {
        "ok": ok, "changed": ok,
        "reply": ("رجّعت التعديل." if ok else "مفيش حاجة أعيدها.") if ar
                 else ("Redone." if ok else "Nothing to redo."),
    })


class FloorOut(BaseModel):
    level: int
    use: str
    label: str
    svg: str
    units: int
    metrics: dict[str, float]
    issues: list[IssueOut]


class BuildingResponse(BaseModel):
    job_id: str
    floors: list[FloorOut]
    report_md: str
    model3d: dict[str, Any]
    metrics: dict[str, float]
    downloads: dict[str, str]


@app.get("/api/floor-uses")
def floor_uses() -> list[dict]:
    from .knowledge import unit_standard
    from .models import FloorUse

    out = []
    for use in FloorUse:
        st = unit_standard(use.value)
        out.append({
            "value": use.value,
            "label_ar": st.label_ar,
            "label_en": st.label_en,
            "unit_ar": st.name_ar,
            "unit_en": st.name_en,
            "ideal_area": st.ideal_area if st.ideal_area < 1e8 else None,
        })
    return out


@app.post("/api/building", response_model=BuildingResponse)
def building(req: BuildingRequest) -> BuildingResponse:
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_ROOT / job_id

    try:
        result = generate_building(req, out_dir=job_dir)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"فشل التوليد: {exc}") from exc

    _JOBS[job_id] = result.files
    _prune_jobs()

    ar = req.lang_key == "ar"
    floors = [
        FloorOut(
            level=f.level,
            use=f.use.value,
            label=f.label_ar if ar else f.label_en,
            svg=render_floor_svg(req, f),
            units=len(f.units),
            metrics=f.metrics,
            issues=[
                IssueOut(
                    severity=i.severity, code=i.code,
                    message=i.message_ar if ar else i.message_en,
                    room_id=i.room_id,
                )
                for i in f.issues
            ],
        )
        for f in result.floors
    ]

    return BuildingResponse(
        job_id=job_id,
        floors=floors,
        report_md=result.report_md,
        model3d=result.model3d,
        metrics=result.metrics,
        downloads={fmt: f"/api/download/{job_id}/{fmt}" for fmt in result.files},
    )


_MEDIA = {
    "svg": ("image/svg+xml", ".svg"),
    "pdf": ("application/pdf", ".pdf"),
    "dxf": ("image/vnd.dxf", ".dxf"),
    "json3d": ("application/json", ".json"),
    "report": ("text/markdown; charset=utf-8", ".md"),
}


@app.get("/api/download/{job_id}/{fmt}")
def download(job_id: str, fmt: str):
    files = _JOBS.get(job_id)
    if not files or fmt not in files:
        raise HTTPException(status_code=404, detail="الملف مش موجود أو انتهت صلاحيته")
    path = Path(files[fmt])
    if not path.exists():
        raise HTTPException(status_code=404, detail="الملف اتمسح")
    base_fmt = fmt.split("_")[0]
    media, _ = _MEDIA.get(base_fmt, ("application/octet-stream", ""))
    return FileResponse(path, media_type=media, filename=path.name)


# ---------------------------------------------------------------------------
# تطبيق الويب
# ---------------------------------------------------------------------------

if (WEB_DIR / "app.js").exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


# ---------------------------------------------------------------------------
# ب-1/ب-2 · المداخل البصرية
# ---------------------------------------------------------------------------


class VisionIn(BaseModel):
    #: صور كـ data URLs من الواجهة
    images: list[str]
    language: str = "ar"


@app.post("/api/read-sketch")
def read_sketch_endpoint(payload: VisionIn) -> dict:
    """يقرأ اسكتش يد. **الناتج للمراجعة، مش بيتطبّق تلقائيًا.**"""
    from .ai.client import Image, supports_vision
    from .ai.vision import read_sketch

    if not supports_vision():
        raise HTTPException(status_code=503, detail="قراءة الصور مش متاحة دلوقتي")
    if not payload.images:
        raise HTTPException(status_code=400, detail="مفيش صور")

    try:
        images = [Image.from_data_url(u) for u in payload.images[:4]]
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"صورة غير صالحة: {exc}") from exc

    reading = read_sketch(images, payload.language)
    if reading is None:
        raise HTTPException(status_code=503, detail="تعذّرت قراءة الاسكتش")
    return {"reading": reading.model_dump(), "needs_confirmation": True}


@app.post("/api/read-site")
def read_site_endpoint(payload: VisionIn) -> dict:
    """يقرأ كروكي أرض أو رخصة. **كل قيمة لازم المستخدم يأكّدها.**"""
    from .ai.client import Image, supports_vision
    from .ai.vision import read_site_document

    if not supports_vision():
        raise HTTPException(status_code=503, detail="قراءة الصور مش متاحة دلوقتي")
    if not payload.images:
        raise HTTPException(status_code=400, detail="مفيش صور")

    try:
        images = [Image.from_data_url(u) for u in payload.images[:4]]
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"صورة غير صالحة: {exc}") from exc

    reading = read_site_document(images, payload.language)
    if reading is None:
        raise HTTPException(status_code=503, detail="تعذّرت قراءة المستند")
    return {"reading": reading.model_dump(), "needs_confirmation": True}


# ---------------------------------------------------------------------------
# ب-3 · الوصف بالصوت
# ---------------------------------------------------------------------------


class VoiceIn(BaseModel):
    audio: str            # data URL
    language: str = "ar"


@app.post("/api/transcribe")
def transcribe_endpoint(payload: VoiceIn) -> dict:
    import base64

    from .ai.speech import SpeechUnavailable, stt_available, tidy_brief, transcribe

    if not stt_available():
        raise HTTPException(
            status_code=503,
            detail="التفريغ الصوتي محتاج CELESTAI_STT_MODEL و OPENAI_API_KEY",
        )
    url = payload.audio
    if not url.startswith("data:"):
        raise HTTPException(status_code=400, detail="مطلوب data URL")

    header, _, b64 = url.partition(",")
    media = header[5:].split(";")[0] or "audio/webm"
    try:
        raw = base64.b64decode(b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="صوت غير صالح") from exc

    try:
        result = transcribe(raw, media, payload.language)
    except SpeechUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"text": tidy_brief(result.text), "provider": result.provider}


# ---------------------------------------------------------------------------
# هـ-1 · دراسة الجدوى
# ---------------------------------------------------------------------------


class FeasibilityIn(BaseModel):
    area: float
    min_floors: int = 2
    max_floors: int = 6
    language: str = "ar"
    brief: str = ""
    prices_path: str = ""
    narrate: bool = True


@app.post("/api/feasibility")
def feasibility_endpoint(payload: FeasibilityIn) -> dict:
    """«عندي أرض كذا — أعمل فيها إيه؟». البحث حتمي؛ السرد اختياري."""
    from .analysis.feasibility import feasibility_markdown, study_feasibility

    if not 40 <= payload.area <= 5000:
        raise HTTPException(status_code=400, detail="مسطح الدور لازم بين 40 و5000 م²")

    prices = None
    if payload.prices_path:
        from .analysis.quantities import PriceBook

        try:
            prices = PriceBook.load(payload.prices_path)
        except (OSError, ValueError):
            prices = None

    try:
        study = study_feasibility(
            payload.area,
            min_floors=max(1, payload.min_floors),
            max_floors=min(payload.max_floors, 20),
            prices=prices,
            language=payload.language,
            brief=payload.brief,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"فشلت الدراسة: {exc}") from exc

    if payload.narrate:
        try:
            from .ai.content import feasibility_advice

            study.advice = feasibility_advice(study, payload.language)
        except Exception:  # noqa: BLE001
            pass

    return {
        "study": study.as_dict(),
        "report_md": feasibility_markdown(study, payload.language),
    }


# ---------------------------------------------------------------------------
# ج-1/ج-2 · الأكواد
# ---------------------------------------------------------------------------


@app.get("/api/codes")
def list_codes() -> list[dict]:
    from .codes import available_codes

    return available_codes()


class CodeQuestion(BaseModel):
    question: str
    code_id: str = "eg"
    language: str = "ar"


@app.post("/api/code-qa")
def code_qa(payload: CodeQuestion) -> dict:
    """سؤال كودي بالمصادر. بيقول صراحةً لو مش واثق."""
    from .codes import ask_code, corpus

    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="السؤال فاضي")

    answer = ask_code(payload.question, payload.code_id, payload.language)
    if answer is None:
        raise HTTPException(status_code=503, detail="مساعد الكود مش متاح")
    return {
        "answer": answer.model_dump(),
        "indexed_clauses": len(corpus),
    }


# ---------------------------------------------------------------------------
# و-3 · تليمتري جودة المزوّدين  ·  ز-1 · ذاكرة الأسلوب
# ---------------------------------------------------------------------------


@app.get("/api/telemetry")
def telemetry_endpoint() -> dict:
    """جودة كل مزوّد بالأرقام — كام استدعاء، كام فشل، كام تصحيح."""
    from .ai.client import telemetry

    return {"providers": telemetry.snapshot(), "savings": response_cache.snapshot()}


@app.get("/api/style")
def get_style() -> dict:
    from .ai.style import StyleMemory

    return StyleMemory.load().as_dict()


class StyleAction(BaseModel):
    action: str            # learn · forget · clear · enable · disable
    key: str = ""
    session_id: str = ""


@app.post("/api/style")
def update_style(payload: StyleAction) -> dict:
    """التفضيلات ظاهرة وقابلة للحذف — مش صندوق أسود."""
    from .ai.style import StyleMemory, learn

    memory = StyleMemory.load()
    action = payload.action

    if action == "forget" and payload.key:
        memory.forget(payload.key)
    elif action == "clear":
        memory.clear()
    elif action in ("enable", "disable"):
        memory.enabled = action == "enable"
    elif action == "learn":
        session = sessions.get(payload.session_id) if payload.session_id else None
        if session is not None:
            memory.record_session(session)
        learn(memory)
    else:
        raise HTTPException(status_code=400, detail=f"إجراء غير معروف: {action}")

    memory.save()
    return memory.as_dict()


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = WEB_DIR / "index.html"
    if not html.exists():
        return HTMLResponse("<h1>CelestAI</h1><p>واجهة الويب مش متثبّتة.</p>")
    return HTMLResponse(html.read_text(encoding="utf-8"))
