"""محرك التوزيع الهندسي — Deterministic floor-plan solver.

الفكرة المعمارية:
    فراغ مركزي (صالة/ممر) عمودي على واجهة المدخل يقسّم القطعة لشريطين،
    وكل غرفة "بلاطة" في شريط بتلمس الفراغ المركزي (فبتاخد باب) وبتلمس
    الواجهة الخارجية (فبتاخد شباك). ده بيضمن رياضيًا:
      • مفيش تداخل بين الغرف ولا مساحات ضايعة
      • كل غرفة ليها مدخل من فراغ الحركة
      • كل غرفة معيشة/نوم ليها تهوية وإضاءة طبيعية
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..knowledge import (
    SHAFT_MIN_WIDTH,
    SHAFT_SERVED,
    UNROOFED,
    WALL_EXTERIOR,
    WALL_INTERIOR,
    WALL_WET,
    needs_daylight,
    orientation_penalty,
    profile,
    shaft_area,
    standard,
)
from ..models import (
    ArchitecturalProgram,
    DesignRequest,
    Rect,
    RoomKind,
    RoomSpec,
    WallSegment,
    Zone,
)

EPS = 1e-6
MIN_STRIP_WIDTH = 1.45
# بدل الحوائط: نص سُمك حائط خارجي + نص سُمك حائط داخلي على كل اتجاه
WALL_ALLOWANCE = (WALL_EXTERIOR + WALL_INTERIOR) / 2
MIN_HUB_LENGTH = 2.60


# ---------------------------------------------------------------------------
# هياكل مساعدة
# ---------------------------------------------------------------------------


@dataclass
class Bay:
    """بلاطة في شريط — غرفة، ومعاها ملحق اختياري (حمام داخلي)."""

    spec: RoomSpec
    child: Optional[RoomSpec] = None

    @property
    def area(self) -> float:
        return self.spec.target_area + (self.child.target_area if self.child else 0.0)

    @property
    def min_width(self) -> float:
        if self.child:
            return max(self.spec.min_width, self.child.min_width)
        return self.spec.min_width

    @property
    def is_shaft(self) -> bool:
        return self.spec.kind == RoomKind.SHAFT

    @property
    def max_strip_depth(self) -> float:
        """أقصى عمق للشريط تفضل معاه البلاطة (وملحقها) بأبعاد صالحة."""
        if self.child:
            return self.child.target_area / max(self.child.min_width, 0.4)
        return 1e9


def _shaft_spec(side: str, kinds: set[RoomKind], floors: int) -> RoomSpec:
    """منور بيخدم الفراغات الخدمية في الشريط ده.

    المنور بلاطة كاملة في الشريط: من الحائط المشترك لحد الفراغ المركزي. الغرف
    اللي فوقه وتحته بتاخد شبابيكها على حيطانه، وهو مكشوف للسما فبيدّيها تهوية
    وإضاءة. ده بالظبط منور العمارات السكنية.
    """
    biggest = max(shaft_area(k, floors) for k in kinds)
    return RoomSpec(
        id=f"shaft_{side}",
        name_ar="منور",
        name_en="Light Well",
        kind=RoomKind.SHAFT,
        target_area=biggest,
        min_width=SHAFT_MIN_WIDTH,
        zone=Zone.SERVICE,
        needs_window=False,
        is_wet=False,
        priority=4,
    )


def _with_shafts(bays: list[Bay], side: str, has_facade: bool, floors: int) -> list[Bay]:
    """الشريط اللي على حائط مشترك بياخد منور لخدمة فراغاته الخدمية.

    غرف النوم والمعيشة مش بتتعالج بمنور: الكود بيطلب لها واجهة خارجية حقيقية،
    فبنسيبها مخالفة صريحة بدل ما نغطّي عليها بمنور صغير.
    """
    if has_facade:
        return bays
    kinds = {
        b.spec.kind for b in bays
        if needs_daylight(b.spec.kind) and b.spec.kind in SHAFT_SERVED
    }
    kinds |= {
        b.child.kind for b in bays
        if b.child and needs_daylight(b.child.kind) and b.child.kind in SHAFT_SERVED
    }
    if not kinds:
        return bays
    return bays + [Bay(_shaft_spec(side, kinds, floors))]


@dataclass
class Placement:
    spec: RoomSpec
    x: float
    y: float
    w: float
    h: float


@dataclass
class CanonicalPlan:
    wc: float
    dc: float
    hub: RoomSpec
    hub_x: float
    hub_w: float
    hub_len: float
    left: list[Bay]
    left_w: float
    right: list[Bay]
    right_w: float
    terminal: list[RoomSpec] = field(default_factory=list)
    #: الأضلاع القياسية المطلّة على الخارج فعلًا (front/back/left/right).
    #: الوحدة المستقلة عندها الأربعة، لكن شقة جوه عمارة بتلاصق جيرانها.
    exterior: frozenset[str] = frozenset({"front", "back", "left", "right"})
    score: float = 0.0
    placements: list[Placement] = field(default_factory=list)

    @property
    def terminal_ids(self) -> set[str]:
        return {t.id for t in self.terminal}


# ---------------------------------------------------------------------------
# التقييم
# ---------------------------------------------------------------------------


def _score_room(w: float, h: float, spec: RoomSpec) -> float:
    """عقوبة (كل ما قلّت كل ما كان أحسن).

    المدخلات أبعاد محورية (centre-line)، والمعايير الكودية أبعاد صافية،
    فبنخصم بدل الحوائط الأول عشان التقييم والمراجعة يقيسوا نفس الحاجة.
    """
    st = standard(spec.kind)
    w = max(w - WALL_ALLOWANCE, 0.05)
    h = max(h - WALL_ALLOWANCE, 0.05)
    short, long = (w, h) if w <= h else (h, w)
    pen = 0.0

    # أقل بُعد مسموح — أهم معيار على الإطلاق: غرفة نحيفة = غرفة غير صالحة
    if short < spec.min_width:
        pen += (spec.min_width - short) * 30.0
    if short < st.min_width:
        pen += (st.min_width - short) * 22.0
    if short < 1.0:
        pen += (1.0 - short) * 60.0        # عمليًا غير قابل للاستخدام

    # نسبة الاستطالة
    aspect = long / max(short, 0.05)
    if aspect > st.max_aspect:
        pen += (aspect - st.max_aspect) * 2.6

    # خطأ المساحة
    area = w * h
    if spec.target_area > 0:
        pen += abs(area - spec.target_area) / spec.target_area * 3.5
    if area < st.min_area:
        pen += (st.min_area - area) / max(st.min_area, 1.0) * 9.0

    return pen


#: وزن عقوبة التوجيه الشمسي. صغير عن قصد: التوجيه مرجّح مش حاكم — مينفعش
#: يغلب على أقل بُعد كودي أو على وجود شباك أصلًا.
ORIENTATION_WEIGHT = 2.2


def _orientation_penalty(bays: list[Bay], facade: str | None) -> float:
    """عقوبة حط الفراغات دي على الواجهة الفعلية دي (د-2).

    من غير ده، `north_angle` بيرسم سهم الشمال وبس. مع ده، المحرك بيفضّل يحط
    غرف النوم شمالي/شرقي والفراغات الخدمية غربي — يعني بيصمّم أحسن، مش بس
    بيعلّق على التصميم بعد ما يخلص.
    """
    if not facade:
        return 0.0
    pen = 0.0
    for b in bays:
        pen += orientation_penalty(b.spec.kind, facade)
        if b.child is not None:
            pen += orientation_penalty(b.child.kind, facade) * 0.5
    return pen * ORIENTATION_WEIGHT


def _score_strip(
    bays: list[Bay], strip_w: float, ly: float, has_facade: bool = True,
    facade: str | None = None,
) -> float:
    """has_facade=False يعني الشريط ده على حائط مشترك — غرفه مش هتاخد شبابيك،
    فبنعاقب أي فراغ محتاج إضاءة طبيعية قبل ما نوصل لمرحلة المراجعة الكودية.

    `facade` = الجهة الفعلية (north/south/east/west) لواجهة الشريط، لو معروفة —
    بتضيف عقوبة التوجيه الشمسي."""
    if not bays:
        return 0.0
    total = sum(b.area for b in bays)
    if total <= EPS or strip_w <= EPS:
        return 1e6

    scale = ly / (total / strip_w)
    pen = 0.0
    y = 0.0
    prev_wet = False

    # الغرفة الملاصقة للمنور بتاخد شباكها عليه
    lit_by_shaft = {
        i for i in range(len(bays))
        if (i > 0 and bays[i - 1].is_shaft) or (i + 1 < len(bays) and bays[i + 1].is_shaft)
    }

    for i, b in enumerate(bays):
        h = (b.area / strip_w) * scale
        if b.child:
            share = b.spec.target_area / b.area
            h_parent, h_child = h * share, h * (1 - share)
            pen += _score_room(strip_w, h_parent, b.spec)
            pen += _score_room(strip_w, h_child, b.child)
        else:
            pen += _score_room(strip_w, h, b.spec)

        if b.is_shaft:
            if strip_w < SHAFT_MIN_WIDTH or h < SHAFT_MIN_WIDTH:
                pen += 22.0        # منور أضيق من الحد الكودي = مش منور
            # منور مش ملاصق لأي فراغ خدمي = مساحة ضايعة
            neighbours = [
                bays[j] for j in (i - 1, i + 1) if 0 <= j < len(bays)
            ]
            if not any(
                n.spec.kind in SHAFT_SERVED
                or (n.child and n.child.kind in SHAFT_SERVED)
                for n in neighbours
            ):
                pen += 30.0
            y += h
            continue

        # التقسيم الوظيفي: النهاري قريب من المدخل، الليلي في العمق
        rel = (y + h / 2) / max(ly, EPS)
        if b.spec.zone == Zone.NIGHT:
            pen += (1.0 - rel) * 1.5
        elif b.spec.zone == Zone.DAY and b.spec.priority <= 2:
            pen += rel * 1.1
        elif b.spec.zone == Zone.SERVICE:
            pen += abs(rel - 0.35) * 0.5

        # شريط على حائط مشترك: الفراغ المحتاج إضاءة إما ملاصق لمنور (وساعتها
        # التهوية متحلّة لكن أقل من واجهة حقيقية) أو أعمى تمامًا
        if not has_facade:
            miss = 2.5 if i in lit_by_shaft else 14.0
            for spec in (b.spec, b.child):
                if spec is None or not needs_daylight(spec.kind):
                    continue
                # غرفة النوم والمعيشة مش بتتعالج بمنور — لازم واجهة حقيقية
                pen += miss if spec.kind in SHAFT_SERVED else 14.0

        # تجميع الفراغات الرطبة (توفير سباكة)
        wet = b.spec.is_wet or (b.child.is_wet if b.child else False)
        if wet and prev_wet:
            pen -= 1.4
        prev_wet = wet

        y += h

    # التوجيه الشمسي — مستقل عن الترتيب داخل الشريط، فبيتحسب مرة واحدة
    if has_facade:
        pen += _orientation_penalty(bays, facade)

    return pen


def _order_strip(
    bays: list[Bay], strip_w: float, ly: float, has_facade: bool = True,
    facade: str | None = None,
) -> tuple[list[Bay], float]:
    """يبحث عن أفضل ترتيب للبلاطات داخل الشريط."""
    n = len(bays)
    if n <= 1:
        return list(bays), _score_strip(bays, strip_w, ly, has_facade, facade)

    if n <= 6:
        best, best_s = None, float("inf")
        for perm in itertools.permutations(bays):
            s = _score_strip(list(perm), strip_w, ly, has_facade, facade)
            if s < best_s:
                best, best_s = list(perm), s
        return best, best_s

    # ترتيب ابتدائي منطقي + تحسين محلي (2-opt على الجيران)
    order = sorted(
        bays,
        key=lambda b: (
            {Zone.DAY: 0, Zone.CIRCULATION: 0, Zone.SERVICE: 1, Zone.NIGHT: 2}[b.spec.zone],
            -b.area,
        ),
    )
    best_s = _score_strip(order, strip_w, ly, has_facade, facade)
    improved = True
    while improved:
        improved = False
        for i in range(len(order) - 1):
            cand = order[:]
            cand[i], cand[i + 1] = cand[i + 1], cand[i]
            s = _score_strip(cand, strip_w, ly, has_facade, facade)
            if s < best_s - 1e-9:
                order, best_s, improved = cand, s, True
    return order, best_s


# ---------------------------------------------------------------------------
# توليد المرشحين
# ---------------------------------------------------------------------------


def _partitions(bays: list[Bay]) -> Iterable[tuple[list[Bay], list[Bay]]]:
    """طرق مختلفة لتقسيم البلاطات على الشريطين."""
    if len(bays) == 1:
        yield bays, []
        return

    # (1) موازنة المساحات
    left: list[Bay] = []
    right: list[Bay] = []
    for b in sorted(bays, key=lambda b: -b.area):
        (left if sum(x.area for x in left) <= sum(x.area for x in right) else right).append(b)
    yield left, right

    # (2) فصل المنطقة الليلية عن باقي الفراغات
    night = [b for b in bays if b.spec.zone == Zone.NIGHT]
    other = [b for b in bays if b.spec.zone != Zone.NIGHT]
    if night and other:
        yield night, other
        yield other, night

    # (3) فصل الفراغات الرطبة
    wet = [b for b in bays if b.spec.is_wet or (b.child and b.child.is_wet)]
    dry = [b for b in bays if b not in wet]
    if wet and dry and len(wet) >= 2:
        # الرطب مع أصغر الجاف عشان الشريط ميبقاش ضيق أوي
        dry_sorted = sorted(dry, key=lambda b: b.area)
        yield wet + dry_sorted[:1], dry_sorted[1:]

    # (4) تقسيم بالتناوب حسب المساحة
    ordered = sorted(bays, key=lambda b: -b.area)
    yield ordered[0::2], ordered[1::2]

    # (5) الفراغات الصغيرة في شريط ضحل لوحدها — بيمنع الغرف النحيفة
    #     (عرض الشريط = مجموع مساحاته ÷ طول الفراغ المركزي، فمساحة أقل = شريط أضيق
    #      = بلاطات أعرض، وده بالظبط اللي الغرف الصغيرة محتاجاه)
    by_area = sorted(bays, key=lambda b: b.area)
    for cut in (1, 2, 3, 4, 5):
        if 0 < cut < len(bays):
            yield by_area[:cut], by_area[cut:]
            yield by_area[cut:], by_area[:cut]

    # (6) كل الفراغات الرطبة في شريط خدمي واحد
    if wet and dry:
        yield wet, dry
        yield dry, wet


def _terminal_candidates(
    bays: list[Bay], wc: float, dc: float
) -> list[list[Bay]]:
    """المجموعات اللي ممكن تحتل عرض القطعة بالكامل في نهاية الفراغ المركزي.

    وجود شريط طرفي بيقصّر الفراغ المركزي فبيمنعه يبقى ممر طويل ضيق.
    """
    out: list[list[Bay]] = [[]]
    usable = [b for b in bays if not b.child and b.spec.kind not in UNROOFED]

    # مرشّح مفرد
    for b in usable:
        depth = b.area / wc
        if depth < max(b.spec.min_width, 2.4) or depth > dc * 0.48:
            continue
        out.append([b])

    # مرشّح مزدوج (غرفتين جنب بعض بعرض القطعة)
    big = sorted(usable, key=lambda b: -b.area)[:4]
    for i in range(len(big)):
        for j in range(i + 1, len(big)):
            pair = [big[i], big[j]]
            total = sum(b.area for b in pair)
            depth = total / wc
            if depth > dc * 0.48 or depth < 2.4:
                continue
            if any(depth < b.spec.min_width for b in pair):
                continue
            if any(total * (b.area / total) / depth < b.min_width for b in pair):
                continue
            out.append(pair)

    return out[:9]


def _canonical_candidates(
    program: ArchitecturalProgram,
    wc: float,
    dc: float,
    req: DesignRequest,
    exterior: frozenset[str] = frozenset({"front", "back", "left", "right"}),
    facades: dict[str, str] | None = None,
) -> list[CanonicalPlan]:
    prof = profile(req.building_type)
    hub = program.rooms[0]

    # المناور من إنتاج المحرك نفسه (بيحطها في الشريط الأعمى)، فلو البرنامج
    # جاي من الموديل وفيه منور بنستبعده عشان ميتعاملش كغرفة عادية.
    rooms = [r for r in program.rooms[1:] if r.kind != RoomKind.SHAFT]

    children: dict[str, RoomSpec] = {
        r.attach_to: r for r in rooms if r.attach_to
    }

    # حالتين بنجرّبهم: الحمام ملحق بغرفة النوم، أو منفصل وبابه من الصالة.
    # الملحق أفخم، بس في المساحات الضيقة بيطلع نحيف — فنسيب المُقيِّم يقرر.
    bay_sets: list[list[Bay]] = []
    attached = [Bay(r, children.get(r.id)) for r in rooms if r.attach_to is None]
    bay_sets.append(attached)
    if children:
        detached = [Bay(r, None) for r in rooms]
        bay_sets.append(detached)

    if not bay_sets[0]:
        return []

    plans: list[CanonicalPlan] = []
    for bays in bay_sets:
        plans += _plans_for_bays(
            bays, hub, prof, wc, dc, exterior, req.shaft_floors, facades
        )

    plans.sort(key=lambda p: p.score, reverse=True)
    # الوحدات المحدودة الواجهات محتاجة مرشحين أكتر: أغلب التوزيعات بتفشل في
    # الإضاءة، والمرشح الناجح ممكن يكون خارج أفضل ٨ حسب التقييم الأولي.
    limit = 8 if len(exterior) >= 3 else 16
    return plans[:limit]


def _plans_for_bays(
    bays: list[Bay],
    hub: RoomSpec,
    prof,
    wc: float,
    dc: float,
    exterior: frozenset[str] = frozenset({"front", "back", "left", "right"}),
    shaft_floors: int = 1,
    facades: dict[str, str] | None = None,
) -> list[CanonicalPlan]:
    plans: list[CanonicalPlan] = []
    facades = facades or {}

    for term_bays in _terminal_candidates(bays, wc, dc):
        rest = [b for b in bays if b not in term_bays]
        if not rest:
            continue
        term_area = sum(b.area for b in term_bays)
        term_depth = term_area / wc
        ly = dc - term_depth
        if ly < MIN_HUB_LENGTH:
            continue

        base_bw = hub.target_area / ly
        bw_options = {
            min(max(base_bw, prof.hub_min_width), prof.hub_max_width),
            prof.hub_min_width,
            min(max(base_bw * 1.15, prof.hub_min_width), prof.hub_max_width),
        }

        for bw in sorted(bw_options):
            ws = wc - bw
            if ws < 2 * MIN_STRIP_WIDTH:
                continue

            for left, right in _partitions(rest):
                if not left and not right:
                    continue
                if right and not left:
                    left, right = right, left

                # المناور بتتفتح قبل حساب عرض الشرايط، عشان مساحة المنور
                # تدخل في حساب عرض الشريط
                left = _with_shafts(left, "l", "left" in exterior, shaft_floors)
                right = _with_shafts(right, "r", "right" in exterior, shaft_floors)

                sum_l = sum(b.area for b in left)
                sum_r = sum(b.area for b in right)

                if not right:
                    lw, rw = ws, 0.0
                else:
                    lw = ws * sum_l / max(sum_l + sum_r, EPS)
                    # نضمن إن كل شريط يستوعب أقل بُعد لغرفه
                    lmin = max([b.min_width for b in left], default=MIN_STRIP_WIDTH)
                    rmin = max([b.min_width for b in right], default=MIN_STRIP_WIDTH)
                    if lmin + rmin <= ws:
                        lw = min(max(lw, lmin), ws - rmin)
                    rw = ws - lw
                    if lw < MIN_STRIP_WIDTH or rw < MIN_STRIP_WIDTH:
                        continue

                # الشريط الطرفي المزدوج: لازم الفاصل بين الغرفتين يقع جوه عرض
                # الفراغ المركزي عشان كل واحدة تاخد بابها منه مباشرة
                term_order = list(term_bays)
                if len(term_order) == 2:
                    ok = False
                    for cand in (term_order, term_order[::-1]):
                        split = cand[0].area / term_depth
                        if lw + 0.55 < split < lw + bw - 0.55:
                            term_order, ok = cand, True
                            break
                    if not ok:
                        continue

                # الشريط الشمال بيلمس x=0 ("left")، واليمين بيلمس x=wc ("right")
                ordered_l, sl = _order_strip(
                    left, lw, ly, "left" in exterior, facades.get("left")
                )
                ordered_r, sr = (
                    _order_strip(right, rw, ly, "right" in exterior, facades.get("right"))
                    if right else ([], 0.0)
                )

                pen = sl + sr
                # تقييم الفراغ المركزي — استطالته أهم من مساحته
                pen += _score_room(bw, ly, hub)
                for ti, tb in enumerate(term_order):
                    tw = tb.area / term_depth
                    pen += _score_room(tw, term_depth, tb.spec)
                    # الشريط الطرفي بيلمس الظهر دايمًا، وأطرافه بتلمس الجنبين
                    lit = (
                        "back" in exterior
                        or (ti == 0 and "left" in exterior)
                        or (ti == len(term_order) - 1 and "right" in exterior)
                    )
                    if not lit and tb.spec.needs_window:
                        pen += 14.0
                # الشريط الطرفي بيطل على الظهر — نفس منطق التوجيه الشمسي
                if "back" in exterior and term_order:
                    pen += _orientation_penalty(term_order, facades.get("back"))
                if not right:
                    pen += 2.5              # شريط واحد = تخطيط أقل كفاءة

                plans.append(
                    CanonicalPlan(
                        wc=wc,
                        dc=dc,
                        hub=hub,
                        hub_x=lw,
                        hub_w=bw,
                        hub_len=ly,
                        left=ordered_l,
                        left_w=lw,
                        right=ordered_r,
                        right_w=rw,
                        terminal=[b.spec for b in term_order],
                        exterior=exterior,
                        score=-pen,
                    )
                )

    return plans


# ---------------------------------------------------------------------------
# تحويل الخطة القياسية لإحداثيات
# ---------------------------------------------------------------------------


def _lay_strip(
    bays: list[Bay], x0: float, strip_w: float, ly: float
) -> list[Placement]:
    out: list[Placement] = []
    if not bays or strip_w <= EPS:
        return out
    total_h = sum(b.area / strip_w for b in bays)
    scale = ly / max(total_h, EPS)
    y = 0.0
    for i, b in enumerate(bays):
        h = (b.area / strip_w) * scale
        if i == len(bays) - 1:
            h = ly - y                      # القضاء على أي خطأ تراكمي
        if b.child:
            share = b.spec.target_area / b.area
            h_parent = h * share
            out.append(Placement(b.spec, x0, y, strip_w, h_parent))
            out.append(Placement(b.child, x0, y + h_parent, strip_w, h - h_parent))
        else:
            out.append(Placement(b.spec, x0, y, strip_w, h))
        y += h
    return out


def _fill_placements(plan: CanonicalPlan) -> None:
    p: list[Placement] = []
    p.append(Placement(plan.hub, plan.hub_x, 0.0, plan.hub_w, plan.hub_len))
    p += _lay_strip(plan.left, 0.0, plan.left_w, plan.hub_len)
    if plan.right:
        p += _lay_strip(plan.right, plan.hub_x + plan.hub_w, plan.right_w, plan.hub_len)

    if plan.terminal:
        depth = plan.dc - plan.hub_len
        total = sum(t.target_area for t in plan.terminal)
        x = 0.0
        for i, spec in enumerate(plan.terminal):
            w = plan.wc if len(plan.terminal) == 1 else plan.wc * spec.target_area / total
            if i == len(plan.terminal) - 1:
                w = plan.wc - x
            p.append(Placement(spec, x, plan.hub_len, w, depth))
            x += w

    plan.placements = p


# ---------------------------------------------------------------------------
# الحوائط
# ---------------------------------------------------------------------------


def _merge_axis(
    edges: list[tuple[float, float, float, float]], plot_extent: float
) -> list[WallSegment]:
    """edges: (coord, start, end, thickness) → مقاطع حوائط مدمجة."""
    by_coord: dict[float, list[tuple[float, float, float]]] = {}
    for coord, s, e, t in edges:
        by_coord.setdefault(round(coord, 4), []).append((s, e, t))

    segs: list[tuple[float, float, float, float]] = []
    for coord, items in by_coord.items():
        points = sorted({round(v, 4) for it in items for v in it[:2]})
        for a, b in zip(points, points[1:]):
            if b - a < 1e-4:
                continue
            mid = (a + b) / 2
            thick = max(
                (t for s, e, t in items if s - 1e-6 <= mid <= e + 1e-6), default=0.0
            )
            if thick > 0:
                segs.append((coord, a, b, thick))

    # دمج المقاطع المتجاورة اللي ليها نفس السُمك
    segs.sort(key=lambda s: (s[0], s[1]))
    merged: list[tuple[float, float, float, float]] = []
    for seg in segs:
        if merged:
            c, a, b, t = merged[-1]
            if abs(c - seg[0]) < 1e-6 and abs(b - seg[1]) < 1e-4 and abs(t - seg[3]) < 1e-6:
                merged[-1] = (c, a, seg[2], t)
                continue
        merged.append(seg)

    return merged  # type: ignore[return-value]


def build_walls(placements: list[Placement], plot: Rect) -> list[WallSegment]:
    """يبني شبكة الحوائط من مستطيلات الغرف (بعد التحويل للإحداثيات الفعلية)."""
    vert: list[tuple[float, float, float, float]] = []
    horiz: list[tuple[float, float, float, float]] = []

    def thick_for(coord: float, extent: float, is_wet: bool) -> float:
        if abs(coord) < 1e-4 or abs(coord - extent) < 1e-4:
            return WALL_EXTERIOR
        return WALL_WET if is_wet else WALL_INTERIOR

    for pl in placements:
        wet = pl.spec.is_wet
        vert.append((pl.x, pl.y, pl.y + pl.h, thick_for(pl.x, plot.w, wet)))
        vert.append((pl.x + pl.w, pl.y, pl.y + pl.h, thick_for(pl.x + pl.w, plot.w, wet)))
        horiz.append((pl.y, pl.x, pl.x + pl.w, thick_for(pl.y, plot.h, wet)))
        horiz.append((pl.y + pl.h, pl.x, pl.x + pl.w, thick_for(pl.y + pl.h, plot.h, wet)))

    out: list[WallSegment] = []
    for coord, a, b, t in _merge_axis(vert, plot.w):
        out.append(
            WallSegment(
                axis="v", coord=coord, start=a, end=b, thickness=t,
                exterior=abs(coord) < 1e-4 or abs(coord - plot.w) < 1e-4,
            )
        )
    for coord, a, b, t in _merge_axis(horiz, plot.h):
        out.append(
            WallSegment(
                axis="h", coord=coord, start=a, end=b, thickness=t,
                exterior=abs(coord) < 1e-4 or abs(coord - plot.h) < 1e-4,
            )
        )
    return out


def wall_thickness_at(walls: list[WallSegment], axis: str, coord: float, a: float, b: float) -> float:
    mid = (a + b) / 2
    best = WALL_INTERIOR
    for w in walls:
        if w.axis == axis and abs(w.coord - coord) < 1e-3 and w.start - 1e-3 <= mid <= w.end + 1e-3:
            best = max(best, w.thickness)
    return best
