"""الفرش الذكي — د-4 · AI furniture layout.

`furniture.py` بيرسم رموز تخطيطية ثابتة: سرير في غرفة النوم، حوض في الحمام.
بتثبت إن الفراغ يستوعب الاستخدام، بس مش بتقول إذا كان الأثاث اللي المستخدم عايزه
هيدخل فعلًا.

نفس فلسفة المشروع بالظبط: **الموديل بينوي، والهندسة بتنفّذ وتتحقق.**
  • الـ AI بيقترح قايمة الأثاث وأبعاده وأولويته لكل فراغ
  • مُرصِّف **حتمي** بيحطّه محترمًا الخلوصات ودوران الأبواب والشبابيك
  • القطعة اللي مش لاقية مكان بترجع كـ«مش داخلة» — مش بتتحشر
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..models import Layout, Opening, PlacedRoom, Rect
from .client import AIUnavailable, ask
from .schemas import FurniturePlan, FurniturePiece

log = logging.getLogger("celestai.ai.furnish")

WALK_CLEARANCE = 0.75      # ممر حركة داخل الفراغ
DOOR_SWING_MARGIN = 0.15


SYSTEM = """You are specifying furniture for rooms in a schematic floor plan produced \
by CelestAI. You do NOT place the furniture — a deterministic packer does that, \
respecting clearances. You specify WHAT goes in and how big it is.

Rules:
1. Use REAL furniture dimensions in metres. A double bed is 1.60 x 2.00, a 3-seat sofa \
about 2.10 x 0.90, a 6-person dining table about 1.60 x 0.90, a wardrobe 0.60 deep.
2. Order by `priority`: 1 = the room is useless without it (bed, sofa, dining table), \
5 = nice to have. The packer drops low-priority pieces that do not fit.
3. `clearance` is the free space needed IN FRONT of the piece to use it: 0.75 m at a \
wardrobe, 0.90 m to pull out a dining chair, 0.60 m beside a bed.
4. `against`: "wall" for beds/sofas/wardrobes, "centre" for dining tables and islands, \
"corner" for corner units.
5. Do NOT over-furnish. A small room with three pieces beats one with seven that will \
not fit. Look at the given area before you specify.
6. Skip circulation spaces, balconies and light wells entirely.
7. Natural Egyptian Arabic names."""


@dataclass
class PlacedPiece:
    name_ar: str
    name_en: str
    rect: Rect
    room_id: str

    def as_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "name_ar": self.name_ar, "name_en": self.name_en,
            "x": round(self.rect.x, 3), "y": round(self.rect.y, 3),
            "w": round(self.rect.w, 3), "h": round(self.rect.h, 3),
        }


@dataclass
class FurnishResult:
    placed: list[PlacedPiece] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)   # (room, اسم)
    intents: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "placed": [p.as_dict() for p in self.placed],
            "dropped": [{"room_id": r, "name": n} for r, n in self.dropped],
            "intents": self.intents,
        }


# ---------------------------------------------------------------------------
# المُرصِّف الحتمي
# ---------------------------------------------------------------------------


def _blocked_zones(room: PlacedRoom, openings: list[Opening]) -> list[Rect]:
    """المناطق اللي مينفعش يتحط فيها أثاث: دوران الأبواب وتحت الشبابيك."""
    zones: list[Rect] = []
    n = room.net_rect
    for o in openings:
        if o.kind not in ("door", "entry", "window"):
            continue
        depth = (o.width + DOOR_SWING_MARGIN) if o.kind != "window" else 0.15
        if o.axis == "v":       # حائط رأسي: x ثابت
            if abs(o.coord - n.x) < 0.35:
                zones.append(Rect(x=n.x, y=o.start, w=depth, h=o.width))
            elif abs(o.coord - n.x2) < 0.35:
                zones.append(Rect(x=n.x2 - depth, y=o.start, w=depth, h=o.width))
        else:                   # حائط أفقي: y ثابت
            if abs(o.coord - n.y) < 0.35:
                zones.append(Rect(x=o.start, y=n.y, w=o.width, h=depth))
            elif abs(o.coord - n.y2) < 0.35:
                zones.append(Rect(x=o.start, y=n.y2 - depth, w=o.width, h=depth))
    return zones


def _overlaps(a: Rect, b: Rect, gap: float = 0.0) -> bool:
    return (
        a.x < b.x2 + gap and b.x < a.x2 + gap
        and a.y < b.y2 + gap and b.y < a.y2 + gap
    )


def _candidate_spots(room: PlacedRoom, piece: FurniturePiece) -> list[Rect]:
    """أماكن مرشّحة للقطعة، حسب `against`."""
    n = room.net_rect
    w, d = piece.width, piece.depth
    spots: list[Rect] = []

    if piece.against in ("wall", "corner", "any"):
        # على كل حائط، بالعرض وبالطول
        step = 0.25
        for (pw, pd) in ((w, d), (d, w)):
            if pw > n.w or pd > n.h:
                continue
            x = n.x
            while x + pw <= n.x2 + 1e-6:
                spots.append(Rect(x=round(x, 3), y=n.y, w=pw, h=pd))          # تحت
                spots.append(Rect(x=round(x, 3), y=n.y2 - pd, w=pw, h=pd))    # فوق
                x += step
            y = n.y
            while y + pd <= n.y2 + 1e-6:
                spots.append(Rect(x=n.x, y=round(y, 3), w=pw, h=pd))          # شمال
                spots.append(Rect(x=n.x2 - pw, y=round(y, 3), w=pw, h=pd))    # يمين
                y += step

    if piece.against in ("centre", "any"):
        if w <= n.w and d <= n.h:
            spots.append(Rect(x=n.cx - w / 2, y=n.cy - d / 2, w=w, h=d))
        if d <= n.w and w <= n.h:
            spots.append(Rect(x=n.cx - d / 2, y=n.cy - w / 2, w=d, h=w))

    return spots


def _fits(spot: Rect, room: PlacedRoom, taken: list[Rect], blocked: list[Rect],
          clearance: float) -> bool:
    n = room.net_rect
    if spot.x < n.x - 1e-6 or spot.y < n.y - 1e-6:
        return False
    if spot.x2 > n.x2 + 1e-6 or spot.y2 > n.y2 + 1e-6:
        return False
    for z in blocked:
        if _overlaps(spot, z):
            return False
    for t in taken:
        if _overlaps(spot, t, gap=0.05):
            return False
    # الخلوص: مساحة حرة قدام القطعة في اتجاه واحد على الأقل
    if clearance > 0.05:
        free = Rect(
            x=spot.x - clearance, y=spot.y - clearance,
            w=spot.w + 2 * clearance, h=spot.h + 2 * clearance,
        )
        overlap_area = 0.0
        for t in taken:
            ox = min(free.x2, t.x2) - max(free.x, t.x)
            oy = min(free.y2, t.y2) - max(free.y, t.y)
            if ox > 0 and oy > 0:
                overlap_area += ox * oy
        if overlap_area > free.area * 0.45:
            return False
    return True


def _walkable_after(room: PlacedRoom, taken: list[Rect]) -> bool:
    """الغرفة لسه فيها مساحة حركة معقولة؟"""
    used = sum(t.area for t in taken)
    return used <= room.net_area * 0.62


def pack_room(
    room: PlacedRoom, pieces: list[FurniturePiece], openings: list[Opening]
) -> tuple[list[PlacedPiece], list[str]]:
    """يحط الأثاث حتميًا. بيرجّع (المتحطّط، المرفوض)."""
    blocked = _blocked_zones(room, openings)
    taken: list[Rect] = []
    placed: list[PlacedPiece] = []
    dropped: list[str] = []

    for piece in sorted(pieces, key=lambda p: (p.priority, -p.width * p.depth)):
        spot = None
        for cand in _candidate_spots(room, piece):
            if _fits(cand, room, taken, blocked, piece.clearance):
                spot = cand
                break
        if spot is None or not _walkable_after(room, taken + [spot]):
            dropped.append(piece.name_ar or piece.name_en)
            continue
        taken.append(spot)
        placed.append(PlacedPiece(
            name_ar=piece.name_ar, name_en=piece.name_en or piece.name_ar,
            rect=spot, room_id=room.spec_id,
        ))
    return placed, dropped


# ---------------------------------------------------------------------------
# نقطة الدخول
# ---------------------------------------------------------------------------

SKIP_KINDS = {"corridor", "stair", "balcony", "shaft", "reception", "waiting"}


def furnish(layout: Layout, language: str = "ar") -> FurnishResult | None:
    """يفرش المخطط. None لو الـ AI مش متاح."""
    rooms = [r for r in layout.rooms if r.kind.value not in SKIP_KINDS]
    if not rooms:
        return None

    listing = "\n".join(
        f"  - {r.spec_id} ({r.kind.value}) \"{r.name_en or r.name_ar}\": "
        f"{r.net_rect.w:.2f} x {r.net_rect.h:.2f} m = {r.net_area:.2f} m²"
        for r in rooms
    )
    try:
        plan = ask(
            SYSTEM,
            f"## Rooms to furnish\n{listing}\n\n"
            "Specify furniture for each. Respect the areas — do not over-furnish.",
            FurniturePlan, task="furnish", max_tokens=12000,
        )
    except AIUnavailable as exc:
        log.info("الفرش الذكي مش متاح: %s", exc)
        return None

    by_id = {r.spec_id: r for r in rooms}
    result = FurnishResult()
    for rf in plan.rooms:
        room = by_id.get(rf.room_id)
        if room is None:
            continue
        placed, dropped = pack_room(room, rf.pieces, layout.openings)
        result.placed.extend(placed)
        result.dropped.extend((rf.room_id, name) for name in dropped)
        intent = rf.intent_ar if language != "en" else (rf.intent_en or rf.intent_ar)
        if intent:
            result.intents[rf.room_id] = intent
    return result


def furnish_markdown(result: FurnishResult, language: str = "ar") -> str:
    ar = language != "en"
    p = ["## الفرش\n" if ar else "## Furniture layout\n"]
    p.append(
        "\nالأثاث اقترحه الـ AI وحطّه مُرصِّف حتمي بيحترم الخلوصات ودوران الأبواب. "
        "القطعة اللي مالقتش مكان بتتقال صراحةً بدل ما تتحشر.\n"
        if ar else
        "\nThe AI specified the furniture; a deterministic packer placed it, "
        "respecting clearances and door swings. Pieces that did not fit are reported "
        "rather than forced in.\n"
    )
    by_room: dict[str, list[PlacedPiece]] = {}
    for piece in result.placed:
        by_room.setdefault(piece.room_id, []).append(piece)

    for room_id, pieces in by_room.items():
        p.append(f"\n**{room_id}** — ")
        p.append("، ".join(
            f"{x.name_ar if ar else x.name_en} ({x.rect.w:.2f}×{x.rect.h:.2f})"
            for x in pieces
        ))
        p.append("\n")
        intent = result.intents.get(room_id)
        if intent:
            p.append(f"  - {intent}\n")

    if result.dropped:
        p.append("\n### مدخلش (المساحة متسمحش)\n" if ar
                 else "\n### Did not fit\n")
        for room_id, name in result.dropped:
            p.append(f"- {room_id}: {name}\n")
    return "".join(p)
