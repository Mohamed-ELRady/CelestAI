"""المداخل البصرية — ب-1 · Sketch → Plan، ب-2 · Site document reading.

المعماري والعميل بيفكّروا برسمة على ورقة، مش بفورم فيه خانات. والمشروع الحقيقي
بيبدأ من كروكي أرض أو رخصة، مش من عرض وعمق مكتوبين بالإيد.

**قاعدة أساسية في الملف ده: مفيش ثقة صامتة.** الرؤية بتغلط في المقاسات، والغلط
بيتسرّب لكل حاجة بعده. فكل قراءة بترجع معاها:
  • `confidence` صريحة
  • `read_back_*` — اللي الموديل فهمه، بلغة المستخدم، عشان يراجعه
  • `unreadable_*` — اللي مقدرش يقراه

والواجهة **لازم** تعرض دي للتأكيد قبل ما تستخدم أي رقم.
"""

from __future__ import annotations

import logging

from ..knowledge import STANDARDS
from ..models import ArchitecturalProgram, DesignRequest, RoomSpec
from .client import AIUnavailable, Image, ask, supports_vision
from .schemas import SiteReading, SketchReading

log = logging.getLogger("celestai.ai.vision")


def _kinds_list() -> str:
    return ", ".join(sorted(k.value for k in STANDARDS))


SKETCH_SYSTEM = f"""You are reading a hand-drawn architectural sketch, a bubble \
diagram, or a rough plan, inside CelestAI. You do NOT design and you do NOT measure \
precisely — you EXTRACT the intent so a deterministic engine can draw it properly.

## What to extract
- Every space you can identify, with the closest matching kind from: {_kinds_list()}
- Any dimensions or areas actually WRITTEN on the drawing (do not infer them)
- Which spaces are drawn touching or connected — that is the adjacency intent
- The entrance, if an arrow or a door is drawn
- Relative sizes (small / medium / large) as drawn

## Rules — these matter more than completeness
1. **Never invent a number.** If no dimension is written, leave `approx_area` null and \
use `relative_size` only. A guessed area is worse than no area.
2. Set `confidence` honestly. If the handwriting or the layout is unclear, say `low`.
3. Put anything you could not read into `unreadable_*` — do not silently skip it.
4. `read_back_*` is what the user will be shown to confirm. Write it as a plain list \
of what you saw, in natural Egyptian Arabic. Do not sell your reading.
5. If the image is not an architectural sketch at all, return zero rooms and say so \
in `unreadable_ar`."""


SITE_SYSTEM = """You are reading a site plan, a plot survey (كروكي), or a building \
permit sheet inside CelestAI, to prefill a design request.

## What to extract
plot width and depth (metres) · plot area · which sides face a street · setbacks \
(front / back / sides) · maximum permitted floors · floor-area ratio if stated

## Rules — this is legal/regulatory data, so the bar is higher
1. **Extract only what is explicitly written.** Never infer a setback or a floor limit \
from convention. Missing is fine; wrong is not.
2. If a number is written but ambiguous (unclear units, unclear which dimension), \
leave it null and describe the ambiguity in `unreadable_ar`.
3. Distinguish plot dimensions from building dimensions. If the sheet shows both, \
report the PLOT and note the other in `unreadable_ar`.
4. `confidence` must be `low` unless the sheet is clearly printed and unambiguous.
5. `read_back_*` in natural Egyptian Arabic — the user MUST confirm every value \
before it is used."""


def read_sketch(images: list[Image], language: str = "ar") -> SketchReading | None:
    """يقرأ اسكتش. بيرجّع None لو الرؤية مش متاحة."""
    if not supports_vision():
        return None
    lang = "Egyptian Arabic" if language != "en" else "English"
    try:
        return ask(
            SKETCH_SYSTEM,
            f"Read this sketch. Write read_back and unreadable in {lang}.",
            SketchReading,
            task="sketch", images=images, max_tokens=8000,
        )
    except AIUnavailable as exc:
        log.info("قراءة الاسكتش مش متاحة: %s", exc)
        return None


def read_site_document(images: list[Image], language: str = "ar") -> SiteReading | None:
    """يقرأ كروكي أرض أو رخصة. بيرجّع None لو الرؤية مش متاحة."""
    if not supports_vision():
        return None
    lang = "Egyptian Arabic" if language != "en" else "English"
    try:
        return ask(
            SITE_SYSTEM,
            f"Read this site document. Write read_back and unreadable in {lang}.",
            SiteReading,
            task="site", images=images, max_tokens=8000,
        )
    except AIUnavailable as exc:
        log.info("قراءة الكروكي مش متاحة: %s", exc)
        return None


# ---------------------------------------------------------------------------
# تحويل القراءة لمدخلات المشروع
# ---------------------------------------------------------------------------

_SIZE_WEIGHT = {"small": 0.6, "medium": 1.0, "large": 1.7}


def sketch_to_program(
    reading: SketchReading, usable_area: float
) -> ArchitecturalProgram | None:
    """يحوّل قراءة الاسكتش لبرنامج معماري بمساحات متسقة.

    المساحات المكتوبة في الاسكتش بتتحترم؛ الباقي بيتوزّع بالأحجام النسبية.
    التوزيع ده **حتمي** — مش بنرجع للموديل تاني.
    """
    if not reading.rooms:
        return None

    from ..knowledge import HABITABLE, WET_ROOMS, standard

    specs: list[RoomSpec] = []
    seen: set[str] = set()
    for i, r in enumerate(reading.rooms):
        st = standard(r.kind)
        rid = (r.name_en or r.kind.value).lower().replace(" ", "_")[:24] or f"space_{i}"
        while rid in seen:
            rid += "_x"
        seen.add(rid)
        specs.append(RoomSpec(
            id=rid,
            name_ar=r.name_ar or st.name_ar,
            name_en=r.name_en or st.name_en,
            kind=r.kind,
            target_area=max(r.approx_area or st.ideal_area, st.min_area),
            min_width=st.min_width,
            zone=st.zone,
            needs_window=r.kind in HABITABLE,
            is_wet=r.kind in WET_ROOMS,
            priority=2 if r.approx_area else 3,
        ))

    # نطبّع على المساحة المتاحة: المكتوب ثابت، والباقي بيتمدّد/يتقلّص
    fixed = sum(
        s.target_area for s, r in zip(specs, reading.rooms) if r.approx_area
    )
    flexible = [
        (s, _SIZE_WEIGHT.get(r.relative_size, 1.0))
        for s, r in zip(specs, reading.rooms) if not r.approx_area
    ]
    remaining = usable_area - fixed
    if flexible and remaining > 0:
        weight_total = sum(w for _s, w in flexible) or 1.0
        for spec, w in flexible:
            st = standard(spec.kind)
            spec.target_area = round(
                max(remaining * w / weight_total, st.min_area), 2
            )

    program = ArchitecturalProgram(rooms=specs, source="ai")

    # لازم فراغ توزيع مركزي واحد في الأول
    from ..planner.ai import HUB_KINDS

    hub = next((s for s in specs if s.kind in HUB_KINDS), None)
    if hub is None:
        hub = max(specs, key=lambda s: s.target_area)
        hub.kind = _default_hub()
        st = standard(hub.kind)
        hub.name_ar, hub.name_en, hub.zone = st.name_ar, st.name_en, st.zone
    program.rooms.remove(hub)
    program.rooms.insert(0, hub)

    ids = {s.id for s in specs}
    id_by_en = {s.name_en.lower(): s.id for s in specs}
    program.adjacency = [
        (id_by_en.get(a.lower(), a), id_by_en.get(b.lower(), b))
        for a, b in reading.adjacency
        if id_by_en.get(a.lower(), a) in ids and id_by_en.get(b.lower(), b) in ids
    ]
    return program


def _default_hub():
    from ..models import RoomKind
    return RoomKind.RECEPTION


def apply_site_reading(req: DesignRequest, reading: SiteReading) -> list[str]:
    """يطبّق قراءة الكروكي على الطلب بعد ما المستخدم أكّدها.

    بيرجّع قايمة باللي اتغيّر — عشان الواجهة تعرضها.
    الردود بتتخصم من القطعة، لأن المحرك بيبني على المساحة الصافية.
    """
    changed: list[str] = []
    w, d = reading.plot_width, reading.plot_depth

    if w and d:
        front = reading.setback_front or 0.0
        back = reading.setback_back or 0.0
        sides = reading.setback_sides or 0.0
        net_w = max(w - 2 * sides, 2.5)
        net_d = max(d - front - back, 2.5)
        req.width, req.depth = round(net_w, 2), round(net_d, 2)
        req.area = round(net_w * net_d, 2)
        changed.append(f"أبعاد البناء {net_w:.2f} × {net_d:.2f} م بعد خصم الردود")
    elif reading.plot_area:
        req.area = round(reading.plot_area, 2)
        changed.append(f"المساحة {req.area:.2f} م²")

    if reading.street_sides:
        req.exterior_sides = list(dict.fromkeys(reading.street_sides))  # type: ignore[assignment]
        changed.append("الواجهات: " + "، ".join(reading.street_sides))
        if req.entry_side == "auto":
            req.entry_side = reading.street_sides[0]  # type: ignore[assignment]
            changed.append(f"جهة المدخل: {req.entry_side}")

    return changed
