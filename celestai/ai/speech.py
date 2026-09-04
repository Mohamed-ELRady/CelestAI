"""الوصف بالصوت — ب-3 · Voice brief.

كتابة وصف طويل بالعربي على الموبايل بطيئة ومرهقة، والمستخدم المستهدف بيتكلم
مصري عامي بطلاقة أكتر ما بيكتب.

بيدعم مزوّدين متوافقين مع OpenAI للـ transcription (Whisper وغيره) — بما فيهم
المجاني زي Groq. بيتفعّل بمتغيّر بيئة، وبيفضل مغلق لو مش متضبّط.

مفيش تحويل صوت → مخطط مباشر: الصوت بيتحوّل نص، والنص بيروح `brief` زي ما هو،
وباقي المسار من غير أي تغيير. كده الميزة مبتضيفش سطح فشل جديد على التصميم.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from . import settings

log = logging.getLogger("celestai.ai.speech")

#: صيغ صوت مقبولة
ALLOWED_AUDIO = {
    "audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4",
    "audio/wav", "audio/x-wav", "audio/m4a",
}
MAX_AUDIO_BYTES = 20 * 1024 * 1024
EXT_BY_MEDIA = {
    "audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3",
    "audio/mp4": "mp4", "audio/wav": "wav", "audio/x-wav": "wav",
    "audio/m4a": "m4a",
}


class SpeechUnavailable(RuntimeError):
    pass


@dataclass
class Transcript:
    text: str
    language: str = ""
    provider: str = ""


def _stt_model() -> str:
    return os.environ.get("CELESTAI_STT_MODEL", "").strip()


def stt_available() -> bool:
    """الصوت متاح؟ محتاج موديل محدّد + مفتاح متوافق مع OpenAI."""
    config = settings.current()
    return bool(_stt_model()) and config.adapter == "openai" and bool(config.api_key)


def transcribe(
    audio: bytes, media_type: str = "audio/webm", language: str = "ar"
) -> Transcript:
    """يحوّل الصوت لنص. بيرمي SpeechUnavailable لو مش متضبّط."""
    if not stt_available():
        raise SpeechUnavailable(
            "التفريغ الصوتي محتاج CELESTAI_STT_MODEL و OPENAI_API_KEY"
        )
    if media_type not in ALLOWED_AUDIO:
        raise SpeechUnavailable(f"صيغة صوت غير مدعومة: {media_type}")
    if len(audio) > MAX_AUDIO_BYTES:
        raise SpeechUnavailable("الملف الصوتي أكبر من 20 ميجابايت")

    try:
        import openai
    except ImportError as exc:  # pragma: no cover
        raise SpeechUnavailable("مكتبة openai غير مثبّتة") from exc

    config = settings.current()
    base_url = os.environ.get("CELESTAI_STT_BASE_URL", "").strip() or \
        config.base_url or None
    client = openai.OpenAI(api_key=config.api_key, base_url=base_url)

    ext = EXT_BY_MEDIA.get(media_type, "webm")
    try:
        response = client.audio.transcriptions.create(
            model=_stt_model(),
            file=(f"brief.{ext}", audio, media_type),
            language=language if language in ("ar", "en") else None,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("فشل التفريغ الصوتي: %s", exc)
        raise SpeechUnavailable(f"{type(exc).__name__}: {exc}") from exc

    text = (getattr(response, "text", "") or "").strip()
    if not text:
        raise SpeechUnavailable("التفريغ رجّع نص فاضي")
    return Transcript(text=text, language=language, provider=_stt_model())


# ---------------------------------------------------------------------------
# تنظيف نص الوصف
# ---------------------------------------------------------------------------

_FILLERS_AR = ("يعني", "أمم", "امم", "اه ", "آه ", "طب ", "يلا ")


def tidy_brief(text: str) -> str:
    """تنظيف خفيف للنص المفرّغ — بدون AI، عشان ميغيّرش المعنى.

    الكلام المنطوق فيه تكرار وحشو. بنشيل الحشو الواضح بس ونسيب الباقي —
    الموديل اللي هيقرا الوصف أقدر على فهم الكلام الطبيعي من أي تنظيف آلي.
    """
    cleaned = " ".join(text.split())
    for f in _FILLERS_AR:
        cleaned = cleaned.replace(f" {f}", " ")
    # شيل الحشو بيسيب مسافات مزدوجة — نلمّها تاني
    return " ".join(cleaned.split())
