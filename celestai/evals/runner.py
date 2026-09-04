"""مشغّل التقييم — runs the suite and scores it.

المبدأ الحاكم: **الدرجة الموضوعية هي الأساس، والحَكَم الذاتي إضافة.**
الأرقام من `validate()` متكرّرة بالظبط كل مرة ومش محتاجة AI. حَكَم الـ LLM
بيجاوب على سؤال واحد بس (هل الوصف اتنفّذ؟) وبيتعلّم عليه في التقرير إنه ذاتي.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models import DesignRequest
from .cases import CASES, EvalCase


# ---------------------------------------------------------------------------
# نتيجة الحالة الواحدة
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    case_id: str
    ok: bool = False
    crashed: str = ""

    # موضوعي
    errors: int = 0
    warnings: int = 0
    rooms: int = 0
    efficiency: float = 0.0
    circulation_share: float = 0.0
    worst_aspect: float = 0.0
    seconds: float = 0.0

    # التوقعات
    met_max_errors: bool = False
    met_min_rooms: bool = False
    met_kinds: bool = False
    missing_kinds: list[str] = field(default_factory=list)

    # ذاتي (اختياري)
    judge_score: Optional[int] = None
    judge_missed: list[str] = field(default_factory=list)
    judge_note: str = ""

    @property
    def objective_score(self) -> float:
        """0..1 من الأرقام الحتمية بس."""
        if self.crashed:
            return 0.0
        score = 0.0
        score += 0.40 if self.met_max_errors else 0.40 / (1 + self.errors)
        score += 0.15 if self.met_min_rooms else 0.0
        score += 0.15 if self.met_kinds else 0.0
        score += 0.15 * min(self.efficiency / 0.80, 1.0)
        score += 0.15 / (1 + self.warnings / max(self.rooms, 1))
        return round(min(score, 1.0), 4)

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "ok": self.ok,
            "crashed": self.crashed,
            "errors": self.errors,
            "warnings": self.warnings,
            "rooms": self.rooms,
            "efficiency": round(self.efficiency, 4),
            "circulation_share": round(self.circulation_share, 4),
            "worst_aspect": round(self.worst_aspect, 3),
            "seconds": round(self.seconds, 2),
            "met_max_errors": self.met_max_errors,
            "met_min_rooms": self.met_min_rooms,
            "met_kinds": self.met_kinds,
            "missing_kinds": self.missing_kinds,
            "objective_score": self.objective_score,
            "judge_score": self.judge_score,
            "judge_missed": self.judge_missed,
        }


@dataclass
class Scorecard:
    label: str = ""
    results: list[CaseResult] = field(default_factory=list)
    use_ai: bool = False
    repair: bool = False
    judged: bool = False
    seconds: float = 0.0

    @property
    def clean(self) -> int:
        return sum(1 for r in self.results if r.errors == 0 and not r.crashed)

    @property
    def crashed(self) -> int:
        return sum(1 for r in self.results if r.crashed)

    @property
    def total_errors(self) -> int:
        return sum(r.errors for r in self.results)

    @property
    def total_warnings(self) -> int:
        return sum(r.warnings for r in self.results)

    @property
    def mean_objective(self) -> float:
        if not self.results:
            return 0.0
        return round(sum(r.objective_score for r in self.results) / len(self.results), 4)

    @property
    def mean_judge(self) -> Optional[float]:
        scored = [r.judge_score for r in self.results if r.judge_score is not None]
        if not scored:
            return None
        return round(sum(scored) / len(scored), 2)

    @property
    def mean_efficiency(self) -> float:
        ok = [r for r in self.results if not r.crashed]
        if not ok:
            return 0.0
        return round(sum(r.efficiency for r in ok) / len(ok), 4)

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "use_ai": self.use_ai,
            "repair": self.repair,
            "judged": self.judged,
            "cases": len(self.results),
            "clean": self.clean,
            "crashed": self.crashed,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "mean_objective": self.mean_objective,
            "mean_judge": self.mean_judge,
            "mean_efficiency": self.mean_efficiency,
            "seconds": round(self.seconds, 1),
            "results": [r.as_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# حَكَم ذاتي (اختياري)
# ---------------------------------------------------------------------------

JUDGE_SYSTEM = """You are scoring whether a floor plan HONOURED ITS BRIEF. You are \
NOT judging whether the plan is beautiful, and you are NOT re-checking the building \
code — a deterministic validator already did that and its verdict is final.

Score 0–10 on one question only: **did the plan deliver what the client asked for?**

Rules:
1. Explicit requests count most. If the brief asked for a closed home office and there \
is no office, that is a major miss regardless of how good the rest is.
2. A room the engine had to drop for lack of area is still a miss — note it, but say \
in the justification that the area was the constraint.
3. Do not reward extra rooms nobody asked for.
4. Do not penalise code violations here. That is measured separately.
5. Be strict. A 10 means every explicit request was met. Most plans are 6–8.
6. Justify in one or two sentences, in Egyptian Arabic."""


def _judge(case: EvalCase, layout, program) -> tuple[Optional[int], list[str], str]:
    from ..ai.client import AIUnavailable, ask
    from ..ai.schemas import BriefCompliance

    if not case.brief.strip():
        return None, [], ""

    rooms = "\n".join(
        f"  - {r.name_en or r.spec_id} ({r.kind.value}): {r.net_area:.1f} m²"
        for r in sorted(layout.rooms, key=lambda r: -r.net_area)
    )
    asked = []
    if case.bedrooms is not None:
        asked.append(f"bedrooms: {case.bedrooms}")
    if case.bathrooms is not None:
        asked.append(f"bathrooms: {case.bathrooms}")
    if case.receptions is not None:
        asked.append(f"receptions: {case.receptions}")

    try:
        verdict = ask(
            JUDGE_SYSTEM,
            f"## Brief\n{case.brief}\n\n"
            f"## Structured requests\n{', '.join(asked) or '(none)'}\n\n"
            f"## Area\n{case.area:.0f} m²\n\n"
            f"## Plan delivered\n{rooms}\n\n"
            "Score it.",
            BriefCompliance, task="judge", max_tokens=3000,
        )
    except AIUnavailable:
        return None, [], ""
    return verdict.score, verdict.missed_ar, verdict.justification_ar


# ---------------------------------------------------------------------------
# التشغيل
# ---------------------------------------------------------------------------


def run_case(
    case: EvalCase,
    *,
    use_ai: bool = False,
    repair: bool = False,
    judge: bool = False,
) -> CaseResult:
    """يشغّل حالة واحدة ويرجّع نتيجتها."""
    from ..service import generate

    result = CaseResult(case_id=case.case_id)
    t0 = time.time()

    req = DesignRequest(
        area=case.area,
        building_type=case.building_type,
        brief=case.brief,
        bedrooms=case.bedrooms,
        bathrooms=case.bathrooms,
        receptions=case.receptions,
        entry_side=case.entry_side,      # type: ignore[arg-type]
        exterior_sides=case.exterior_sides,  # type: ignore[arg-type]
        use_ai=use_ai,
        outputs=["svg"],
    )

    try:
        design = generate(req, out_dir=None, alternatives=0, repair=repair)
    except Exception as exc:  # noqa: BLE001 — حالة فاشلة مش بتوقف المجموعة
        result.crashed = f"{type(exc).__name__}: {exc}"
        result.seconds = time.time() - t0
        return result

    layout = design.layout
    m = layout.metrics
    result.ok = True
    result.errors = int(m.get("errors", 0))
    result.warnings = int(m.get("warnings", 0))
    result.rooms = int(m.get("rooms", 0))
    result.efficiency = float(m.get("efficiency", 0.0))
    result.circulation_share = float(m.get("circulation_share", 0.0))
    result.worst_aspect = float(m.get("worst_aspect", 0.0))

    result.met_max_errors = result.errors <= case.expect_max_errors
    result.met_min_rooms = result.rooms >= case.expect_min_rooms
    kinds = {r.kind.value for r in layout.rooms}
    result.missing_kinds = [k for k in case.expect_kinds if k not in kinds]
    result.met_kinds = not result.missing_kinds

    if judge:
        score, missed, note = _judge(case, layout, design.program)
        result.judge_score, result.judge_missed, result.judge_note = score, missed, note

    result.seconds = time.time() - t0
    return result


def run_suite(
    cases: list[EvalCase] | None = None,
    *,
    label: str = "",
    use_ai: bool = False,
    repair: bool = False,
    judge: bool = False,
    progress=None,
) -> Scorecard:
    """يشغّل المجموعة كاملة."""
    cases = cases or CASES
    card = Scorecard(label=label, use_ai=use_ai, repair=repair, judged=judge)
    t0 = time.time()
    for i, case in enumerate(cases, start=1):
        if progress:
            progress(i, len(cases), case.case_id)
        card.results.append(
            run_case(case, use_ai=use_ai, repair=repair, judge=judge)
        )
    card.seconds = time.time() - t0
    return card


# ---------------------------------------------------------------------------
# المقارنة والتقرير
# ---------------------------------------------------------------------------


def compare_scorecards(base: Scorecard, new: Scorecard) -> dict:
    """يقارن بطاقتين — ده اللي بيمنع الانحدار الصامت."""
    by_id = {r.case_id: r for r in base.results}
    regressions, improvements = [], []
    for r in new.results:
        old = by_id.get(r.case_id)
        if old is None:
            continue
        delta = r.objective_score - old.objective_score
        row = {
            "case_id": r.case_id,
            "before": old.objective_score,
            "after": r.objective_score,
            "delta": round(delta, 4),
            "errors_before": old.errors,
            "errors_after": r.errors,
        }
        if delta < -0.02:
            regressions.append(row)
        elif delta > 0.02:
            improvements.append(row)

    mean_delta = new.mean_objective - base.mean_objective

    # الحكم مش بالمتوسط لوحده. حالة واحدة بتنهار وسط 12 حالة كويسة بتحرّك
    # المتوسط أقل من العتبة، وتعدّي كأن مفيش حاجة حصلت — وده بالظبط الانحدار
    # الصامت اللي الحزمة دي موجودة عشانه. فأي حالة اتكسرت أو زادت مخالفاتها
    # بتبقى انحدار مهما كان المتوسط.
    broke = [
        r for r in regressions
        if r["errors_after"] > r["errors_before"] or r["delta"] < -0.08
    ]
    if mean_delta < -0.01 or broke:
        verdict = "regression"
    elif mean_delta > 0.01:
        verdict = "improvement"
    else:
        verdict = "no significant change"

    return {
        "mean_before": base.mean_objective,
        "mean_after": new.mean_objective,
        "mean_delta": round(mean_delta, 4),
        "errors_before": base.total_errors,
        "errors_after": new.total_errors,
        "clean_before": base.clean,
        "clean_after": new.clean,
        "regressions": sorted(regressions, key=lambda r: r["delta"]),
        "improvements": sorted(improvements, key=lambda r: -r["delta"]),
        "broke": [r["case_id"] for r in broke],
        "verdict": verdict,
    }


def scorecard_markdown(card: Scorecard, language: str = "ar") -> str:
    ar = language != "en"
    p: list[str] = []
    p.append(f"# بطاقة الجودة{' — ' + card.label if card.label else ''}\n" if ar
             else f"# Quality scorecard{' — ' + card.label if card.label else ''}\n")

    mode = []
    mode.append(("AI" if card.use_ai else ("قواعد" if ar else "rules")))
    if card.repair:
        mode.append("إصلاح ذاتي" if ar else "self-repair")
    if card.judged:
        mode.append("حَكَم" if ar else "judge")

    p.append(
        f"\n**الوضع:** {' + '.join(mode)} · {len(card.results)} حالة · "
        f"{card.seconds:.0f} ثانية\n" if ar else
        f"\n**Mode:** {' + '.join(mode)} · {len(card.results)} cases · "
        f"{card.seconds:.0f}s\n"
    )
    p.append(
        f"\n| | |\n|---|---|\n"
        f"| {'الدرجة الموضوعية' if ar else 'Objective score'} | "
        f"**{card.mean_objective:.3f}** |\n"
        f"| {'حالات نضيفة' if ar else 'Clean cases'} | "
        f"{card.clean}/{len(card.results)} |\n"
        f"| {'إجمالي المخالفات' if ar else 'Total violations'} | "
        f"{card.total_errors} |\n"
        f"| {'إجمالي التنبيهات' if ar else 'Total warnings'} | "
        f"{card.total_warnings} |\n"
        f"| {'متوسط الكفاءة' if ar else 'Mean efficiency'} | "
        f"{card.mean_efficiency * 100:.1f}% |\n"
        f"| {'انهيارات' if ar else 'Crashes'} | {card.crashed} |\n"
    )
    if card.mean_judge is not None:
        p.append(
            f"| {'حَكَم تنفيذ الوصف (ذاتي)' if ar else 'Brief compliance (subjective)'}"
            f" | {card.mean_judge:.1f}/10 |\n"
        )

    p.append("\n## الحالات\n" if ar else "\n## Cases\n")
    p.append(
        "| الحالة | مخالفات | تنبيهات | فراغات | كفاءة | درجة | حَكَم |\n"
        if ar else
        "| Case | Errors | Warnings | Rooms | Efficiency | Score | Judge |\n"
    )
    p.append("|---|---|---|---|---|---|---|\n")
    for r in sorted(card.results, key=lambda r: r.objective_score):
        if r.crashed:
            p.append(f"| `{r.case_id}` | — | — | — | — | **انهار** | — |\n")
            continue
        judge = f"{r.judge_score}/10" if r.judge_score is not None else "—"
        p.append(
            f"| `{r.case_id}` | {r.errors} | {r.warnings} | {r.rooms} | "
            f"{r.efficiency * 100:.0f}% | {r.objective_score:.3f} | {judge} |\n"
        )

    misses = [r for r in card.results if r.missing_kinds]
    if misses:
        p.append("\n### فراغات مطلوبة ومطلعتش\n" if ar
                 else "\n### Requested spaces that did not appear\n")
        for r in misses:
            p.append(f"- `{r.case_id}`: {', '.join(r.missing_kinds)}\n")

    p.append(
        "\n---\n\n> الدرجة الموضوعية محسوبة من `validate()` والمقاييس — متكرّرة "
        "بالظبط كل مرة. درجة الحَكَم **ذاتية** ومن موديل، فاتعامل معاها كمؤشر "
        "اتجاه مش كحقيقة.\n"
        if ar else
        "\n---\n\n> The objective score comes from `validate()` and the metrics — "
        "exactly reproducible. The judge score is **subjective** and model-produced; "
        "treat it as a direction indicator, not a fact.\n"
    )
    return "".join(p)


def save_scorecard(card: Scorecard, path: str | Path) -> str:
    import json

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(card.as_dict(), ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return str(p)


def load_scorecard(path: str | Path) -> Scorecard:
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    card = Scorecard(
        label=data.get("label", ""),
        use_ai=data.get("use_ai", False),
        repair=data.get("repair", False),
        judged=data.get("judged", False),
        seconds=data.get("seconds", 0.0),
    )
    for row in data.get("results", []):
        r = CaseResult(case_id=row["case_id"])
        for key in ("ok", "crashed", "errors", "warnings", "rooms", "efficiency",
                    "circulation_share", "worst_aspect", "seconds", "met_max_errors",
                    "met_min_rooms", "met_kinds", "missing_kinds", "judge_score",
                    "judge_missed"):
            if key in row:
                setattr(r, key, row[key])
        card.results.append(r)
    return card
