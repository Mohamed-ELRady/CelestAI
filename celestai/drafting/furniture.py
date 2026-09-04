"""رموز الفرش المعماري — schematic furniture blocks.

الهدف مش تصميم داخلي، الهدف إن المخطط يقرأ صح: الراسم بيعرف إن ده أوضة نوم
من السرير مش من الاسم بس، وبيتأكد إن المساحة فعلًا بتستوعب الفرش الأساسي.
"""

from __future__ import annotations

from ..models import PlacedRoom, RoomKind
from .drawing import Circle, Drawing, Line, Poly

F = "FURNITURE"


def _r(dw: Drawing, x: float, y: float, w: float, h: float, dash=None) -> None:
    if w <= 0.05 or h <= 0.05:
        return
    dw.rect(x, y, w, h, layer=F, dash=dash)


def _horizontal(room: PlacedRoom) -> bool:
    return room.net_rect.w >= room.net_rect.h


def _bed(dw: Drawing, room: PlacedRoom, bed_w: float, bed_l: float) -> None:
    """سرير + كومودينو + دولاب على الحائط المقابل."""
    r = room.net_rect
    horiz = r.w >= r.h
    if horiz:
        bw, bl = bed_l, bed_w
    else:
        bw, bl = bed_w, bed_l
    if bw > r.w - 0.5 or bl > r.h - 0.5:
        bw, bl = min(bw, r.w * 0.55), min(bl, r.h * 0.6)

    bx = r.x + 0.12
    by = r.y + (r.h - bl) / 2 if horiz else r.y + 0.12
    if not horiz:
        bx = r.x + (r.w - bw) / 2

    _r(dw, bx, by, bw, bl)
    # المخدّة
    if horiz:
        dw.add(Line(bx + 0.18, by, bx + 0.18, by + bl, layer=F))
    else:
        dw.add(Line(bx, by + bl - 0.18, bx + bw, by + bl - 0.18, layer=F))

    # دولاب على الضلع البعيد
    if horiz and r.w - bw > 0.9:
        _r(dw, r.x2 - 0.60, r.y + 0.15, 0.58, min(r.h - 0.3, 2.0))
    elif not horiz and r.h - bl > 0.9:
        _r(dw, r.x + 0.15, r.y2 - 0.60, min(r.w - 0.3, 2.0), 0.58)


def _sofa(dw: Drawing, room: PlacedRoom) -> None:
    r = room.net_rect
    horiz = r.w >= r.h
    if horiz:
        w, h = min(2.4, r.w * 0.55), 0.85
        x, y = r.x + 0.15, r.y + 0.15
    else:
        w, h = 0.85, min(2.4, r.h * 0.55)
        x, y = r.x + 0.15, r.y + 0.15
    _r(dw, x, y, w, h)
    # ترابيزة قهوة
    if horiz:
        _r(dw, x + w * 0.15, y + h + 0.35, w * 0.7, 0.55)
    else:
        _r(dw, x + w + 0.35, y + h * 0.15, 0.55, h * 0.7)


def _dining(dw: Drawing, room: PlacedRoom) -> None:
    r = room.net_rect
    tw, th = min(1.8, r.w * 0.6), min(0.95, r.h * 0.5)
    cx, cy = r.cx - tw / 2, r.cy - th / 2
    _r(dw, cx, cy, tw, th)
    n = max(2, int(tw // 0.6))
    for i in range(n):
        x = cx + tw * (i + 0.5) / n - 0.20
        _r(dw, x, cy - 0.50, 0.40, 0.40)
        _r(dw, x, cy + th + 0.10, 0.40, 0.40)


def _kitchen(dw: Drawing, room: PlacedRoom) -> None:
    r = room.net_rect
    d = 0.60                       # عمق الكاونتر
    if r.w >= r.h:
        _r(dw, r.x, r.y2 - d, r.w, d)
        sink_x, sink_y = r.x + r.w * 0.25, r.y2 - d / 2
        hob_x, hob_y = r.x + r.w * 0.65, r.y2 - d / 2
        _r(dw, r.x, r.y, 0.60, 0.62)          # ثلاجة
    else:
        _r(dw, r.x2 - d, r.y, d, r.h)
        sink_x, sink_y = r.x2 - d / 2, r.y + r.h * 0.25
        hob_x, hob_y = r.x2 - d / 2, r.y + r.h * 0.65
        _r(dw, r.x, r.y, 0.62, 0.60)
    dw.add(Circle(sink_x, sink_y, 0.19, layer=F))
    for dx, dy in ((-0.12, -0.12), (0.12, -0.12), (-0.12, 0.12), (0.12, 0.12)):
        dw.add(Circle(hob_x + dx, hob_y + dy, 0.075, layer=F))


def _bath(dw: Drawing, room: PlacedRoom, with_shower: bool) -> None:
    r = room.net_rect
    horiz = r.w >= r.h
    # قاعدة الحمام
    if horiz:
        dw.add(Circle(r.x + 0.42, r.y + r.h / 2, 0.22, layer=F))
        _r(dw, r.x + 0.78, r.y + r.h / 2 - 0.26, 0.52, 0.42)      # حوض
        if with_shower and r.w > 1.9:
            _r(dw, r.x2 - 0.90, r.y + 0.06, 0.85, min(r.h - 0.12, 0.90))
    else:
        dw.add(Circle(r.x + r.w / 2, r.y + 0.42, 0.22, layer=F))
        _r(dw, r.x + r.w / 2 - 0.26, r.y + 0.78, 0.42, 0.52)
        if with_shower and r.h > 1.9:
            _r(dw, r.x + 0.06, r.y2 - 0.90, min(r.w - 0.12, 0.90), 0.85)


def _desk(dw: Drawing, room: PlacedRoom) -> None:
    r = room.net_rect
    if r.w >= r.h:
        _r(dw, r.x + 0.20, r.y2 - 0.85, min(1.60, r.w - 0.4), 0.70)
        _r(dw, r.x + 0.70, r.y2 - 1.45, 0.50, 0.50)
    else:
        _r(dw, r.x2 - 0.85, r.y + 0.20, 0.70, min(1.60, r.h - 0.4))
        _r(dw, r.x2 - 1.45, r.y + 0.70, 0.50, 0.50)


def _meeting(dw: Drawing, room: PlacedRoom) -> None:
    r = room.net_rect
    tw, th = r.w * 0.5, r.h * 0.42
    dw.add(
        Poly(
            [
                (r.cx - tw / 2, r.cy - th / 2), (r.cx + tw / 2, r.cy - th / 2),
                (r.cx + tw / 2, r.cy + th / 2), (r.cx - tw / 2, r.cy + th / 2),
            ],
            layer=F,
        )
    )
    n = max(2, int(tw // 0.7))
    for i in range(n):
        x = r.cx - tw / 2 + tw * (i + 0.5) / n - 0.22
        _r(dw, x, r.cy - th / 2 - 0.55, 0.44, 0.44)
        _r(dw, x, r.cy + th / 2 + 0.11, 0.44, 0.44)


def _open_office(dw: Drawing, room: PlacedRoom) -> None:
    r = room.net_rect
    step_x, step_y = 1.70, 1.55
    nx = max(1, int((r.w - 0.5) // step_x))
    ny = max(1, int((r.h - 0.5) // step_y))
    ox = r.x + (r.w - nx * step_x) / 2
    oy = r.y + (r.h - ny * step_y) / 2
    for i in range(nx):
        for j in range(ny):
            _r(dw, ox + i * step_x + 0.10, oy + j * step_y + 0.10, 1.40, 0.70)
            _r(dw, ox + i * step_x + 0.55, oy + j * step_y + 0.88, 0.48, 0.48)


def _stair(dw: Drawing, room: PlacedRoom) -> None:
    r = room.net_rect
    horiz = r.w >= r.h
    tread = 0.28
    n = max(3, int((r.w if horiz else r.h) // tread))
    for i in range(1, n):
        t = i * ((r.w if horiz else r.h) / n)
        if horiz:
            dw.add(Line(r.x + t, r.y, r.x + t, r.y2, layer=F))
        else:
            dw.add(Line(r.x, r.y + t, r.x2, r.y + t, layer=F))
    # سهم اتجاه الصعود
    if horiz:
        dw.add(Line(r.x + 0.2, r.cy, r.x2 - 0.2, r.cy, layer=F, width_scale=1.4))
        dw.add(Line(r.x2 - 0.45, r.cy - 0.13, r.x2 - 0.2, r.cy, layer=F, width_scale=1.4))
        dw.add(Line(r.x2 - 0.45, r.cy + 0.13, r.x2 - 0.2, r.cy, layer=F, width_scale=1.4))
    else:
        dw.add(Line(r.cx, r.y + 0.2, r.cx, r.y2 - 0.2, layer=F, width_scale=1.4))
        dw.add(Line(r.cx - 0.13, r.y2 - 0.45, r.cx, r.y2 - 0.2, layer=F, width_scale=1.4))
        dw.add(Line(r.cx + 0.13, r.y2 - 0.45, r.cx, r.y2 - 0.2, layer=F, width_scale=1.4))


def draw_furniture(dw: Drawing, room: PlacedRoom) -> None:
    """يرسم الفرش المناسب لنوع الفراغ."""
    r = room.net_rect
    if r.w < 1.0 or r.h < 1.0:
        return

    k = room.kind
    try:
        if k == RoomKind.MASTER_BEDROOM:
            _bed(dw, room, 1.70, 2.05)
        elif k in (RoomKind.BEDROOM, RoomKind.KIDS_BEDROOM):
            _bed(dw, room, 1.30 if k == RoomKind.BEDROOM else 0.95, 2.00)
        elif k in (RoomKind.LIVING, RoomKind.RECEPTION, RoomKind.WAITING):
            _sofa(dw, room)
        elif k == RoomKind.DINING:
            _dining(dw, room)
        elif k == RoomKind.KITCHEN:
            _kitchen(dw, room)
        elif k == RoomKind.BATH:
            _bath(dw, room, with_shower=True)
        elif k == RoomKind.WC:
            _bath(dw, room, with_shower=False)
        elif k in (RoomKind.OFFICE_ROOM, RoomKind.EXAM_ROOM):
            _desk(dw, room)
        elif k == RoomKind.MEETING:
            _meeting(dw, room)
        elif k == RoomKind.OPEN_OFFICE:
            _open_office(dw, room)
        elif k == RoomKind.STAIR:
            _stair(dw, room)
    except Exception:  # noqa: BLE001 — الفرش تحسين مش شرط لصحة المخطط
        return
