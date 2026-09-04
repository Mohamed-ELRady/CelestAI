"""دراسة الجدوى — هـ-1 · Feasibility study, و هـ-2 · Multi-objective search.

سؤال المطوّر مش «ارسملي 4 شقق». سؤاله: **«عندي أرض 500 م² — أعمل فيها إيه؟»**

الملف ده بيجاوب على السؤال ده: بياخد الأرض والقيود، وبيجرّب فضاء بحث من
السيناريوهات (عدد أدوار × عدد وحدات × خلطة استخدامات)، وبيقيّم كل واحد بأرقام
حقيقية من المحرك — مساحة قابلة للبيع، كفاءة، مخالفات، تكلفة تقديرية.

**البحث والتقييم حتميان بالكامل.** الـ AI (في `ai/feasibility.py`) بيتنادى بعدين
وبس عشان يكتب التوصية والمخاطر بلغة مفهومة.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..knowledge import FLOOR_TO_FLOOR, unit_standard
from ..models import BuildingRequest, FloorSpec, FloorUse

# ---------------------------------------------------------------------------
# أوزان الأهداف — هـ-2
# ---------------------------------------------------------------------------


@dataclass
class Objectives:
    """أوزان المستخدم. المجموع مش لازم يساوي 1 — بيتعمله تطبيع."""

    sellable: float = 1.0        # مساحة قابلة للبيع
    compliance: float = 1.0      # قلة المخالفات
    efficiency: float = 0.7      # كفاءة التوزيع
    cost: float = 0.5            # قلة التكلفة
    daylight: float = 0.5        # جودة الإضاءة والتهوية

    def normalised(self) -> "Objectives":
        total = (
            self.sellable + self.compliance + self.efficiency
            + self.cost + self.daylight
        ) or 1.0
        return Objectives(
            sellable=self.sellable / total,
            compliance=self.compliance / total,
            efficiency=self.efficiency / total,
            cost=self.cost / total,
            daylight=self.daylight / total,
        )


# ---------------------------------------------------------------------------
# السيناريو
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    scenario_id: str
    label_ar: str
    label_en: str
    request: BuildingRequest
    floors: list = field(default_factory=list)

    # أرقام محسوبة
    total_units: int = 0
    sellable_area: float = 0.0
    built_area: float = 0.0
    efficiency: float = 0.0
    errors: int = 0
    warnings: int = 0
    shafts: int = 0
    height: float = 0.0
    cost_low: Optional[float] = None
    cost_high: Optional[float] = None
    score: float = 0.0
    failed: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.scenario_id,
            "label_ar": self.label_ar, "label_en": self.label_en,
            "floors": len(self.floors),
            "units": self.total_units,
            "sellable_area": round(self.sellable_area, 2),
            "built_area": round(self.built_area, 2),
            "efficiency": round(self.efficiency, 4),
            "errors": self.errors, "warnings": self.warnings,
            "shafts": self.shafts,
            "height": round(self.height, 2),
            "cost_low": self.cost_low, "cost_high": self.cost_high,
            "score": round(self.score, 4),
            "failed": self.failed,
        }


@dataclass
class FeasibilityStudy:
    plot_area: float
    scenarios: list[Scenario] = field(default_factory=list)
    objectives: Objectives = field(default_factory=Objectives)
    advice: object = None            # FeasibilityAdvice لو الـ AI اشتغل

    @property
    def best(self) -> Optional[Scenario]:
        ok = [s for s in self.scenarios if not s.failed]
        return max(ok, key=lambda s: s.score) if ok else None

    def as_dict(self) -> dict:
        return {
            "plot_area": self.plot_area,
            "best": self.best.scenario_id if self.best else None,
            "scenarios": [s.as_dict() for s in self.scenarios],
        }


# ---------------------------------------------------------------------------
# توليد فضاء البحث
# ---------------------------------------------------------------------------

#: خلطات الاستخدام اللي تستاهل التجربة
MIXES: list[tuple[str, FloorUse, FloorUse, str, str]] = [
    ("res",        FloorUse.APARTMENTS, FloorUse.APARTMENTS,
     "سكني بالكامل", "Fully residential"),
    ("retail_res", FloorUse.RETAIL, FloorUse.APARTMENTS,
     "أرضي محلات + سكني", "Retail ground + residential"),
    ("retail_off", FloorUse.RETAIL, FloorUse.OFFICES,
     "أرضي محلات + إداري", "Retail ground + offices"),
    ("off",        FloorUse.OFFICES, FloorUse.OFFICES,
     "إداري بالكامل", "Fully offices"),
    ("mixed3",     FloorUse.RETAIL, FloorUse.APARTMENTS,
     "أرضي محلات + دور إداري + سكني", "Retail + offices + residential"),
    ("clinics",    FloorUse.RETAIL, FloorUse.CLINICS,
     "أرضي محلات + عيادات", "Retail ground + clinics"),
]


def _build_specs(
    mix_id: str, ground: FloorUse, upper: FloorUse, floors: int, units: int
) -> list[FloorSpec]:
    specs = [FloorSpec(level=0, use=ground, units=units)]
    for level in range(1, floors):
        use = upper
        if mix_id == "mixed3" and level == 1:
            use = FloorUse.OFFICES
        specs.append(FloorSpec(level=level, use=use, units=units))
    return specs


def _candidate_units(floor_area: float, use: FloorUse) -> list[int]:
    """أعداد وحدات معقولة للمساحة دي — أزواج بس، لأن النواة المركزية بتقسم لشريطين."""
    st = unit_standard(use.value)
    usable = floor_area * 0.82
    ideal = max(1, round(usable / st.ideal_area))
    options = {2, 4}
    if ideal >= 5:
        options.add(6)
    if usable / 2 > st.max_area:
        options.discard(2)
    if usable / 4 < st.min_area:
        options.discard(4)
    options = {n for n in options if usable / n >= st.min_area * 0.85}
    return sorted(options) or [2]


# ---------------------------------------------------------------------------
# التقييم
# ---------------------------------------------------------------------------


def _score(s: Scenario, ref: dict, w: Objectives) -> float:
    """درجة موحّدة 0..1 بعد تطبيع كل هدف على أفضل سيناريو."""
    if s.failed:
        return -1.0

    sellable = s.sellable_area / max(ref["sellable"], 1e-6)
    efficiency = s.efficiency / max(ref["efficiency"], 1e-6)

    # المخالفات لكل وحدة — سيناريو بـ40 وحدة و20 مخالفة أحسن من 4 وحدات و8
    per_unit = s.errors / max(s.total_units, 1)
    compliance = 1.0 / (1.0 + per_unit)

    if s.cost_high and ref["cost"]:
        cost = ref["cost"] / max(s.cost_high, 1e-6)
    else:
        cost = 1.0

    daylight = 1.0 / (1.0 + (s.warnings / max(s.total_units, 1)))

    return (
        w.sellable * min(sellable, 1.5)
        + w.compliance * compliance
        + w.efficiency * min(efficiency, 1.5)
        + w.cost * min(cost, 1.5)
        + w.daylight * daylight
    )


def study_feasibility(
    plot_area: float,
    *,
    max_floors: int = 6,
    min_floors: int = 2,
    floor_options: list[int] | None = None,
    objectives: Objectives | None = None,
    prices=None,
    language: str = "ar",
    brief: str = "",
    limit: int = 12,
) -> FeasibilityStudy:
    """بيبحث في فضاء السيناريوهات ويرجّع الدراسة مرتّبة.

    كل التقييم من المحرك الحتمي — مفيش AI في الأرقام.
    """
    from ..engine.building import compose_building
    from .quantities import take_off_building

    w = (objectives or Objectives()).normalised()
    study = FeasibilityStudy(plot_area=plot_area, objectives=w)

    floor_counts = floor_options or sorted(
        {min_floors, (min_floors + max_floors) // 2, max_floors}
    )
    floor_counts = [f for f in floor_counts if min_floors <= f <= max_floors]

    for mix_id, ground, upper, label_ar, label_en in MIXES:
        for n_floors in floor_counts:
            if mix_id == "mixed3" and n_floors < 3:
                continue
            for units in _candidate_units(plot_area, upper):
                sid = f"{mix_id}-{n_floors}f-{units}u"
                req = BuildingRequest(
                    area=plot_area,
                    floors=_build_specs(mix_id, ground, upper, n_floors, units),
                    brief=brief,
                    language=language,   # type: ignore[arg-type]
                    use_ai=False,        # البحث حتمي — الـ AI بيعلّق بعدين
                )
                scenario = Scenario(
                    scenario_id=sid,
                    label_ar=f"{label_ar} · {n_floors} أدوار · {units} وحدة/دور",
                    label_en=f"{label_en} · {n_floors} floors · {units} units/floor",
                    request=req,
                )
                try:
                    floors = compose_building(req)
                except Exception as exc:  # noqa: BLE001 — سيناريو فاشل مش بيوقف البحث
                    scenario.failed = type(exc).__name__
                    study.scenarios.append(scenario)
                    continue

                scenario.floors = floors
                scenario.total_units = sum(len(f.units) for f in floors)
                scenario.sellable_area = sum(
                    f.metrics.get("unit_area", 0.0) for f in floors
                )
                scenario.built_area = sum(
                    f.metrics.get("gross_area", 0.0) for f in floors
                )
                scenario.efficiency = (
                    sum(f.metrics.get("efficiency", 0.0) for f in floors) / len(floors)
                )
                scenario.errors = sum(int(f.metrics.get("errors", 0)) for f in floors)
                scenario.warnings = sum(int(f.metrics.get("warnings", 0)) for f in floors)
                scenario.shafts = sum(int(f.metrics.get("shafts", 0)) for f in floors)
                scenario.height = len(floors) * FLOOR_TO_FLOOR

                if prices is not None:
                    try:
                        boq, _per = take_off_building(floors, prices=prices)
                        scenario.cost_low, scenario.cost_high = boq.low, boq.high
                    except Exception:  # noqa: BLE001
                        pass

                study.scenarios.append(scenario)

    ok = [s for s in study.scenarios if not s.failed]
    if ok:
        ref = {
            "sellable": max(s.sellable_area for s in ok),
            "efficiency": max(s.efficiency for s in ok),
            "cost": min((s.cost_high for s in ok if s.cost_high), default=0.0),
        }
        for s in study.scenarios:
            s.score = _score(s, ref, w)

    study.scenarios.sort(key=lambda s: -s.score)
    study.scenarios = study.scenarios[:limit]
    return study


# ---------------------------------------------------------------------------
# التقرير
# ---------------------------------------------------------------------------


def feasibility_markdown(study: FeasibilityStudy, language: str = "ar") -> str:
    ar = language != "en"
    p: list[str] = []
    p.append("# دراسة جدوى مبدئية\n" if ar else "# Schematic feasibility study\n")
    p.append(
        f"\nأرض بمسطح دور **{study.plot_area:.0f} م²**. "
        f"اتجرّب {len(study.scenarios)} سيناريو، وكل واحد اتحل بالمحرك الكامل "
        "(نواة + وحدات + مناور + مراجعة كودية) — الأرقام دي مقاسة مش مقدّرة.\n"
        if ar else
        f"\nA plot with a **{study.plot_area:.0f} m²** floor plate. "
        f"{len(study.scenarios)} scenarios were tried, each solved with the full "
        "engine (core + units + light wells + code review) — these numbers are "
        "measured, not estimated.\n"
    )

    best = study.best
    if best:
        p.append(
            f"\n## التوصية: {best.label_ar}\n" if ar else
            f"\n## Recommendation: {best.label_en}\n"
        )
        p.append(
            f"\n- **{best.total_units} وحدة** بإجمالي مسطح بيع "
            f"{best.sellable_area:,.0f} م²\n"
            f"- كفاءة توزيع {best.efficiency * 100:.1f}%\n"
            f"- {best.errors} مخالفة كودية · {best.warnings} تنبيه\n"
            f"- ارتفاع تقريبي {best.height:.1f} م\n"
            if ar else
            f"\n- **{best.total_units} units**, {best.sellable_area:,.0f} m² sellable\n"
            f"- {best.efficiency * 100:.1f}% planning efficiency\n"
            f"- {best.errors} code violations · {best.warnings} warnings\n"
            f"- approx. {best.height:.1f} m tall\n"
        )
        if best.cost_low:
            p.append(
                f"- تكلفة تقديرية {best.cost_low:,.0f} – {best.cost_high:,.0f}\n"
                if ar else
                f"- estimated cost {best.cost_low:,.0f} – {best.cost_high:,.0f}\n"
            )

    p.append("\n## كل السيناريوهات\n" if ar else "\n## All scenarios\n")
    p.append(
        "| السيناريو | وحدات | مسطح البيع | الكفاءة | مخالفات | الدرجة |\n"
        if ar else
        "| Scenario | Units | Sellable | Efficiency | Violations | Score |\n"
    )
    p.append("|---|---|---|---|---|---|\n")
    for s in study.scenarios:
        if s.failed:
            label = s.label_ar if ar else s.label_en
            note = "تعذّر" if ar else "failed"
            p.append(f"| {label} | — | — | — | — | {note} |\n")
            continue
        p.append(
            f"| {s.label_ar if ar else s.label_en} | {s.total_units} | "
            f"{s.sellable_area:,.0f} | {s.efficiency * 100:.1f}% | "
            f"{s.errors} | {s.score:.3f} |\n"
        )

    advice = study.advice
    if advice is not None:
        reasoning = advice.reasoning_ar if ar else (
            advice.reasoning_en or advice.reasoning_ar
        )
        if reasoning:
            p.append(("\n## قراءة النتائج\n\n" if ar else "\n## Reading the results\n\n")
                     + reasoning + "\n")
        by_id = {v.scenario_id: v for v in advice.verdicts}
        rows = [s for s in study.scenarios if s.scenario_id in by_id][:4]
        if rows:
            p.append("\n## السيناريوهات المرشّحة\n" if ar else "\n## Shortlist\n")
            for s in rows:
                v = by_id[s.scenario_id]
                p.append(f"\n### {s.label_ar if ar else s.label_en}\n")
                p.append((v.pitch_ar if ar else (v.pitch_en or v.pitch_ar)) + "\n")
                risk = v.risk_ar if ar else (v.risk_en or v.risk_ar)
                if risk:
                    p.append(f"\n> **المخاطرة:** {risk}\n" if ar
                             else f"\n> **Risk:** {risk}\n")

    p.append(
        "\n---\n\n> دراسة **مبدئية** مبنية على الهندسة بس. مش بديل عن دراسة جدوى "
        "مالية بأسعار السوق وتكاليف الأرض والتمويل والتسويق.\n"
        if ar else
        "\n---\n\n> A **schematic** study based on geometry only. Not a substitute "
        "for a financial feasibility study with market prices, land cost, finance "
        "and marketing.\n"
    )
    return "".join(p)
