"""ذاكرة أسلوب المصمّم — ز-1 · Designer style memory.

المعماري اللي استخدم الأداة 50 مرة بيعيد كتابة تفضيلاته كل مرة: «المطبخ مفتوح»،
«مش عايز حمام داخلي»، «الصالة أكبر حاجة».

الملف ده بيتعلّم التفضيلات دي من **التعديلات اللي عملها فعلًا** — مش من كلامه —
وبيحقنها في البرومبت المرة الجاية.

**شرط أساسي: الذاكرة ظاهرة وقابلة للتعديل والحذف.** مش صندوق أسود بيغيّر
التصميم من ورا المستخدم. أي تفضيل متخزَّن بيتعرض في الواجهة، ومعاه الدليل اللي
اتعلمنا منه، وزرار حذف.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .client import AIUnavailable, ask
from .schemas import StyleProfile, StylePreference

log = logging.getLogger("celestai.ai.style")

MAX_PREFERENCES = 12
MIN_SIGNALS = 3          # مش بنستنتج أسلوب من تعديل أو اتنين


def _profile_path() -> Path:
    """مكان ملف التفضيلات. بيتظبط بـ CELESTAI_STYLE_DIR."""
    base = os.environ.get("CELESTAI_STYLE_DIR", "").strip()
    root = Path(base) if base else Path.home() / ".config" / "celestai"
    return root / "style.json"


@dataclass
class StyleMemory:
    """تفضيلات مستخدم واحد + الإشارات اللي لسه ما اتعلّمناش منها."""

    preferences: list[StylePreference] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    enabled: bool = True

    # -- التخزين -----------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "StyleMemory":
        p = path or _profile_path()
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.info("ملف الأسلوب مش مقروء (%s) — هنبدأ من فاضي", exc)
            return cls()
        return cls(
            preferences=[StylePreference(**d) for d in data.get("preferences", [])],
            signals=list(data.get("signals", [])),
            enabled=bool(data.get("enabled", True)),
        )

    def save(self, path: Path | None = None) -> str:
        p = path or _profile_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "preferences": [pref.model_dump() for pref in self.preferences],
            "signals": self.signals[-40:],
            "enabled": self.enabled,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(p)

    # -- التعلّم -----------------------------------------------------------

    def record(self, signal: str) -> None:
        """يسجّل إشارة خام: تعديل عمله المستخدم، أو طلب رفضه."""
        text = signal.strip()
        if text:
            self.signals.append(text)

    def record_session(self, session) -> int:
        """يستخرج الإشارات من جلسة حوار كاملة."""
        added = 0
        for turn in session.history:
            if turn.role == "user":
                self.record(f"asked: {turn.text}")
                added += 1
            elif turn.applied:
                self.record("applied: " + " · ".join(turn.applied))
                added += 1
        return added

    def forget(self, key: str) -> bool:
        before = len(self.preferences)
        self.preferences = [p for p in self.preferences if p.key != key]
        return len(self.preferences) < before

    def clear(self) -> None:
        self.preferences.clear()
        self.signals.clear()

    # -- الحقن في البرومبت -------------------------------------------------

    def prompt_block(self, language: str = "ar") -> str:
        """نص يتحط في البرومبت. فاضي لو الذاكرة مقفولة أو مفيهاش حاجة."""
        if not self.enabled or not self.preferences:
            return ""
        lines = [
            "\n## This designer's known preferences",
            "Learned from their previous edits. Honour them WHERE THEY DO NOT "
            "CONFLICT with the current brief or the building code — the brief in "
            "front of you always wins.",
        ]
        for p in self.preferences:
            lines.append(f"- ({p.confidence}) {p.statement_en or p.statement_ar}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "preferences": [
                {
                    "key": p.key,
                    "statement_ar": p.statement_ar,
                    "statement_en": p.statement_en,
                    "confidence": p.confidence,
                    "evidence": p.evidence,
                }
                for p in self.preferences
            ],
            "pending_signals": len(self.signals),
        }


# ---------------------------------------------------------------------------
# استخلاص التفضيلات
# ---------------------------------------------------------------------------

SYSTEM = """You are inferring a designer's persistent preferences from the edits they \
actually made to floor plans in CelestAI — not from what they said they like.

Rules:
1. Infer only PATTERNS, not one-offs. A preference needs at least three consistent \
signals across different sessions. One request to enlarge one kitchen is not \
"prefers large kitchens".
2. Preferences must be actionable when planning a NEW project: "prefers an open \
kitchen connected to the dining area", "consistently rejects internal bathrooms \
without a window", "allocates more area to the living room than to bedrooms".
3. Do NOT infer anything about the person — not their family, income, taste in \
decoration, or anything personal. Design preferences only.
4. `evidence` must quote the actual signals the inference rests on.
5. Set `confidence` honestly. `high` needs a strong, repeated, unambiguous pattern.
6. If the signals do not support any real pattern, return an empty list. An empty \
profile is correct and normal — a fabricated one silently distorts every future plan.
7. `statement_ar` in natural Egyptian Arabic."""


def learn(memory: StyleMemory, existing_only: bool = False) -> StyleMemory:
    """يحدّث التفضيلات من الإشارات المتراكمة.

    بيرجّع نفس الكائن. لو الـ AI مش متاح، الذاكرة بتفضل زي ما هي.
    """
    if existing_only or len(memory.signals) < MIN_SIGNALS:
        return memory

    current = "\n".join(
        f"- [{p.key}] {p.statement_en or p.statement_ar} ({p.confidence})"
        for p in memory.preferences
    ) or "(none yet)"

    try:
        profile = ask(
            SYSTEM,
            f"## Preferences already recorded\n{current}\n\n"
            f"## New signals from recent sessions\n"
            + "\n".join(f"- {s}" for s in memory.signals[-40:])
            + "\n\nReturn the FULL updated preference list (keep the still-valid "
              "existing ones, drop any the new signals contradict).",
            StyleProfile, task="style", max_tokens=6000,
        )
    except AIUnavailable as exc:
        log.info("تعلّم الأسلوب مش متاح: %s", exc)
        return memory

    memory.preferences = profile.preferences[:MAX_PREFERENCES]
    memory.signals.clear()
    return memory


def style_markdown(memory: StyleMemory, language: str = "ar") -> str:
    ar = language != "en"
    if not memory.preferences:
        return (
            "مفيش تفضيلات متعلّمة لسه.\n" if ar
            else "No preferences learned yet.\n"
        )
    p = ["## أسلوبك المتعلَّم\n" if ar else "## Your learned style\n"]
    p.append(
        "\nاتعلمناها من تعديلاتك، مش من كلامك. تقدر تحذف أي واحدة.\n" if ar
        else "\nLearned from your edits, not your words. You can delete any of them.\n"
    )
    for pref in memory.preferences:
        text = pref.statement_ar if ar else (pref.statement_en or pref.statement_ar)
        p.append(f"\n- **{text}** _({pref.confidence})_")
        if pref.evidence:
            p.append(f"\n  - {'الدليل' if ar else 'Evidence'}: {pref.evidence}")
    p.append("\n")
    return "".join(p)
