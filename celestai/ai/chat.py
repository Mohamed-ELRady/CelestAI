"""الحوار التصميمي — أ-2 · Conversational design loop.

أكبر فجوة كانت: الأداة **توليد لمرة واحدة**. «الماستر صغير، كبّره على حساب
السفرة» = ابدأ من الأول واخسر كل حاجة.

هنا الموديل بيرجّع **تعديلات** (`ProgramEdit`) مش برنامج جديد. كده:
  • باقي التصميم بيفضل ثابت
  • المستخدم بيشوف اتغيّر إيه بالظبط، وبأرقام قبل/بعد
  • التراجع ممكن

ولو الطلب مستحيل هندسيًا، الموديل بيرفض ويشرح — أحسن من إنه ينفّذ حاجة غلط.
"""

from __future__ import annotations

import logging

from ..models import Layout
from ..session import Session, Turn
from .client import AIUnavailable, ask
from .edits import apply_edits
from .schemas import EditPlan

log = logging.getLogger("celestai.ai.chat")

SYSTEM = """You are the design assistant inside CelestAI. The user is looking at a \
floor plan you produced and wants to change it. You do NOT redraw — you return a list \
of EDITS to the architectural programme, and a deterministic engine re-solves the plan.

## What you can change
resize · add · remove · rename · retype · min_width · attach (en-suite) · detach

## How the geometry engine works — an edit that ignores this will not do what the user wants
- A central hub runs perpendicular to the entry façade and splits the plot into two \
strips. Every other room is a bay in one of those strips.
- A bay's WIDTH is the strip width, and strip width is proportional to the TOTAL area \
of the rooms in that strip. So a room gets wider when its strip gets a bigger share — \
which usually means moving area from the other strip, or having fewer rooms in this one.
- A bay's DEPTH is its area ÷ strip width. Adding area to one room alone mostly makes \
it DEEPER, not wider.
- The plot area is FIXED. Every square metre you give one room is taken from another. \
Always take it from a specific named room — never leave it implicit.

## Rules
1. Do the smallest set of edits that satisfies the request. Do not redesign.
2. If the user says "bigger" without a number, use a sensible step (about 15–25%) and \
say what you took it from.
3. If the request would break the code (a room under its minimum, dropping the last \
bathroom or kitchen, removing the hub), REFUSE in `refused_*` and explain why. Do not \
half-do it.
4. If the request is ambiguous, pick the most likely reading, state it in \
`understood_*`, and proceed. Do not ask a question back.
5. `reason_ar` on each edit: one short clause in Egyptian Arabic.
6. `understood_*`: one sentence, what you are about to do and what it costs.
7. Use room ids EXACTLY as given."""


def _describe(layout: Layout) -> str:
    lines = []
    for r in sorted(layout.rooms, key=lambda r: -r.net_area):
        n = r.net_rect
        lines.append(
            f"  - {r.spec_id} ({r.kind.value}) \"{r.name_en or r.name_ar}\": "
            f"{n.w:.2f} x {n.h:.2f} m = {n.area:.2f} m²"
            + ("" if r.has_window else ", NO WINDOW")
        )
    return "\n".join(lines)


def plan_edits(session: Session, message: str) -> EditPlan | None:
    """يحوّل رسالة المستخدم لتعديلات. None لو الـ AI مش متاح."""
    layout = session.layout
    program = session.program

    targets = "\n".join(
        f"  - {r.id}: {r.kind.value}, target {r.target_area:.2f} m², "
        f"min_width {r.min_width:.2f} m"
        + (f", en-suite of {r.attach_to}" if r.attach_to else "")
        for r in program.rooms
    )
    issues = "\n".join(
        f"  - [{i.severity}] {i.message_en or i.message_ar}"
        for i in layout.issues[:8]
    ) or "  (none)"

    history = session.transcript()
    user = (
        f"## Plot\n{layout.plot.w:.2f} x {layout.plot.h:.2f} m, "
        f"entry from the {layout.entry_side}. "
        f"Total area is fixed at {layout.plot.area:.2f} m².\n\n"
        f"## Programme\n{targets}\n\n"
        f"## Plan as built\n{_describe(layout)}\n\n"
        f"## Current code issues\n{issues}\n\n"
        + (f"## Conversation so far\n{history}\n\n" if history else "")
        + f"## The user now says\n{message.strip()}\n\n"
        "Return the edits."
    )

    try:
        return ask(SYSTEM, user, EditPlan, task="chat", max_tokens=8000)
    except AIUnavailable as exc:
        log.info("الحوار مش متاح: %s", exc)
        return None


def apply_message(session: Session, message: str) -> dict:
    """المسار الكامل لدورة حوار: افهم → عدّل → أعد الحل → قارن.

    بيرجّع dict جاهز للـ API. المخطط مبيتغيّرش غير لو التعديل نجح فعلًا.
    """
    ar = session.request.lang_key != "en"
    session.add_turn(Turn(role="user", text=message))

    plan = plan_edits(session, message)
    if plan is None:
        reply = (
            "الحوار محتاج مفتاح AI. حط ANTHROPIC_API_KEY (أو مزوّد متوافق مع "
            "OpenAI) وجرّب تاني."
            if ar else
            "The design chat needs an AI key. Set ANTHROPIC_API_KEY (or an "
            "OpenAI-compatible provider) and try again."
        )
        session.add_turn(Turn(role="assistant", text=reply))
        return {"ok": False, "reply": reply, "applied": [], "rejected": [],
                "changed": False}

    refused = plan.refused_ar if ar else (plan.refused_en or plan.refused_ar)
    if refused and not plan.edits:
        session.add_turn(Turn(role="assistant", text=refused))
        return {"ok": True, "reply": refused, "applied": [], "rejected": [],
                "changed": False}

    understood = plan.understood_ar if ar else (
        plan.understood_en or plan.understood_ar
    )

    before = dict(session.layout.metrics)
    snap = session.snapshot(label_ar=message[:60], label_en=message[:60])

    outcome = apply_edits(
        session.program, plan.edits, language=session.request.language
    )
    if not outcome.changed:
        reply = refused or (
            "مقدرتش أنفّذ الطلب ده: " + " · ".join(outcome.rejected)
            if outcome.rejected else
            ("مفيش تعديل اتطبّق." if ar else "No edit was applied.")
        )
        session.add_turn(Turn(role="assistant", text=reply,
                              rejected=outcome.rejected))
        return {"ok": True, "reply": reply, "applied": [],
                "rejected": outcome.rejected, "changed": False}

    # نعيد الحل بالبرنامج المعدّل
    from ..engine.solver import solve
    from ..planner.rules import normalise_program

    try:
        program = normalise_program(outcome.program, session.layout.plot.area)
        layouts = solve(program, session.request, session.layout.plot)
    except Exception as exc:  # noqa: BLE001
        log.info("فشل حل البرنامج المعدّل: %s", exc)
        layouts = []

    if not layouts:
        reply = (
            "التعديل ده المحرك مش قادر يطلّع منه مخطط سليم — رجّعت المخطط زي ما كان."
            if ar else
            "The engine could not produce a valid plan from that edit — the previous "
            "plan was kept."
        )
        session.add_turn(Turn(role="assistant", text=reply))
        return {"ok": True, "reply": reply, "applied": [],
                "rejected": outcome.rejected, "changed": False}

    session.push_undo(snap)
    session.result.program = program
    session.result.layout = layouts[0]
    session.result.alternatives = layouts[1:3]
    after = dict(layouts[0].metrics)

    session.rationale.add(
        "edit",
        message.strip()[:120],
        what_en=message.strip()[:120],
        why_ar=understood,
        by="user",
        applied=outcome.applied,
    )

    delta = _delta_text(before, after, ar)
    reply = "\n".join(
        [p for p in [understood, "· " + " · ".join(outcome.applied), delta] if p]
    )
    if outcome.rejected:
        head = "مطبّقتش: " if ar else "Not applied: "
        reply += "\n" + head + " · ".join(outcome.rejected)

    session.add_turn(Turn(
        role="assistant", text=reply,
        applied=outcome.applied, rejected=outcome.rejected,
        metrics_before=before, metrics_after=after,
    ))
    return {
        "ok": True,
        "reply": reply,
        "understood": understood,
        "applied": outcome.applied,
        "rejected": outcome.rejected,
        "changed": True,
        "metrics_before": before,
        "metrics_after": after,
    }


def _delta_text(before: dict, after: dict, ar: bool) -> str:
    """فرق الأرقام قبل/بعد — الجزء اللي المستخدم بيحكم بيه فعلًا."""
    bits = []
    eb, ea = int(before.get("errors", 0)), int(after.get("errors", 0))
    if eb != ea:
        arrow = "↓" if ea < eb else "↑"
        bits.append(
            f"المخالفات {eb} → {ea} {arrow}" if ar
            else f"violations {eb} → {ea} {arrow}"
        )
    fb, fa = before.get("efficiency", 0), after.get("efficiency", 0)
    if abs(fa - fb) > 0.005:
        bits.append(
            f"الكفاءة {fb * 100:.1f}% → {fa * 100:.1f}%" if ar
            else f"efficiency {fb * 100:.1f}% → {fa * 100:.1f}%"
        )
    return " · ".join(bits)
