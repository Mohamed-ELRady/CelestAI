"""حلقة الإصلاح الذاتي — أ-1 · Self-repair loop.

المشكلة: الموديل بيكتب البرنامج المعماري وهو **أعمى**. لو الناتج فيه 12 مخالفة،
محدش بيقوله. `_trim_program` كان بيحاول يصلّح بطريقة غبية: بيشيل غرف بالأولوية
لحد ما المخالفات تقل.

الحل: عندنا **مُتحقِّق موثوق** (`validate()`) — ده بالظبط اللي الموديل مش بيعرف
يعمله وإحنا بنعرف. فبنقفل الحلقة: نحل، نراجع، نودّي المخالفات للموديل، ناخد
برنامج معدّل، نحل تاني، ونمسك الأحسن.

الحلقة دي **agent بمُتحقِّق** — من غير framework، بالكود الموجود. ولو الـ AI مش
متاح، بنرجع للتقليم القواعدي القديم زي ما هو.
"""

from __future__ import annotations

import logging

from ..models import ArchitecturalProgram, DesignRequest, Layout, Rect
from .client import AIUnavailable, ask
from .schemas import RepairPlan

log = logging.getLogger("celestai.ai.repair")

MAX_ROUNDS = 2

SYSTEM = """You are the repair pass of CelestAI's architectural programming engine.

A previous programme was packed onto the plot by a deterministic geometry engine, \
and the result FAILED the building-code check. You are given the exact violations.

Your job: return a REVISED programme that fixes those specific violations.

## How the geometry engine works — this determines what actually helps
- A central circulation hub runs perpendicular to the entry façade and splits the \
plot into two strips. Every other room is a "bay" in one of those strips.
- A bay's WIDTH is the strip width; its DEPTH is (its area ÷ strip width).
- Strip width is proportional to the total area of the rooms in that strip. So a \
strip holding lots of small rooms is NARROW, and every room in it is narrow.
- Therefore: **to widen a room, either give it more area, or move area out of the \
OTHER strip** — the two are coupled. Enlarging one room alone often does nothing.
- Rooms in a strip that faces a party wall get no windows. A light well can \
ventilate a kitchen/bath there, but never a bedroom or living room.

## Rules
1. The sum of `target_area` MUST equal the same usable area as before (within 1%). \
The engine fills the plot completely — there is nowhere for leftover area to go.
2. Fixing a MIN_WIDTH violation usually means REDUCING the number of rooms sharing \
that strip, or raising that room's area enough to widen its bay. Say which you did.
3. Fixing a MIN_AREA violation means giving the room area — taken explicitly from a \
named larger room.
4. If the area genuinely cannot carry the programme, DROP a room rather than \
returning something that will fail again. A comfortable 2-bedroom beats a cramped 3.
5. Never drop the last bathroom or the last kitchen. A home without them is not a home.
6. Keep exactly one circulation hub, and keep it first in the list.
7. `design_notes` must be written in {notes_language}.

Return the full revised programme, plus a one-or-two sentence diagnosis of what \
was actually wrong."""


def _describe_layout(layout: Layout, plot: Rect) -> str:
    """وصف نصّي مختصر للمخطط الفاشل — الموديل محتاج يشوف الهندسة مش البرنامج بس."""
    lines = [
        f"Plot: {plot.w:.2f} m x {plot.h:.2f} m ({plot.area:.1f} m²)",
        f"Entry side: {layout.entry_side}",
        "",
        "Rooms as built (clear internal dimensions):",
    ]
    for r in sorted(layout.rooms, key=lambda r: -r.net_area):
        n = r.net_rect
        short = min(n.w, n.h)
        lines.append(
            f"  - {r.spec_id} ({r.kind.value}): {n.w:.2f} x {n.h:.2f} m"
            f" = {n.area:.2f} m², shortest {short:.2f} m,"
            f" window={'yes' if r.has_window else 'NO'}"
        )
    lines.append("")
    lines.append("Code violations that must be fixed:")
    for i in layout.issues:
        if i.severity == "error":
            lines.append(f"  - [{i.code}] {i.message_en or i.message_ar}")
    warnings = [i for i in layout.issues if i.severity == "warning"]
    if warnings:
        lines.append("")
        lines.append("Warnings (fix if cheap, do not make errors worse):")
        for i in warnings[:6]:
            lines.append(f"  - [{i.code}] {i.message_en or i.message_ar}")
    return "\n".join(lines)


def repair_program(
    program: ArchitecturalProgram,
    layout: Layout,
    req: DesignRequest,
    plot: Rect,
    usable_area: float,
) -> tuple[ArchitecturalProgram | None, str]:
    """يطلب برنامج معدّل يستهدف مخالفات المخطط ده.

    يرجّع (البرنامج، التشخيص) أو (None, "") لو الـ AI مش متاح أو فشل.
    """
    errors = [i for i in layout.issues if i.severity == "error"]
    if not errors:
        return None, ""

    notes_lang = "English" if req.lang_key == "en" else "Egyptian Arabic"
    system = SYSTEM.replace("{notes_language}", notes_lang)

    current = "\n".join(
        f"  - {r.id} ({r.kind.value}): target {r.target_area:.2f} m²,"
        f" min_width {r.min_width:.2f} m"
        + (f", en-suite of {r.attach_to}" if r.attach_to else "")
        for r in program.rooms
    )
    user = (
        f"## Usable area to allocate\n{usable_area:.2f} m² "
        "(the sum of target_area must equal this)\n\n"
        f"## Current programme\n{current}\n\n"
        f"## What the engine built from it\n{_describe_layout(layout, plot)}\n\n"
        "Return the revised programme now."
    )

    try:
        plan = ask(system, user, RepairPlan, task="repair", max_tokens=12000)
    except AIUnavailable as exc:
        log.info("الإصلاح الذاتي مش متاح (%s) — هنكمّل بالتقليم القواعدي", exc)
        return None, ""

    diagnosis = plan.diagnosis_ar if req.lang_key != "en" else (
        plan.diagnosis_en or plan.diagnosis_ar
    )
    return plan.program, diagnosis


def repair_loop(
    program: ArchitecturalProgram,
    req: DesignRequest,
    plot: Rect | None,
    *,
    rounds: int = MAX_ROUNDS,
    log_to=None,
):
    """يحل، وكل ما يلاقي مخالفات يطلب إصلاح من الموديل ويعيد.

    بيرجّع نفس شكل `solve_with_trimming`: (أفضل مخطط، برنامجه، البدائل).
    بيمسك دايمًا **الأحسن** — لو الإصلاح وحّش النتيجة بنرجع للقديم.
    """
    from ..engine.solver import solve
    from ..planner.rules import normalise_program
    from ..service import solve_with_trimming

    # الأساس: التقليم القواعدي — بيشتغل من غير AI ودايمًا موجود
    best, best_program, alts = solve_with_trimming(program, req, plot)
    if best is None:
        return best, best_program, alts

    area_ref = plot.area if plot is not None else best.plot.area

    for round_no in range(rounds):
        errors = int(best.metrics.get("errors", 0))
        if errors == 0:
            break

        revised, diagnosis = repair_program(
            best_program, best, req, best.plot, area_ref
        )
        if revised is None:
            break

        try:
            revised = normalise_program(revised, area_ref)
            layouts = solve(revised, req, plot)
        except Exception as exc:  # noqa: BLE001 — إصلاح فاشل ميوقفش الحل الأصلي
            log.info("لفّة إصلاح فشلت: %s", exc)
            break
        if not layouts:
            break

        candidate = layouts[0]
        improved = candidate.score > best.score
        if log_to is not None:
            log_to.add(
                "repair",
                (
                    f"لفّة إصلاح {round_no + 1}: "
                    + (
                        f"المخالفات من {errors} لـ"
                        f"{int(candidate.metrics.get('errors', 0))}"
                        if improved else "مفيش تحسّن، رجعنا للمخطط الأصلي"
                    )
                ),
                what_en=(
                    f"Repair round {round_no + 1}: "
                    + (
                        f"violations {errors} → "
                        f"{int(candidate.metrics.get('errors', 0))}"
                        if improved else "no improvement, kept the original"
                    )
                ),
                why_ar=diagnosis,
                by="ai",
                round=round_no + 1,
                before_errors=errors,
                after_errors=int(candidate.metrics.get("errors", 0)),
                accepted=improved,
            )

        if not improved:
            break
        best, best_program, alts = candidate, revised, layouts[1:]

    return best, best_program, alts
