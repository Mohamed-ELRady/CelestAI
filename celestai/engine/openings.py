"""توليد الأبواب والشبابيك — Door & window placement."""

from __future__ import annotations

from collections import defaultdict

from ..knowledge import (
    DOOR_ENTRY_WIDTH,
    DOOR_MIN_CLEAR,
    DOOR_HEIGHT,
    SHAFT_WINDOW_HEIGHT,
    SHAFT_WINDOW_SILL,
    UNROOFED,
    WINDOW_HEIGHT,
    WINDOW_HEIGHT_WET,
    WINDOW_MAX_EDGE_RATIO,
    WINDOW_MIN_WIDTH,
    WINDOW_SILL,
    WINDOW_SILL_WET,
    door_width,
    required_glazing,
)
from ..models import Opening, RoomKind
from .layout import CanonicalPlan

CORNER_MARGIN = 0.28
DOOR_CLEARANCE = 0.30


# ---------------------------------------------------------------------------
# الأبواب
# ---------------------------------------------------------------------------


def _door_span(
    lo: float, hi: float, dw: float, prefer_start: bool = True
) -> tuple[float, float] | None:
    """يرجّع (البداية، العرض) للباب على الحائط، أو None لو الحائط ضيّق أوي.

    لو الحائط أضيق من الباب القياسي بنضيّق الباب لحد الحد الأدنى الكودي بدل
    ما نسيب الفراغ من غير مدخل.
    """
    span = hi - lo
    if span < DOOR_MIN_CLEAR + 0.12:
        return None
    w = min(dw, span - 0.12)
    if span >= w + 2 * DOOR_CLEARANCE and prefer_start:
        return lo + DOOR_CLEARANCE, w
    return lo + (span - w) / 2, w


def canonical_doors(plan: CanonicalPlan) -> list[Opening]:
    doors: list[Opening] = []
    hub = plan.hub

    # باب المدخل الرئيسي على واجهة المدخل داخل عرض الفراغ المركزي
    entry_w = min(DOOR_ENTRY_WIDTH, plan.hub_w - 0.3)
    doors.append(
        Opening(
            kind="entry",
            axis="h",
            coord=0.0,
            start=plan.hub_x + (plan.hub_w - entry_w) / 2,
            width=entry_w,
            room_id=hub.id,
            swing=1,
            hinge=1,
            height=DOOR_HEIGHT,
        )
    )

    by_id = {p.spec.id: p for p in plan.placements}

    for pl in plan.placements:
        spec = pl.spec
        if spec.id == hub.id:
            continue
        if spec.kind == RoomKind.SHAFT:
            continue        # المنور مش فراغ بيتدخله — بيتخدم بشباك بس

        dw = door_width(spec.kind)

        # (أ) فراغ ملحق (حمام داخل غرفة نوم) → باب على الحائط المشترك مع الغرفة الأم
        if spec.attach_to and spec.attach_to in by_id:
            parent = by_id[spec.attach_to]
            shared_y = pl.y if abs(pl.y - (parent.y + parent.h)) < 1e-4 else pl.y + pl.h
            swing = 1 if shared_y <= pl.y + 1e-4 else -1
            span = _door_span(pl.x, pl.x + pl.w, dw, prefer_start=False)
            if span is not None:
                doors.append(
                    Opening(
                        kind="door", axis="h", coord=shared_y, start=span[0], width=span[1],
                        room_id=spec.id, swing=swing, hinge=1, height=DOOR_HEIGHT,
                    )
                )
            continue

        # (ب) غرف الشريط الطرفي → باب على نهاية الفراغ المركزي، داخل التداخل
        #     بين عرض الغرفة وعرض الفراغ المركزي
        if spec.id in plan.terminal_ids:
            lo = max(pl.x, plan.hub_x)
            hi = min(pl.x + pl.w, plan.hub_x + plan.hub_w)
            span = _door_span(lo, hi, dw, prefer_start=False)
            if span is not None:
                doors.append(
                    Opening(
                        kind="door", axis="h", coord=plan.hub_len, start=span[0],
                        width=span[1], room_id=spec.id, swing=1, hinge=1, height=DOOR_HEIGHT,
                    )
                )
            continue

        # (ج) غرف الشرائط → باب على الحائط المشترك مع الفراغ المركزي
        left_side = pl.x + pl.w <= plan.hub_x + 1e-4
        coord = plan.hub_x if left_side else plan.hub_x + plan.hub_w
        swing = -1 if left_side else 1
        span = _door_span(pl.y, pl.y + pl.h, dw)
        if span is not None:
            doors.append(
                Opening(
                    kind="door", axis="v", coord=coord, start=span[0], width=span[1],
                    room_id=spec.id, swing=swing, hinge=1, height=DOOR_HEIGHT,
                )
            )

    return doors


# ---------------------------------------------------------------------------
# الشبابيك
# ---------------------------------------------------------------------------


def _free_intervals(
    span: tuple[float, float], used: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    lo, hi = span[0] + CORNER_MARGIN, span[1] - CORNER_MARGIN
    if hi <= lo:
        return []
    blocks = sorted(
        (max(a - 0.20, lo), min(b + 0.20, hi))
        for a, b in used
        if b > lo and a < hi
    )
    out: list[tuple[float, float]] = []
    cursor = lo
    for a, b in blocks:
        if a > cursor:
            out.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < hi:
        out.append((cursor, hi))
    return [iv for iv in out if iv[1] - iv[0] >= WINDOW_MIN_WIDTH]


#: ضلع صالح لشباك: (المحور، الإحداثي، من، إلى، ارتفاع الشباك، منسوب الشبّاك)
Edge = tuple[str, float, float, float, float, float]


def _shaft_edges(pl, shafts, h_win: float, sill: float) -> list[Edge]:
    """الأضلاع المشتركة بين الفراغ ومنور — كل واحد منها بياخد شباك تهوية."""
    out: list[Edge] = []
    for s in shafts:
        oy = min(pl.y + pl.h, s.y + s.h) - max(pl.y, s.y)
        ox = min(pl.x + pl.w, s.x + s.w) - max(pl.x, s.x)
        if oy >= WINDOW_MIN_WIDTH and ox <= 1e-4:      # ملاصقة رأسية
            lo, hi = max(pl.y, s.y), min(pl.y + pl.h, s.y + s.h)
            coord = pl.x if abs(pl.x - (s.x + s.w)) < 1e-4 else pl.x + pl.w
            out.append(("v", coord, lo, hi, h_win, sill))
        elif ox >= WINDOW_MIN_WIDTH and oy <= 1e-4:    # ملاصقة أفقية
            lo, hi = max(pl.x, s.x), min(pl.x + pl.w, s.x + s.w)
            coord = pl.y if abs(pl.y - (s.y + s.h)) < 1e-4 else pl.y + pl.h
            out.append(("h", coord, lo, hi, h_win, sill))
    return out


def canonical_windows(
    plan: CanonicalPlan, doors: list[Opening]
) -> list[Opening]:
    used: dict[tuple[str, float], list[tuple[float, float]]] = defaultdict(list)
    for d in doors:
        used[(d.axis, round(d.coord, 4))].append((d.start, d.end))

    windows: list[Opening] = []
    shafts = [p for p in plan.placements if p.spec.kind == RoomKind.SHAFT]

    for pl in plan.placements:
        spec = pl.spec
        if spec.kind in UNROOFED:
            continue

        need_area = required_glazing(spec.kind, pl.w * pl.h)
        if need_area <= 0:
            continue

        wet = spec.is_wet
        h_win = WINDOW_HEIGHT_WET if wet else WINDOW_HEIGHT
        sill = WINDOW_SILL_WET if wet else WINDOW_SILL

        # الأضلاع اللي على محيط الوحدة *ومطلّة على الخارج فعلًا*. الضلع اللي على
        # حائط مشترك مع وحدة تانية بيبقى على المحيط بس مش بياخد شبابيك.
        edges: list[Edge] = []
        if "left" in plan.exterior and abs(pl.x) < 1e-4:
            edges.append(("v", 0.0, pl.y, pl.y + pl.h, h_win, sill))
        if "right" in plan.exterior and abs(pl.x + pl.w - plan.wc) < 1e-4:
            edges.append(("v", plan.wc, pl.y, pl.y + pl.h, h_win, sill))
        if "front" in plan.exterior and abs(pl.y) < 1e-4:
            edges.append(("h", 0.0, pl.x, pl.x + pl.w, h_win, sill))
        if "back" in plan.exterior and abs(pl.y + pl.h - plan.dc) < 1e-4:
            edges.append(("h", plan.dc, pl.x, pl.x + pl.w, h_win, sill))

        # الواجهة الحقيقية بتيجي الأول، والمنور بيكمّل اللي ناقص
        edges.sort(key=lambda e: e[3] - e[2], reverse=True)
        edges += _shaft_edges(pl, shafts, SHAFT_WINDOW_HEIGHT, SHAFT_WINDOW_SILL)

        # بنتابع المساحة الزجاجية الناقصة مش عرضها، لأن شباك المنور أقصر من
        # شباك الواجهة فبياخد عرض أكبر عشان يدّي نفس المساحة
        remaining = need_area
        for axis, coord, lo, hi, eh, esill in edges:
            if remaining <= 0.12:
                break
            key = (axis, round(coord, 4))
            for a, b in _free_intervals((lo, hi), used[key]):
                if remaining <= 0.12:
                    break
                w = min(remaining / eh, (hi - lo) * WINDOW_MAX_EDGE_RATIO, b - a)
                if w < WINDOW_MIN_WIDTH:
                    continue
                start = a + (b - a - w) / 2
                windows.append(
                    Opening(
                        kind="window", axis=axis, coord=coord, start=round(start, 4),
                        width=round(w, 4), room_id=spec.id, sill=esill, height=eh,
                    )
                )
                used[key].append((start, start + w))
                remaining -= w * eh

        # فراغ من غير أي شباك: نفتح أصغر فتحة ممكنة عشان تفضل فيه تهوية،
        # وباقي النقص بيتسجّل مخالفة في المراجعة الكودية
        if not any(w.room_id == spec.id for w in windows) and edges:
            axis, coord, lo, hi, eh, esill = edges[0]
            w = min(WINDOW_MIN_WIDTH, (hi - lo) * 0.5)
            if w >= 0.4:
                start = lo + (hi - lo - w) / 2
                windows.append(
                    Opening(
                        kind="window", axis=axis, coord=coord, start=round(start, 4),
                        width=round(w, 4), room_id=spec.id, sill=esill, height=eh,
                    )
                )

    return windows


def canonical_openings(plan: CanonicalPlan) -> list[Opening]:
    doors = canonical_doors(plan)
    return doors + canonical_windows(plan, doors)
