"""طبقة الذكاء الاصطناعي — every LLM call in the project goes through here.

الفلسفة اللي المشروع كله مبني عليها: **الموديل بينوي، والهندسة بتنفّذ وتتحقق**.
فكل حاجة في الحزمة دي بترجّع بيانات مُهيكلة بتتحقق بـ Pydantic، والمحرك الحتمي
هو اللي بيحكم على النتيجة في الآخر — مش الموديل.
"""

from .client import (
    AIUnavailable,
    ask,
    ask_text,
    credentials_available,
    active_provider_label,
    telemetry,
)

__all__ = [
    "AIUnavailable",
    "ask",
    "ask_text",
    "credentials_available",
    "active_provider_label",
    "telemetry",
]
