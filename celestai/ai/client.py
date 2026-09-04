"""عميل موحّد لكل استدعاءات الـ AI — one door for every provider.

بيدعم:
  • Anthropic (Claude) — `messages.parse` بيضمن الـ structured output.
  • أي مزوّد متوافق مع OpenAI — Groq، OpenRouter، Together، Ollama محلي…
    مفيش ضمان structured output، فبنحط الـ schema في البرومبت ونتحقق بـ Pydantic.

وكمان بيسجّل **تليمتري الجودة** (فكرة و-3): كام استدعاء نجح، كام فشل، وكام
مرة الرد احتاج تصحيح. ده بيخلّي المستخدم يشوف الفرق بين المزوّدين بالأرقام
بدل ما يخمّن.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from . import settings

log = logging.getLogger("celestai.ai")

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16000


class AIUnavailable(RuntimeError):
    """مفيش مفتاح، أو المزوّد فشل — المُنادي لازم يتصرّف من غير AI."""


# ---------------------------------------------------------------------------
# اختيار المزوّد
# ---------------------------------------------------------------------------

def provider() -> str:
    """Return the active adapter: ``anthropic``, ``openai``, or ``none``."""
    return settings.current().adapter


def _anthropic_ready() -> bool:
    if settings.current().api_key:
        return True
    cfg = os.environ.get("ANTHROPIC_CONFIG_DIR") or os.path.expanduser(
        "~/.config/anthropic"
    )
    return os.path.isdir(os.path.join(cfg, "credentials"))


def _openai_ready() -> bool:
    return bool(settings.current().api_key)


def credentials_available() -> bool:
    if provider() == "openai":
        return _openai_ready()
    if provider() == "anthropic":
        return _anthropic_ready()
    return False


def active_provider_label() -> Optional[str]:
    if not credentials_available():
        return None
    return provider()


def supports_vision() -> bool:
    """الرؤية متاحة على Anthropic دايمًا؛ على OpenAI-compatible حسب الموديل."""
    if not credentials_available():
        return False
    if provider() == "anthropic":
        return True
    return settings.current().vision


# ---------------------------------------------------------------------------
# التليمتري — و-3
# ---------------------------------------------------------------------------


@dataclass
class ProviderStats:
    calls: int = 0
    failures: int = 0
    repairs: int = 0          # ردود احتاجت تصحيح (JSON مكسور، حقول ناقصة…)
    total_seconds: float = 0.0
    tasks: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        ok = self.calls - self.failures
        return {
            "calls": self.calls,
            "ok": ok,
            "failures": self.failures,
            "repairs": self.repairs,
            "failure_rate": round(self.failures / self.calls, 3) if self.calls else 0.0,
            "repair_rate": round(self.repairs / self.calls, 3) if self.calls else 0.0,
            "avg_seconds": round(self.total_seconds / self.calls, 2) if self.calls else 0.0,
            "tasks": dict(self.tasks),
        }


class _Telemetry:
    """إحصاءات جودة لكل مزوّد — عشان المستخدم يقارن بالأرقام."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_provider: dict[str, ProviderStats] = {}

    def record(
        self, name: str, task: str, seconds: float, *,
        failed: bool = False, repaired: bool = False,
    ) -> None:
        with self._lock:
            st = self._by_provider.setdefault(name, ProviderStats())
            st.calls += 1
            st.total_seconds += seconds
            st.tasks[task] = st.tasks.get(task, 0) + 1
            if failed:
                st.failures += 1
            if repaired:
                st.repairs += 1

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {k: v.as_dict() for k, v in self._by_provider.items()}

    def reset(self) -> None:
        with self._lock:
            self._by_provider.clear()


telemetry = _Telemetry()


# ---------------------------------------------------------------------------
# العملاء
# ---------------------------------------------------------------------------


def _anthropic_client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise AIUnavailable("مكتبة anthropic غير مثبّتة") from exc
    key = settings.current().api_key
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def _openai_client():
    try:
        import openai
    except ImportError as exc:  # pragma: no cover
        raise AIUnavailable("مكتبة openai غير مثبّتة") from exc
    config = settings.current()
    return openai.OpenAI(api_key=config.api_key, base_url=config.base_url or None)


def _openai_model() -> str:
    model = settings.current().model.strip()
    if not model:
        raise AIUnavailable(
            "لازم تحدد CELESTAI_AI_MODEL عند استخدام مزوّد متوافق مع OpenAI"
        )
    return model


# ---------------------------------------------------------------------------
# تنظيف ردود الموديلات الأضعف
# ---------------------------------------------------------------------------


def strip_json_fences(text: str) -> tuple[str, bool]:
    """يشيل ```json وأي نص حوالين الـ JSON. يرجّع (النص، هل احتاج تصحيح)."""
    original = text
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return text, text.strip() != original.strip()


def _schema_suffix(model: Type[BaseModel]) -> str:
    schema = json.dumps(model.model_json_schema(), ensure_ascii=False)
    return (
        "\n\n## Output format (STRICT — overrides any format guidance above)\n"
        "Respond with ONLY one JSON object. No markdown fences, no prose before or "
        "after. It must validate against this JSON Schema:\n"
        f"{schema}\n"
    )


# ---------------------------------------------------------------------------
# الصور
# ---------------------------------------------------------------------------


@dataclass
class Image:
    """صورة مدخلة — بايتات + نوعها."""

    data: bytes
    media_type: str = "image/png"

    @property
    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    @classmethod
    def from_data_url(cls, url: str) -> "Image":
        """يقرأ data:image/png;base64,… زي اللي الواجهة بتبعته."""
        if not url.startswith("data:"):
            raise ValueError("مش data URL")
        header, _, payload = url.partition(",")
        media = header[5:].split(";")[0] or "image/png"
        return cls(data=base64.b64decode(payload), media_type=media)


_ALLOWED_MEDIA = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _anthropic_content(user: str, images: list[Image] | None) -> list[dict]:
    blocks: list[dict] = []
    for img in images or []:
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img.media_type,
                "data": img.b64,
            },
        })
    blocks.append({"type": "text", "text": user})
    return blocks


def _openai_content(user: str, images: list[Image] | None) -> Any:
    if not images:
        return user
    parts: list[dict] = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{i.media_type};base64,{i.b64}"},
        }
        for i in images
    ]
    parts.append({"type": "text", "text": user})
    return parts


def validate_images(images: list[Image] | None) -> list[Image]:
    out: list[Image] = []
    for img in images or []:
        if img.media_type not in _ALLOWED_MEDIA:
            raise ValueError(f"نوع صورة غير مدعوم: {img.media_type}")
        if len(img.data) > MAX_IMAGE_BYTES:
            raise ValueError("الصورة أكبر من 5 ميجابايت")
        out.append(img)
    return out


# ---------------------------------------------------------------------------
# نقطة الدخول
# ---------------------------------------------------------------------------


def ask(
    system: str,
    user: str,
    output_model: Type[T],
    *,
    task: str = "generic",
    images: list[Image] | None = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    effort: str = "high",
) -> T:
    """استدعاء بمخرج مُهيكل. بيرمي AIUnavailable لو مفيش مفتاح أو فشل الاستدعاء.

    كل مُنادي **لازم** يمسك AIUnavailable ويكمّل من غير AI — الأداة لازم تفضل
    شغّالة أوفلاين بالقواعد المدمجة.
    """
    if not credentials_available():
        raise AIUnavailable("مفيش مفتاح API متاح")

    images = validate_images(images)
    name = provider()
    t0 = time.time()
    repaired = False

    try:
        if name == "openai":
            client = _openai_client()
            response = client.chat.completions.create(
                model=_openai_model(),
                messages=[
                    {"role": "system", "content": system + _schema_suffix(output_model)},
                    {"role": "user", "content": _openai_content(user, images)},
                ],
                response_format={"type": "json_object"},
            )
            raw = (response.choices[0].message.content or "").strip()
            if not raw:
                raise AIUnavailable("الموديل رجّع رد فاضي")
            cleaned, repaired = strip_json_fences(raw)
            try:
                parsed = output_model.model_validate_json(cleaned)
            except (ValidationError, json.JSONDecodeError) as exc:
                raise AIUnavailable(f"رد غير صالح: {exc}") from exc
        else:
            client = _anthropic_client()
            response = client.messages.parse(
                model=model or settings.current().model or DEFAULT_MODEL,
                max_tokens=max_tokens,
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                system=[{
                    "type": "text", "text": system,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": _anthropic_content(user, images)}],
                output_format=output_model,
            )
            if response.stop_reason == "refusal":
                raise AIUnavailable("الموديل رفض الطلب")
            parsed = response.parsed_output
            if parsed is None:
                raise AIUnavailable("الموديل مرجّعش مخرج صالح")

        telemetry.record(name, task, time.time() - t0, repaired=repaired)
        return parsed

    except AIUnavailable:
        telemetry.record(name, task, time.time() - t0, failed=True)
        raise
    except Exception as exc:  # noqa: BLE001 — أي فشل مزوّد بيتحوّل لنوعنا
        telemetry.record(name, task, time.time() - t0, failed=True)
        log.warning("فشل استدعاء الـ AI (%s / %s): %s", name, task, exc)
        raise AIUnavailable(f"{type(exc).__name__}: {exc}") from exc


def ask_text(
    system: str,
    user: str,
    *,
    task: str = "generic",
    images: list[Image] | None = None,
    model: str | None = None,
    max_tokens: int = 4000,
) -> str:
    """استدعاء بمخرج نصّي حر — للحاجات اللي مش محتاجة بنية (إجابة سؤال مثلًا)."""
    if not credentials_available():
        raise AIUnavailable("مفيش مفتاح API متاح")

    images = validate_images(images)
    name = provider()
    t0 = time.time()

    try:
        if name == "openai":
            client = _openai_client()
            response = client.chat.completions.create(
                model=_openai_model(),
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": _openai_content(user, images)},
                ],
            )
            out = (response.choices[0].message.content or "").strip()
        else:
            client = _anthropic_client()
            response = client.messages.create(
                model=model or settings.current().model or DEFAULT_MODEL,
                max_tokens=max_tokens,
                system=[{
                    "type": "text", "text": system,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": _anthropic_content(user, images)}],
            )
            out = "".join(
                b.text for b in response.content if getattr(b, "type", "") == "text"
            ).strip()

        if not out:
            raise AIUnavailable("الموديل رجّع رد فاضي")
        telemetry.record(name, task, time.time() - t0)
        return out

    except AIUnavailable:
        telemetry.record(name, task, time.time() - t0, failed=True)
        raise
    except Exception as exc:  # noqa: BLE001
        telemetry.record(name, task, time.time() - t0, failed=True)
        log.warning("فشل استدعاء نصّي (%s / %s): %s", name, task, exc)
        raise AIUnavailable(f"{type(exc).__name__}: {exc}") from exc
