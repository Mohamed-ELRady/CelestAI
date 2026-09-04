"""سجل القرارات — و-2 · Design Rationale Log.

المشكلة: المخطط بيطلع من غير ما حد يعرف ليه. ليه نسبة القطعة دي؟ ليه المدخل من
الجهة دي؟ إيه اللي اتشال في التقليم وليه؟ الأداة كانت بتاخد ثقة من غير ما تشرح.

الحل: كل قرار — سواء من الموديل أو من المحرك الحتمي — بيتسجّل مُهيكل هنا،
وبعدين بيتحوّل لـ«دفتر تصميم» مقروء. مفيش AI مطلوب عشان التسجيل نفسه؛ الـ AI
اختياري بس للسرد.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Stage = Literal["program", "plot", "layout", "openings", "repair", "trim",
                "building", "edit", "analysis"]

STAGE_LABELS = {
    "program": ("البرنامج المعماري", "Architectural programme"),
    "plot": ("أبعاد القطعة", "Plot proportions"),
    "layout": ("التوزيع", "Space planning"),
    "openings": ("الفتحات", "Openings"),
    "repair": ("الإصلاح الذاتي", "Self-repair"),
    "trim": ("التقليم", "Programme trimming"),
    "building": ("تركيب المبنى", "Building composition"),
    "edit": ("تعديلات المستخدم", "User edits"),
    "analysis": ("التحليل", "Analysis"),
}


@dataclass
class Decision:
    """قرار واحد: إيه اللي اتقرر، ومين قرره، وليه."""

    stage: Stage
    what_ar: str
    what_en: str = ""
    why_ar: str = ""
    why_en: str = ""
    by: Literal["ai", "engine", "user", "rules"] = "engine"
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "stage": self.stage,
            "by": self.by,
            "what_ar": self.what_ar,
            "what_en": self.what_en,
            "why_ar": self.why_ar,
            "why_en": self.why_en,
            "data": self.data,
        }


class RationaleLog:
    """سجل مرتّب بترتيب حدوث القرارات."""

    def __init__(self) -> None:
        self.decisions: list[Decision] = []

    def add(
        self,
        stage: Stage,
        what_ar: str,
        *,
        what_en: str = "",
        why_ar: str = "",
        why_en: str = "",
        by: str = "engine",
        **data: Any,
    ) -> None:
        self.decisions.append(
            Decision(
                stage=stage, what_ar=what_ar, what_en=what_en,
                why_ar=why_ar, why_en=why_en, by=by,  # type: ignore[arg-type]
                data=data,
            )
        )

    def __len__(self) -> int:
        return len(self.decisions)

    def __bool__(self) -> bool:
        return bool(self.decisions)

    def by_stage(self) -> dict[str, list[Decision]]:
        out: dict[str, list[Decision]] = {}
        for d in self.decisions:
            out.setdefault(d.stage, []).append(d)
        return out

    def as_list(self) -> list[dict]:
        return [d.as_dict() for d in self.decisions]

    # -----------------------------------------------------------------
    # التصدير
    # -----------------------------------------------------------------

    def to_markdown(self, language: str = "ar") -> str:
        """دفتر التصميم — من غير أي استدعاء AI."""
        ar = language != "en"
        p: list[str] = []
        p.append("## دفتر التصميم\n" if ar else "## Design log\n")
        p.append(
            "كل قرار في المخطط ده ومين اتخذه وليه — عشان تقدر تراجعه أو تعترض عليه.\n"
            if ar else
            "Every decision behind this plan, who made it and why — so you can "
            "review it or disagree with it.\n"
        )

        actor = {
            "ai": ("الذكاء الاصطناعي", "AI"),
            "engine": ("المحرك الهندسي", "Engine"),
            "rules": ("القواعد المدمجة", "Rule planner"),
            "user": ("المستخدم", "User"),
        }

        for stage, items in self.by_stage().items():
            label = STAGE_LABELS.get(stage, (stage, stage))
            p.append(f"\n### {label[0] if ar else label[1]}\n")
            for d in items:
                who = actor.get(d.by, ("—", "—"))
                what = d.what_ar if ar else (d.what_en or d.what_ar)
                why = d.why_ar if ar else (d.why_en or d.why_ar)
                p.append(f"- **{what}** — _{who[0] if ar else who[1]}_")
                if why:
                    p.append(f"\n  - {'ليه: ' if ar else 'Why: '}{why}")
                p.append("\n")
        return "".join(p)


# ---------------------------------------------------------------------------
# سرد بالـ AI (اختياري بالكامل)
# ---------------------------------------------------------------------------

_NARRATIVE_SYSTEM = """You are writing the "design log" section of an architectural \
report produced by CelestAI. You are given the raw list of decisions the system made — \
some by an AI programme planner, some by a deterministic geometry engine.

Turn them into a short, honest narrative a client or an examiner can follow. Rules:
- Do NOT invent decisions. Only narrate what is in the list.
- Group related decisions; do not repeat the list mechanically.
- Be plain about trade-offs. If something was dropped, say what was lost.
- Never claim the plan is better than the numbers say.
- Arabic must be natural Egyptian Arabic, not translated-sounding.
"""


def narrate(log: RationaleLog, language: str = "ar") -> str:
    """يحوّل السجل لسرد بالـ AI. بيرجّع النسخة الجاهزة لو الـ AI مش متاح."""
    from .ai.client import AIUnavailable, ask
    from .ai.schemas import RationaleNarrative

    if not log:
        return ""
    try:
        result = ask(
            _NARRATIVE_SYSTEM,
            "Decisions (JSON):\n"
            + str(log.as_list())
            + "\n\nWrite the design log. Use the same section keys as the stages.",
            RationaleNarrative,
            task="rationale",
            max_tokens=4000,
        )
    except AIUnavailable:
        return log.to_markdown(language)

    ar = language != "en"
    intro = result.intro_ar if ar else (result.intro_en or result.intro_ar)
    sections = result.sections_ar if ar else (result.sections_en or result.sections_ar)

    p = ["## دفتر التصميم\n" if ar else "## Design log\n", f"\n{intro}\n"]
    for stage, text in sections.items():
        label = STAGE_LABELS.get(stage, (stage, stage))
        p.append(f"\n### {label[0] if ar else label[1]}\n\n{text}\n")
    return "".join(p)
