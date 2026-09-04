"""البدائل بالنيّة — أ-4 · Intent-driven alternatives.

`--alternatives 2` كان بيدّي **نفس البرنامج** بترتيب هندسي مختلف. مش بدائل
تصميمية — العميل بياخد «بديل 1، بديل 2» ومش عارف يفاضل على أساس إيه.

هنا بنطلب من الموديل K برامج تحت **أطروحات تصميمية مختلفة صراحةً**، بنحلّهم
كلهم بالمحرك، وبعدين استدعاء أخير بيكتب المقارنة بالأرقام الحقيقية.

النتيجة: «مساحة معيشة أوسع» مقابل «خصوصية أعلى للنوم» — قرار العميل يقدر ياخده.
"""

from __future__ import annotations

import logging

from ..models import DesignRequest, Layout
from .client import AIUnavailable, ask
from .schemas import AlternativeComparison, AlternativeSet, DesignThesis

log = logging.getLogger("celestai.ai.alternatives")

GENERATE_SYSTEM = """You are generating genuinely DIFFERENT design options inside \
CelestAI, for the same plot and the same client brief.

Each option must be a distinct architectural THESIS, not a rearrangement. A thesis is \
a stated priority that costs something else. Examples of real theses:
  - generous living: one large open day zone, bedrooms trimmed to the minimum
  - private night zone: bedrooms pushed deep and buffered, day zone compact
  - low plumbing cost: every wet room stacked in one strip, fewer bathrooms
  - work from home: a real study with a door, taken from the second bedroom
  - family kitchen: kitchen enlarged and opened to dining, formal reception dropped

## Hard requirements (same for every option)
1. Sum of `target_area` in EACH option MUST equal the usable area given, within 1%.
2. Exactly one circulation hub, first in the room list.
3. Respect minimum areas and widths. An option that violates the code is not an option.
4. Never drop the last bathroom or the last kitchen.
5. Options must differ in ROOM COUNT, ROOM MIX, or AREA DISTRIBUTION — not just names. \
If two options would produce nearly the same plan, replace one.
6. Honour the client's explicit requests in every option; the thesis governs the \
trade-offs, not the requirements.
7. `title_ar`/`idea_ar` in natural Egyptian Arabic. `idea_*` must name what is gained \
AND what is given up, in one sentence.
8. `design_notes` in {notes_language}."""

COMPARE_SYSTEM = """You are writing the comparison that helps a client choose between \
design options produced by CelestAI.

You are given, for each option, the stated thesis AND the real measured numbers from \
the geometry engine (areas, efficiency, code violations, room dimensions).

Rules:
- Use the MEASURED numbers, not the promises. If an option promised a generous living \
room and the engine produced 17 m², say 17 m².
- For each option write two sentences: what it actually gains, and what it actually \
costs. No marketing.
- Recommend one option and say WHO it suits ("لو عندكم ضيوف كتير…"), not that it is \
objectively best.
- If an option came out worse than its thesis promised, say so.
- Natural Egyptian Arabic."""


def generate_alternatives(
    req: DesignRequest,
    usable_area: float,
    plot_w: float,
    plot_d: float,
    count: int = 3,
) -> list[DesignThesis]:
    """يطلب K برامج بأطروحات مختلفة. بيرجّع [] لو الـ AI مش متاح."""
    notes_lang = "English" if req.lang_key == "en" else "Egyptian Arabic"
    system = GENERATE_SYSTEM.replace("{notes_language}", notes_lang)

    parts = [
        "## Brief",
        f"- Building type: {req.building_type.value}",
        f"- Plot: {plot_w:.2f} m x {plot_d:.2f} m",
        f"- Usable area per option: {usable_area:.2f} m²",
    ]
    if req.bedrooms is not None:
        parts.append(f"- Bedrooms requested: {req.bedrooms}")
    if req.bathrooms is not None:
        parts.append(f"- Bathrooms requested: {req.bathrooms}")
    if req.brief.strip():
        parts.append(f"\n## Client's own words\n{req.brief.strip()}")
    parts.append(f"\nProduce exactly {count} options with distinct theses.")

    try:
        result = ask(
            system, "\n".join(parts), AlternativeSet,
            task="alternatives", max_tokens=20000,
        )
    except AIUnavailable as exc:
        log.info("توليد البدائل مش متاح: %s", exc)
        return []
    return result.options[:count]


def compare_alternatives(
    req: DesignRequest,
    solved: list[tuple[DesignThesis, Layout]],
) -> AlternativeComparison | None:
    """مقارنة مكتوبة بالأرقام الحقيقية بعد ما المحرك حلّ كل بديل."""
    if len(solved) < 2:
        return None

    blocks = []
    for thesis, layout in solved:
        m = layout.metrics
        rooms = ", ".join(
            f"{r.name_en or r.spec_id} {r.net_area:.1f}m²"
            for r in sorted(layout.rooms, key=lambda r: -r.net_area)[:7]
        )
        blocks.append(
            f"### {thesis.slug} — {thesis.title_en or thesis.title_ar}\n"
            f"Stated thesis: {thesis.idea_en or thesis.idea_ar}\n"
            f"Measured: net {m.get('net_area', 0):.1f} m², "
            f"efficiency {m.get('efficiency', 0) * 100:.1f}%, "
            f"circulation {m.get('circulation_share', 0) * 100:.1f}%, "
            f"{int(m.get('errors', 0))} violations, "
            f"{int(m.get('warnings', 0))} warnings, "
            f"{int(m.get('rooms', 0))} spaces\n"
            f"Rooms: {rooms}\n"
        )

    try:
        return ask(
            COMPARE_SYSTEM,
            "Compare these options for the client.\n\n" + "\n".join(blocks),
            AlternativeComparison,
            task="compare", max_tokens=6000,
        )
    except AIUnavailable as exc:
        log.info("مقارنة البدائل مش متاحة: %s", exc)
        return None


def comparison_markdown(
    comparison: AlternativeComparison,
    solved: list[tuple[DesignThesis, Layout]],
    language: str = "ar",
) -> str:
    ar = language != "en"
    p: list[str] = []
    p.append("## البدائل\n" if ar else "## Design options\n")

    verdict = comparison.verdict_ar if ar else (
        comparison.verdict_en or comparison.verdict_ar
    )
    if verdict:
        p.append(f"\n{verdict}\n")

    per = comparison.per_option_ar if ar else (
        comparison.per_option_en or comparison.per_option_ar
    )

    p.append(
        "\n| البديل | الفكرة | صافي | كفاءة | مخالفات |\n" if ar
        else "\n| Option | Idea | Net | Efficiency | Violations |\n"
    )
    p.append("|---|---|---|---|---|\n")
    for thesis, layout in solved:
        m = layout.metrics
        star = " ⭐" if thesis.slug == comparison.recommendation_slug else ""
        title = (thesis.title_ar if ar else thesis.title_en) + star
        idea = thesis.idea_ar if ar else (thesis.idea_en or thesis.idea_ar)
        p.append(
            f"| **{title}** | {idea} | {m.get('net_area', 0):.1f} م² | "
            f"{m.get('efficiency', 0) * 100:.1f}% | {int(m.get('errors', 0))} |\n"
        )

    for thesis, _layout in solved:
        text = per.get(thesis.slug)
        if text:
            p.append(f"\n### {thesis.title_ar if ar else thesis.title_en}\n\n{text}\n")
    return "".join(p)
