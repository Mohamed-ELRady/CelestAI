"""نصوص التوجيه للمُخطِّط المعماري — System prompts for the architectural planner."""

from __future__ import annotations

from ..knowledge import STANDARDS
from ..models import ArchitecturalProgram, DesignRequest
from ..ai.cache import compact_json


def _standards_table() -> str:
    lines = ["| kind | min_area | ideal_area | min_width | zone |", "|---|---|---|---|---|"]
    for kind, st in STANDARDS.items():
        lines.append(
            f"| {kind.value} | {st.min_area} | {st.ideal_area} | {st.min_width} | {st.zone.value} |"
        )
    return "\n".join(lines)


SYSTEM = f"""You are the architectural programming engine inside CelestAI, a tool that turns \
a plot area into a buildable floor plan. You do NOT draw. You produce the *program*: the list of \
spaces, their target areas, and their relationships. A deterministic geometry engine downstream \
packs your program into the plot, so your numbers must be internally consistent and buildable.

## Hard requirements
1. The sum of `target_area` across all rooms MUST equal the usable area given in the brief \
(within 1%). The geometry engine fills the plot completely — leftover area has nowhere to go.
2. Exactly ONE room must be the circulation hub (kind `reception`, `waiting`, or `corridor`). \
Every other room opens directly onto it. Give it {{hub_share}} of the total area.
3. Respect the minimum areas and minimum widths in the standards table. A room below its minimum \
is a code violation, not a design choice.
4. `min_width` is the shortest dimension the room can tolerate. The engine will honour it, so an \
unrealistically large value on a small room makes the plan fail.
5. Wet rooms (`kitchen`, `bath`, `wc`, `laundry`, `pantry`) should be listed adjacent to each \
other in the `adjacency` list so plumbing runs stay short.
6. Use `attach_to` ONLY for an en-suite bathroom that opens off a bedroom instead of the hub. \
The parent must be a bedroom listed in the same program.
7. `id` must be a unique lowercase ASCII slug. `name_ar` must be correct Arabic architectural \
terminology (صالة، معيشة، سفرة، غرفة نوم رئيسية، مطبخ، حمام، دورة مياه، بلكونة).

## Design judgement expected of you
- Read the free-text brief carefully and honour explicit requests (room counts, "مكتب في البيت", \
"مطبخ أمريكاني", "مساحة تخزين كبيرة").
- Size rooms to the *use*, not evenly. A master bedroom carries more area than a kids' room.
- On tight areas, cut room count before cutting room quality — a cramped 3-bedroom is worse than a \
comfortable 2-bedroom.
- Put day-zone spaces (living, dining, kitchen) near the entrance and night-zone spaces deeper in.
- Write `design_notes` in {{notes_language}}: 3–5 concrete decisions you made and why — the
  trade-offs a client would want explained, not a restatement of the room list.

## Standards table (metres, m²)
{_standards_table()}
"""


def openai_schema_suffix() -> str:
    """تعليمات شكل الرد لمزوّدي OpenAI-compatible.

    Anthropic بيضمن الـ structured output تلقائيًا عن طريق `messages.parse`، لكن مفيش
    ضمان مماثل لأي مزوّد تاني (Groq وغيره)، فبنحط شكل الـ JSON صراحة في البرومبت
    ونتحقق من الرد بعدين بـ Pydantic في `ai.py`.
    """
    schema = compact_json(ArchitecturalProgram.model_json_schema())
    return (
        "\n\n## Output format (STRICT — this overrides everything above about format)\n"
        "Respond with ONLY a single JSON object. No markdown code fences, no prose "
        "before or after it, no explanation — just the raw JSON object starting with "
        "`{` and ending with `}`. It must validate against this JSON Schema:\n"
        f"{schema}\n"
    )


def user_prompt(req: DesignRequest, usable_area: float, plot_w: float, plot_d: float) -> str:
    """يبني رسالة المستخدم من الطلب."""
    parts = [
        "## Brief",
        f"- Building type: {req.building_type.value}",
        f"- Plot: {plot_w:.2f} m × {plot_d:.2f} m",
        f"- Usable area to allocate: {usable_area:.2f} m² (the sum of target_area must equal this)",
        f"- Entry from the {req.entry_side} side" if req.entry_side != "auto"
        else "- Entry side: engine will choose the best",
    ]
    if req.bedrooms is not None:
        parts.append(f"- Bedrooms requested: {req.bedrooms}")
    if req.bathrooms is not None:
        parts.append(f"- Bathrooms requested: {req.bathrooms}")
    if req.receptions is not None:
        parts.append(f"- Reception/living spaces requested: {req.receptions}")
    if req.brief.strip():
        parts.append(f"\n## Client's own words (may be Arabic)\n{req.brief.strip()}")

    notes_lang = "English" if req.lang_key == "en" else "Egyptian Arabic"
    parts.append(
        "\nProduce the architectural program now. Remember: sum of target_area = "
        f"{usable_area:.2f} m², exactly one circulation hub, `name_ar` in correct "
        f"Arabic and `name_en` in correct English, and `design_notes` written in "
        f"{notes_lang}."
    )
    return "\n".join(parts)
