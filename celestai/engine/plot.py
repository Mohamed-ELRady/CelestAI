"""اشتقاق أبعاد القطعة — Plot dimensioning."""

from __future__ import annotations

import math
from typing import Iterable

from ..knowledge import profile
from ..models import DesignRequest, Rect

Side = str
SIDES: tuple[str, ...] = ("south", "north", "east", "west")


def derive_plot(req: DesignRequest) -> Rect:
    """يحدد أبعاد القطعة من المساحة و/أو الأبعاد المُدخلة."""
    return candidate_plots(req)[0]


def candidate_plots(req: DesignRequest) -> list[Rect]:
    """أبعاد قطعة مرشّحة — لو المستخدم مدّاش أبعاد بنجرّب أكتر من نسبة.

    نسبة القطعة هي أقوى مؤثر على جودة التوزيع: البُعد الموازي لواجهة المدخل
    هو اللي بيحدد عمق الشرائط، وبالتالي عرض الغرف.
    """
    prof = profile(req.building_type)

    if req.width and req.depth:
        return [Rect(x=0.0, y=0.0, w=round(req.width, 3), h=round(req.depth, 3))]
    if req.width:
        return [Rect(x=0.0, y=0.0, w=round(req.width, 3), h=round(req.area / req.width, 3))]
    if req.depth:
        return [Rect(x=0.0, y=0.0, w=round(req.area / req.depth, 3), h=round(req.depth, 3))]

    base = prof.preferred_aspect
    # المباني الكبيرة محتاجة استطالة أكبر عشان الشرائط ما تبقاش عميقة جدًا
    ratios = sorted({
        round(base, 3),
        round(base * 1.22, 3),
        round(base * 1.48, 3),
        round(max(base * 0.85, 1.0), 3),
    })
    if req.area >= 160:
        ratios.append(round(base * 1.8, 3))

    plots: list[Rect] = []
    for r in ratios:
        w = math.sqrt(req.area * r)
        plots.append(Rect(x=0.0, y=0.0, w=round(w, 3), h=round(req.area / w, 3)))
    return plots


def candidate_entry_sides(req: DesignRequest, plot: Rect) -> list[str]:
    """جهات الدخول اللي هنجرّبها."""
    if req.entry_side != "auto":
        return [req.entry_side]
    # المدخل الأفضل عادةً من الضلع الأقصر عشان الممر المركزي يبقى أقصر
    if plot.w <= plot.h:
        return ["south", "north", "west", "east"]
    return ["west", "east", "south", "north"]


# ---------------------------------------------------------------------------
# التحويل بين الإحداثيات القياسية والفعلية
# ---------------------------------------------------------------------------
# الإحداثيات القياسية (canonical): المدخل دايمًا عند y=0، العمق لأعلى.
#   Wc = امتداد واجهة المدخل، Dc = العمق من المدخل للداخل.


def canonical_dims(plot: Rect, side: str) -> tuple[float, float]:
    """يرجّع (Wc, Dc) في الإطار القياسي."""
    if side in ("south", "north"):
        return plot.w, plot.h
    return plot.h, plot.w


class Transform:
    """يحوّل من الإطار القياسي للإطار الفعلي حسب جهة المدخل."""

    def __init__(self, plot: Rect, side: str):
        self.plot = plot
        self.side = side
        self.wc, self.dc = canonical_dims(plot, side)

    # -- المستطيلات ---------------------------------------------------------

    def rect(self, x: float, y: float, w: float, h: float) -> Rect:
        s = self.side
        if s == "south":
            return Rect(x=x, y=y, w=w, h=h)
        if s == "north":
            return Rect(x=self.wc - x - w, y=self.dc - y - h, w=w, h=h)
        if s == "west":
            # canonical (x=على الواجهة, y=للعمق) → actual (x=العمق, y=على الواجهة)
            return Rect(x=y, y=x, w=h, h=w)
        # east
        return Rect(x=self.plot.w - y - h, y=x, w=h, h=w)

    # -- الفتحات والحوائط ---------------------------------------------------

    def opening(
        self, axis: str, coord: float, start: float, width: float, swing: int, hinge: int
    ) -> tuple[str, float, float, int, int]:
        """يرجّع (axis, coord, start, swing, hinge) بعد التحويل.

        axis='h' يعني حائط أفقي (y ثابت = coord) ممتد على المحور x.
        axis='v' يعني حائط رأسي (x ثابت = coord) ممتد على المحور y.
        """
        s = self.side

        if s == "south":                       # الإطار القياسي نفسه
            return axis, coord, start, swing, hinge

        if s == "north":                       # دوران 180°
            span_len = self.wc if axis == "h" else self.dc
            new_coord = (self.dc - coord) if axis == "h" else (self.wc - coord)
            return axis, new_coord, span_len - start - width, -swing, -hinge

        if s == "west":                        # تبديل المحاور (x↔y)
            return ("v" if axis == "h" else "h"), coord, start, swing, hinge

        # east — تبديل المحاور + انعكاس على محور x الفعلي
        if axis == "h":
            # حائط أفقي قياسي (y=coord) → حائط رأسي فعلي عند x = W - coord
            return "v", self.plot.w - coord, start, -swing, hinge
        # حائط رأسي قياسي (x=coord) → حائط أفقي فعلي عند y = coord
        return "h", coord, self.plot.w - start - width, swing, -hinge

    def span_length(self, axis: str) -> float:
        return self.wc if axis == "h" else self.dc

    # -- الواجهات ----------------------------------------------------------
    # الأضلاع القياسية: "front" = y=0 (واجهة المدخل)، "back" = y=dc،
    #                   "left" = x=0،               "right" = x=wc.

    #: يربط كل ضلع قياسي بالجهة الفعلية، حسب جهة المدخل.
    _SIDE_MAP: dict[str, dict[str, str]] = {
        "south": {"front": "south", "back": "north", "left": "west", "right": "east"},
        "north": {"front": "north", "back": "south", "left": "east", "right": "west"},
        "west": {"front": "west", "back": "east", "left": "south", "right": "north"},
        "east": {"front": "east", "back": "west", "left": "south", "right": "north"},
    }

    def canonical_sides(self, actual_sides: Iterable[str]) -> set[str]:
        """يحوّل جهات فعلية (north/south/…) لأضلاع قياسية (front/back/left/right)."""
        mapping = self._SIDE_MAP[self.side]
        actual = set(actual_sides)
        return {canon for canon, real in mapping.items() if real in actual}

    def real_side(self, canonical: str) -> str:
        """العكس: ضلع قياسي → الجهة الفعلية. بيستخدمه التقييم الشمسي."""
        return self._SIDE_MAP[self.side].get(canonical, canonical)

    def facade_map(self) -> dict[str, str]:
        """كل الأضلاع القياسية → جهاتها الفعلية."""
        return dict(self._SIDE_MAP[self.side])
