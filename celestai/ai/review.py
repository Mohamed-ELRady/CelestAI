"""المراجع الكودي الذكي — أ-3 · Explainable code review.

`validate()` بيقول «أقل بُعد 1.51 م أقل من الحد الأدنى 1.55 م». صح تمامًا،
وبرضه المستخدم مش عارف يعمل بيه إيه.

الملف ده بياخد المخالفات + الهندسة، ويرجّع لكل مخالفة: **السبب الجذري**
و**حلول عملية بالأرقام**، وكل حل معاه `ProgramEdit` قابل للتطبيق بضغطة.

المخالفات نفسها بتفضل من المُتحقِّق الحتمي — الـ AI بيفسّر بس، مش بيحكم.
"""

from __future__ import annotations

import logging

from ..models import ArchitecturalProgram, DesignRequest, Layout
from .client import AIUnavailable, ask
from .schemas import ReviewAdvice

log = logging.getLogger("celestai.ai.review")

SYSTEM = """You are the code-review explainer inside CelestAI. A deterministic \
validator has already judged the plan — you do NOT re-judge it. Every violation you \
are given is a fact. Your job is to explain WHY each one happened and HOW to fix it.

## How the geometry engine works — a fix that ignores this will not work
- A central hub runs perpendicular to the entry façade and splits the plot into two \
strips. Every other room is a bay in one of those strips.
- A bay's WIDTH is the strip width. Strip width is proportional to the total area of \
the rooms in that strip. **So rooms get narrow when too many of them share a strip**, \
not because any single one is too small.
- A bay's DEPTH is its area ÷ strip width.
- A strip facing a party wall gets no windows. A light well can serve a kitchen or \
bathroom there — never a bedroom or living room.

## Rules for your advice
1. Root cause first. "This bathroom is narrow" is not a cause; "four rooms share the \
left strip so it is only 1.5 m wide" is.
2. Give 2–3 fixes per violation, each with REAL NUMBERS and each naming what shrinks \
in exchange. Every fix in a fixed-area plan costs something. Say what.
3. Order fixes cheapest-first.
4. Attach `edits` to each fix so it can be applied with one click. Use room ids \
exactly as given. Areas are m², widths are m.
5. If a violation genuinely cannot be fixed at this area, say so plainly and \
recommend the smallest programme reduction that would work.
6. Never claim a fix is free.
7. Arabic must be natural Egyptian Arabic. Keep it short — this is read next to a drawing."""


def explain_issues(
    layout: Layout,
    program: ArchitecturalProgram,
    req: DesignRequest,
) -> ReviewAdvice | None:
    """يرجّع شرح وحلول للمخالفات، أو None لو الـ AI مش متاح."""
    issues = [i for i in layout.issues if i.severity in ("error", "warning")]
    if not issues:
        return None

    rooms = "\n".join(
        f"  - {r.spec_id} ({r.kind.value}): {r.net_rect.w:.2f} x {r.net_rect.h:.2f} m"
        f" = {r.net_area:.2f} m², window={'yes' if r.has_window else 'NO'}"
        for r in sorted(layout.rooms, key=lambda r: -r.net_area)
    )
    targets = "\n".join(
        f"  - {r.id}: target {r.target_area:.2f} m², min_width {r.min_width:.2f} m"
        for r in program.rooms
    )
    violations = "\n".join(
        f"  - [{i.severity}/{i.code}] room={i.room_id or '-'} :: "
        f"{i.message_en or i.message_ar}"
        for i in issues
    )

    user = (
        f"## Plot\n{layout.plot.w:.2f} m x {layout.plot.h:.2f} m, "
        f"entry from the {layout.entry_side}\n\n"
        f"## Programme targets\n{targets}\n\n"
        f"## Rooms as built\n{rooms}\n\n"
        f"## Violations to explain\n{violations}\n\n"
        "Explain each violation and give applicable fixes."
    )

    try:
        return ask(SYSTEM, user, ReviewAdvice, task="review", max_tokens=10000)
    except AIUnavailable as exc:
        log.info("المراجعة الذكية مش متاحة: %s", exc)
        return None


def advice_markdown(advice: ReviewAdvice, language: str = "ar") -> str:
    """يحوّل الشرح لماركداون للتقرير."""
    ar = language != "en"
    p: list[str] = []
    summary = advice.summary_ar if ar else (advice.summary_en or advice.summary_ar)
    if summary:
        p.append(f"\n{summary}\n")

    for a in advice.advice:
        cause = a.root_cause_ar if ar else (a.root_cause_en or a.root_cause_ar)
        p.append(f"\n**{a.code}** — {a.room_id or '—'}\n\n")
        if cause:
            p.append(f"{'السبب' if ar else 'Cause'}: {cause}\n")
        for f in a.fixes:
            title = f.title_ar if ar else (f.title_en or f.title_ar)
            detail = f.detail_ar if ar else (f.detail_en or f.detail_ar)
            cost = f.trade_off_ar if ar else (f.trade_off_en or f.trade_off_ar)
            p.append(f"\n- **{title}**")
            if detail:
                p.append(f"\n  - {detail}")
            if cost:
                p.append(f"\n  - {'الثمن' if ar else 'Trade-off'}: {cost}")
            p.append("\n")
    return "".join(p)
