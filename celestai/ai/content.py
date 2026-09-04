"""مولّدات المحتوى — د-3 المواصفات · د-1 سرد التكلفة · د-2 سرد الشمس ·
هـ-1 سرد الجدوى · و-4 التعريب.

كل الدوال هنا **اختيارية بالكامل**: لو الـ AI مش متاح، الأرقام والجداول بتفضل
موجودة كاملة من الحساب الحتمي — اللي بيضيع هو السرد بس، مش المحتوى.
"""

from __future__ import annotations

import logging

from ..models import DesignRequest, Layout
from .client import AIUnavailable, ask
from .schemas import (
    CostNarrative,
    FeasibilityAdvice,
    FinishSchedule,
    SolarAdvice,
    TranslationBundle,
)

log = logging.getLogger("celestai.ai.content")


# ---------------------------------------------------------------------------
# د-3 · المواصفات والتشطيبات
# ---------------------------------------------------------------------------

TIERS = {
    "economy": ("اقتصادي", "Economy"),
    "standard": ("متوسط", "Standard"),
    "premium": ("فاخر", "Premium"),
}

FINISH_SYSTEM = """You are writing a finishes schedule for a schematic floor plan \
produced by CelestAI, for a project in Egypt / the Arab region.

Rules:
1. Specify by SPECIFICATION, not brand. "بورسلين 60×60 مضاد للانزلاق" not a brand name.
2. Match the budget tier honestly. Economy means economy — do not quietly upgrade.
3. Wet rooms get wall tiling to a stated height; dry rooms get skirting.
4. Kitchens and bathrooms need slip resistance — say the class.
5. Note anything the plan itself makes necessary (e.g. a room with limited daylight \
needs lighter finishes).
6. Do NOT give prices. Pricing comes from a separate priced bill of quantities.
7. Natural Egyptian Arabic in the *_ar fields, correct construction English in *_en."""


def finishes_schedule(
    layout: Layout, req: DesignRequest, tier: str = "standard"
) -> FinishSchedule | None:
    tier_ar, tier_en = TIERS.get(tier, TIERS["standard"])
    rooms = "\n".join(
        f"  - {r.spec_id} ({r.kind.value}) \"{r.name_en or r.name_ar}\": "
        f"{r.net_area:.2f} m²"
        + ("" if r.has_window else ", no external window")
        for r in layout.rooms
    )
    try:
        return ask(
            FINISH_SYSTEM,
            f"## Budget tier\n{tier_en}\n\n## Spaces\n{rooms}\n\n"
            f"Write the finishes schedule. tier_ar must be \"{tier_ar}\".",
            FinishSchedule, task="finishes", max_tokens=10000,
        )
    except AIUnavailable as exc:
        log.info("جدول التشطيبات مش متاح: %s", exc)
        return None


def finishes_markdown(schedule: FinishSchedule, language: str = "ar") -> str:
    ar = language != "en"
    p = ["## المواصفات والتشطيبات\n" if ar else "## Finishes schedule\n"]
    tier = schedule.tier_ar if ar else (schedule.tier_en or schedule.tier_ar)
    if tier:
        p.append(f"\n**{'الفئة' if ar else 'Tier'}:** {tier}\n")

    p.append("\n| الفراغ | الأرضية | الحوائط | السقف |\n" if ar
             else "\n| Space | Floor | Walls | Ceiling |\n")
    p.append("|---|---|---|---|\n")
    for r in schedule.rooms:
        p.append(
            f"| {r.room_id} | {r.floor_ar if ar else r.floor_en} | "
            f"{r.walls_ar if ar else r.walls_en} | "
            f"{r.ceiling_ar if ar else r.ceiling_en} |\n"
        )

    general = schedule.general_ar if ar else (
        schedule.general_en or schedule.general_ar
    )
    if general:
        p.append("\n### ملاحظات عامة\n" if ar else "\n### General notes\n")
        for g in general:
            p.append(f"- {g}\n")
    p.append(
        "\n> مواصفات مبدئية بدون أسعار — الأسعار في حصر الكميات.\n" if ar
        else "\n> Schematic specification, no prices — pricing is in the BoQ.\n"
    )
    return "".join(p)


# ---------------------------------------------------------------------------
# د-1 · سرد التكلفة
# ---------------------------------------------------------------------------

COST_SYSTEM = """You are writing the narrative around a bill of quantities computed \
by CelestAI directly from a floor plan's geometry.

Critical rules:
1. **Never state a price the data does not contain.** If the BoQ is unpriced, do not \
guess rates, do not cite "typical market prices", do not give any figure. Talk about \
quantities and drivers only.
2. Quantities are EXACT (computed from wall lengths, room areas, opening counts). Say \
so — it is the strongest thing about this estimate.
3. List the real assumptions (waste factor, floor height, what is excluded: \
foundations, land, finishes beyond the listed items, fees).
4. `savings_*`: cost-reduction opportunities visible IN THIS SPECIFIC PLAN — e.g. wet \
rooms already stacked, or an unusually long internal wall run. Not generic advice.
5. Natural Egyptian Arabic."""


def cost_narrative(boq, layout: Layout, req: DesignRequest) -> CostNarrative | None:
    items = "\n".join(
        f"  - {i.name_en} ({i.code}): {i.quantity:,.2f} {i.unit_en}"
        + (f" @ {i.unit_rate}" if i.unit_rate is not None else "")
        for i in boq.items
    )
    wet = [r.name_en or r.spec_id for r in layout.rooms if r.is_wet]
    status = (
        f"PRICED in {boq.currency}, subtotal {boq.subtotal:,.2f}"
        if boq.priced else "UNPRICED — no price book supplied"
    )
    try:
        return ask(
            COST_SYSTEM,
            f"## Status\n{status}\n\n## Quantities\n{items}\n\n"
            f"## Wet rooms\n{', '.join(wet) or 'none'}\n\n"
            f"## Plan\n{layout.plot.w:.2f} x {layout.plot.h:.2f} m, "
            f"{layout.metrics.get('net_area', 0):.1f} m² net, "
            f"{int(layout.metrics.get('rooms', 0))} spaces\n\n"
            "Write the narrative.",
            CostNarrative, task="cost", max_tokens=6000,
        )
    except AIUnavailable as exc:
        log.info("سرد التكلفة مش متاح: %s", exc)
        return None


def cost_narrative_markdown(n: CostNarrative, language: str = "ar") -> str:
    ar = language != "en"
    p: list[str] = []
    summary = n.summary_ar if ar else (n.summary_en or n.summary_ar)
    if summary:
        p.append(f"\n{summary}\n")
    assumptions = n.assumptions_ar if ar else (n.assumptions_en or n.assumptions_ar)
    if assumptions:
        p.append("\n### الافتراضات\n" if ar else "\n### Assumptions\n")
        for a in assumptions:
            p.append(f"- {a}\n")
    savings = n.savings_ar if ar else (n.savings_en or n.savings_ar)
    if savings:
        p.append("\n### فرص التوفير في المخطط ده\n" if ar
                 else "\n### Savings opportunities in this plan\n")
        for s in savings:
            p.append(f"- {s}\n")
    return "".join(p)


# ---------------------------------------------------------------------------
# د-2 · سرد التحليل الشمسي
# ---------------------------------------------------------------------------

SOLAR_SYSTEM = """You are interpreting a solar exposure analysis computed by CelestAI \
using real solar geometry for the project's latitude. The numbers are facts — you \
explain them and recommend actions.

Rules:
1. In a hot climate the SUMMER load governs, not winter gain. A west-facing bedroom is \
the classic failure: low afternoon sun strikes horizontally, penetrates deep, and the \
air is already hot.
2. Recommend REAL architectural measures with the right geometry: horizontal shading \
(كاسر أفقي) works on south façades because the summer sun is high; vertical fins \
(كاسر رأسي) are what west façades need. Do not mix them up.
3. Do not recommend moving rooms — the plan is already solved. Recommend what can be \
done to THIS plan: shading, glazing size, glass type, planting.
4. If the orientation is already good, say so briefly and stop. Do not manufacture \
problems.
5. Natural Egyptian Arabic."""


def solar_advice(report, language: str = "ar") -> SolarAdvice | None:
    windows = "\n".join(
        f"  - {w.room_name_en or w.room_id} ({w.kind.value}): {w.facade}-facing, "
        f"{w.area:.2f} m² glass, summer {w.summer_wh:,.0f} Wh/m², "
        f"winter {w.winter_wh:,.0f} Wh/m², severity={w.severity}"
        for w in report.windows
    )
    try:
        return ask(
            SOLAR_SYSTEM,
            f"## Location\n{report.city_en}, latitude {report.latitude:.2f}°\n\n"
            f"## Summer load index\n{report.summer_load_index:.3f} "
            "(0 = excellent, >0.6 = problematic)\n\n"
            f"## Windows\n{windows or '  (none)'}\n\n"
            "Interpret and recommend.",
            SolarAdvice, task="solar", max_tokens=6000,
        )
    except AIUnavailable as exc:
        log.info("سرد التحليل الشمسي مش متاح: %s", exc)
        return None


# ---------------------------------------------------------------------------
# هـ-1 · سرد الجدوى
# ---------------------------------------------------------------------------

FEASIBILITY_SYSTEM = """You are advising a developer on a schematic feasibility study \
produced by CelestAI. Every scenario in front of you was actually solved by the \
geometry engine — units, core, light wells and code review are all real, measured \
numbers, not projections.

Rules:
1. Recommend ONE scenario and say WHO it suits and under what assumption \
("لو السوق عندك طالب شقق صغيرة…"). Never claim one is objectively best.
2. Use the measured numbers. If a scenario has more units but more violations, say the \
trade-off explicitly.
3. `risk_*` must be a real risk of THAT scenario (absorption, unit size vs market, \
code violations needing redesign, height/lift cost) — not a generic disclaimer.
4. Be explicit that this is geometry-only: no land cost, no finance, no marketing, no \
market prices. It cannot tell anyone whether a project is profitable.
5. Natural Egyptian Arabic."""


def feasibility_advice(study, language: str = "ar") -> FeasibilityAdvice | None:
    rows = "\n".join(
        f"  - {s.scenario_id} \"{s.label_en}\": {s.total_units} units, "
        f"{s.sellable_area:,.0f} m² sellable, {s.efficiency * 100:.1f}% efficiency, "
        f"{s.errors} violations, {s.warnings} warnings, {s.height:.1f} m tall"
        + (f", cost {s.cost_low:,.0f}–{s.cost_high:,.0f}" if s.cost_low else "")
        for s in study.scenarios if not s.failed
    )
    if not rows:
        return None
    try:
        return ask(
            FEASIBILITY_SYSTEM,
            f"## Plot floor plate\n{study.plot_area:.0f} m²\n\n"
            f"## Scenarios (all solved by the engine)\n{rows}\n\n"
            "Recommend one and give verdicts for the top few.",
            FeasibilityAdvice, task="feasibility", max_tokens=8000,
        )
    except AIUnavailable as exc:
        log.info("سرد الجدوى مش متاح: %s", exc)
        return None


# ---------------------------------------------------------------------------
# و-4 · التعريب
# ---------------------------------------------------------------------------

LOCALISE_SYSTEM = """You are translating the UI of CelestAI, an architectural \
floor-plan tool, into a new language.

Rules:
1. Use correct ARCHITECTURAL terminology in the target language, not literal \
translation. "Reception" here is the central circulation space of an apartment; \
"Light well" is a specific building element; "Efficiency" is net-to-gross ratio.
2. Keep translations SHORT — these are UI labels and buttons, and long strings break \
the layout. Match the source length where you can.
3. Keep placeholders, punctuation and any markup exactly as they are.
4. `glossary_notes`: list every term you are NOT confident about, with your reasoning. \
A human must review these before the language ships.
5. Set `direction` correctly (rtl for Arabic, Hebrew, Persian, Urdu; ltr otherwise)."""


def translate_ui(
    strings: dict[str, str], language_code: str, language_name: str
) -> TranslationBundle | None:
    """يترجم قاموس الواجهة. الناتج **مسوّدة محتاجة مراجعة بشرية.**"""
    try:
        return ask(
            LOCALISE_SYSTEM,
            f"Target language: {language_name} ({language_code})\n\n"
            "Translate these UI strings. Keep the same keys:\n"
            + "\n".join(f"  {k}: {v}" for k, v in strings.items()),
            TranslationBundle, task="localise", max_tokens=16000,
        )
    except AIUnavailable as exc:
        log.info("الترجمة مش متاحة: %s", exc)
        return None
