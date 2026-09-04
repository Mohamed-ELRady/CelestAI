"""المعايير المعمارية والأكواد — Architectural standards & code rules.

المصادر المرجعية: الكود المصري للأعمال المعمارية، Neufert Architects' Data.
كل الأبعاد بالمتر والمساحات بالمتر المربع.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import BuildingType, RoomKind, Zone

# ---------------------------------------------------------------------------
# سُمك الحوائط — Wall thicknesses
# ---------------------------------------------------------------------------

WALL_EXTERIOR = 0.25
WALL_INTERIOR = 0.12
WALL_WET = 0.15          # حوائط الفراغات الرطبة (سباكة)
SLAB_HEIGHT = 3.00       # ارتفاع الدور الصافي

# ---------------------------------------------------------------------------
# الأبواب — Doors
# ---------------------------------------------------------------------------

DOOR_WIDTHS: dict[RoomKind, float] = {
    RoomKind.BATH: 0.80,
    RoomKind.WC: 0.75,
    RoomKind.STORAGE: 0.75,
    RoomKind.PANTRY: 0.80,
    RoomKind.LAUNDRY: 0.80,
    RoomKind.KITCHEN: 0.90,
    RoomKind.BALCONY: 1.00,
    RoomKind.MEETING: 0.95,
    RoomKind.OPEN_OFFICE: 1.20,
}
DOOR_WIDTH_DEFAULT = 0.90
DOOR_ENTRY_WIDTH = 1.05
DOOR_HEIGHT = 2.10
DOOR_MIN_CLEAR = 0.75    # أقل عرض باب مسموح بالكود

# ---------------------------------------------------------------------------
# الشبابيك والإضاءة الطبيعية — Windows & daylight
# ---------------------------------------------------------------------------

WINDOW_HEIGHT = 1.50
WINDOW_SILL = 0.90
WINDOW_SILL_WET = 1.60
WINDOW_HEIGHT_WET = 0.60
WINDOW_MIN_WIDTH = 0.60
WINDOW_MAX_EDGE_RATIO = 0.72   # أقصى نسبة من طول الحائط

# نسبة مساحة الشباك لمساحة الأرضية حسب نوع الفراغ (الكود المصري)
DAYLIGHT_RATIO: dict[RoomKind, float] = {
    RoomKind.BEDROOM: 1 / 8,
    RoomKind.MASTER_BEDROOM: 1 / 8,
    RoomKind.KIDS_BEDROOM: 1 / 8,
    RoomKind.LIVING: 1 / 8,
    RoomKind.RECEPTION: 1 / 14,   # فراغ حركة: إضاءة مستعارة مقبولة
    RoomKind.DINING: 1 / 8,
    RoomKind.OFFICE_ROOM: 1 / 8,
    RoomKind.MEETING: 1 / 8,
    RoomKind.OPEN_OFFICE: 1 / 7,
    RoomKind.EXAM_ROOM: 1 / 8,
    RoomKind.WAITING: 1 / 12,
    RoomKind.KITCHEN: 1 / 10,
    RoomKind.BATH: 1 / 12,
    RoomKind.WC: 1 / 12,
    RoomKind.LAUNDRY: 1 / 12,
}

HABITABLE = {
    RoomKind.BEDROOM,
    RoomKind.MASTER_BEDROOM,
    RoomKind.KIDS_BEDROOM,
    RoomKind.LIVING,
    RoomKind.RECEPTION,
    RoomKind.DINING,
    RoomKind.OFFICE_ROOM,
    RoomKind.MEETING,
    RoomKind.OPEN_OFFICE,
    RoomKind.EXAM_ROOM,
    RoomKind.WAITING,
}

WET_ROOMS = {RoomKind.BATH, RoomKind.WC, RoomKind.KITCHEN, RoomKind.LAUNDRY, RoomKind.PANTRY}

UNROOFED = {RoomKind.BALCONY, RoomKind.SHAFT}


# ---------------------------------------------------------------------------
# المناور — Light wells / ventilation shafts
# ---------------------------------------------------------------------------
#
# المنور فراغ مكشوف للسما بيخترق المبنى رأسيًا، بيدّي تهوية وإضاءة للفراغات
# اللي مالهاش واجهة خارجية. الكود المصري بيسمح بيه للفراغات الخدمية (مطبخ،
# حمام، دورة مياه، غسيل) — إنما غرف النوم والمعيشة لازم واجهة خارجية حقيقية
# أو فناء بمساحة أكبر بكتير، فالمحرك بيرفض يعالج غرفة نوم بمنور.

SHAFT_SERVED = {
    RoomKind.KITCHEN,
    RoomKind.BATH,
    RoomKind.WC,
    RoomKind.LAUNDRY,
    RoomKind.PANTRY,
}

SHAFT_MIN_WIDTH = 1.10        # أقل بُعد صافي للمنور
SHAFT_MIN_AREA = 2.00         # منور تهوية لحمام/دورة مياه
SHAFT_KITCHEN_MIN_AREA = 3.60  # المطبخ محتاج إضاءة كمان مش تهوية بس
SHAFT_AREA_PER_FLOOR = 0.40   # زيادة المساحة عن كل دور فوق الدور الأول
SHAFT_MAX_AREA = 9.00         # فوق كده بقى فناء مش منور
SHAFT_WINDOW_HEIGHT = 0.90    # شباك المنور أعلى وأصغر من شباك الواجهة
SHAFT_WINDOW_SILL = 1.40


def shaft_area(kind: RoomKind, floors: int = 1) -> float:
    """أقل مساحة منور مقبولة للفراغ ده في مبنى بالارتفاع ده."""
    base = SHAFT_KITCHEN_MIN_AREA if kind == RoomKind.KITCHEN else SHAFT_MIN_AREA
    grown = base + SHAFT_AREA_PER_FLOOR * max(floors - 1, 0)
    return round(min(grown, SHAFT_MAX_AREA), 2)


# ---------------------------------------------------------------------------
# معايير الفراغات — Per-room standards
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoomStandard:
    min_area: float
    ideal_area: float
    min_width: float
    max_aspect: float
    zone: Zone
    name_ar: str
    name_en: str


STANDARDS: dict[RoomKind, RoomStandard] = {
    RoomKind.RECEPTION: RoomStandard(12.0, 22.0, 2.90, 3.0, Zone.CIRCULATION, "صالة", "Reception"),
    RoomKind.LIVING: RoomStandard(12.0, 20.0, 3.20, 2.2, Zone.DAY, "معيشة", "Living"),
    RoomKind.DINING: RoomStandard(9.0, 14.0, 2.80, 2.2, Zone.DAY, "سفرة", "Dining"),
    RoomKind.MASTER_BEDROOM: RoomStandard(12.0, 18.0, 3.00, 2.0, Zone.NIGHT, "غرفة نوم رئيسية", "Master Bedroom"),
    RoomKind.BEDROOM: RoomStandard(9.0, 13.0, 2.80, 2.0, Zone.NIGHT, "غرفة نوم", "Bedroom"),
    RoomKind.KIDS_BEDROOM: RoomStandard(8.0, 12.0, 2.70, 2.0, Zone.NIGHT, "غرفة أطفال", "Kids Bedroom"),
    RoomKind.KITCHEN: RoomStandard(6.0, 10.0, 1.90, 2.8, Zone.SERVICE, "مطبخ", "Kitchen"),
    RoomKind.BATH: RoomStandard(3.0, 4.5, 1.55, 2.6, Zone.SERVICE, "حمام", "Bathroom"),
    RoomKind.WC: RoomStandard(1.4, 2.2, 1.05, 2.6, Zone.SERVICE, "دورة مياه", "WC"),
    RoomKind.OFFICE_ROOM: RoomStandard(7.0, 11.0, 2.60, 2.2, Zone.DAY, "مكتب", "Office"),
    RoomKind.MEETING: RoomStandard(10.0, 18.0, 3.00, 2.2, Zone.DAY, "غرفة اجتماعات", "Meeting Room"),
    RoomKind.OPEN_OFFICE: RoomStandard(20.0, 60.0, 4.00, 2.6, Zone.DAY, "مساحة عمل مفتوحة", "Open Workspace"),
    RoomKind.PANTRY: RoomStandard(3.0, 5.0, 1.60, 2.6, Zone.SERVICE, "بانتري", "Pantry"),
    RoomKind.STORAGE: RoomStandard(1.5, 3.0, 1.00, 3.0, Zone.SERVICE, "تخزين", "Storage"),
    RoomKind.LAUNDRY: RoomStandard(2.5, 4.0, 1.40, 2.6, Zone.SERVICE, "غسيل", "Laundry"),
    RoomKind.BALCONY: RoomStandard(2.5, 6.0, 1.20, 4.0, Zone.DAY, "بلكونة", "Balcony"),
    RoomKind.SHAFT: RoomStandard(2.0, 4.0, 1.10, 4.0, Zone.SERVICE, "منور", "Light Well"),
    RoomKind.STAIR: RoomStandard(6.0, 9.0, 2.40, 2.2, Zone.CIRCULATION, "سلم", "Stair"),
    RoomKind.CORRIDOR: RoomStandard(2.0, 6.0, 1.10, 8.0, Zone.CIRCULATION, "ممر", "Corridor"),
    RoomKind.EXAM_ROOM: RoomStandard(9.0, 14.0, 2.80, 2.0, Zone.DAY, "غرفة كشف", "Exam Room"),
    RoomKind.WAITING: RoomStandard(10.0, 20.0, 2.80, 2.6, Zone.DAY, "انتظار", "Waiting"),
}


def standard(kind: RoomKind) -> RoomStandard:
    return STANDARDS.get(
        kind, RoomStandard(6.0, 10.0, 2.40, 2.5, Zone.DAY, "فراغ", "Space")
    )


# ---------------------------------------------------------------------------
# قواعد نسب المسطحات حسب نوع المبنى
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildingProfile:
    """خصائص عامة لكل نوع مبنى."""

    hub_kind: RoomKind                 # الفراغ المركزي اللي بيوزّع على الباقي
    hub_min_width: float
    hub_max_width: float
    circulation_share: float           # نسبة الفراغ المركزي من المساحة الكلية
    preferred_aspect: float            # نسبة العرض للعمق للقطعة
    label_ar: str
    label_en: str
    adjacency: list[tuple[RoomKind, RoomKind]] = field(default_factory=list)


PROFILES: dict[BuildingType, BuildingProfile] = {
    BuildingType.APARTMENT: BuildingProfile(
        hub_kind=RoomKind.RECEPTION,
        hub_min_width=3.10,
        hub_max_width=4.80,
        circulation_share=0.20,
        preferred_aspect=1.28,
        label_ar="شقة سكنية",
        label_en="Apartment",
        adjacency=[
            (RoomKind.KITCHEN, RoomKind.DINING),
            (RoomKind.MASTER_BEDROOM, RoomKind.BATH),
            (RoomKind.LIVING, RoomKind.DINING),
        ],
    ),
    BuildingType.VILLA_FLOOR: BuildingProfile(
        hub_kind=RoomKind.RECEPTION,
        hub_min_width=3.45,
        hub_max_width=5.40,
        circulation_share=0.22,
        preferred_aspect=1.15,
        label_ar="دور فيلا",
        label_en="Villa Floor",
        adjacency=[
            (RoomKind.KITCHEN, RoomKind.DINING),
            (RoomKind.MASTER_BEDROOM, RoomKind.BATH),
            (RoomKind.STAIR, RoomKind.RECEPTION),
        ],
    ),
    BuildingType.OFFICE: BuildingProfile(
        hub_kind=RoomKind.CORRIDOR,
        hub_min_width=1.70,
        hub_max_width=2.60,
        circulation_share=0.16,
        preferred_aspect=1.45,
        label_ar="مكتب إداري",
        label_en="Office",
        adjacency=[
            (RoomKind.MEETING, RoomKind.WAITING),
            (RoomKind.PANTRY, RoomKind.OPEN_OFFICE),
        ],
    ),
    BuildingType.CLINIC: BuildingProfile(
        hub_kind=RoomKind.WAITING,
        hub_min_width=3.00,
        hub_max_width=4.60,
        circulation_share=0.24,
        preferred_aspect=1.30,
        label_ar="عيادة",
        label_en="Clinic",
        adjacency=[
            (RoomKind.EXAM_ROOM, RoomKind.WAITING),
            (RoomKind.WC, RoomKind.WAITING),
        ],
    ),
    BuildingType.GENERIC: BuildingProfile(
        hub_kind=RoomKind.CORRIDOR,
        hub_min_width=1.60,
        hub_max_width=3.40,
        circulation_share=0.14,
        preferred_aspect=1.30,
        label_ar="فراغ عام",
        label_en="Generic Space",
    ),
}


def profile(bt: BuildingType) -> BuildingProfile:
    return PROFILES.get(bt, PROFILES[BuildingType.GENERIC])


def door_width(kind: RoomKind) -> float:
    return DOOR_WIDTHS.get(kind, DOOR_WIDTH_DEFAULT)


def required_glazing(kind: RoomKind, floor_area: float) -> float:
    """المساحة الزجاجية المطلوبة للفراغ (م²)."""
    ratio = DAYLIGHT_RATIO.get(kind)
    return 0.0 if ratio is None else floor_area * ratio


# ---------------------------------------------------------------------------
# التوجيه الشمسي — Solar orientation (د-2)
# ---------------------------------------------------------------------------
#
# في مناخ حار زي مصر والخليج، الحِمل الصيفي هو الحاكم مش مكسب الشتا. الجداول
# دي هي أساس عقوبة التوجيه اللي المحرك بيستخدمها وهو بيوزّع الفراغات —
# الحسابات الشمسية التفصيلية في `analysis/solar.py`.

#: جودة كل واجهة (0 = مثالية، 1 = أسوأ). الغرب أسوأ واجهة على الإطلاق: شمس
#: منخفضة بعد العصر بتضرب أفقيًا وبتخترق أعمق، والجو ساخن أصلًا وقتها.
FACADE_PENALTY_HOT: dict[str, float] = {
    "north": 0.0,     # ضوء ثابت من غير حِمل مباشر — أفضل واجهة
    "east": 0.35,     # شمس الصبح والجو لسه بارد
    "south": 0.55,    # عالية في الصيف فسهل تتظلّل بكاسر أفقي
    "west": 1.00,     # الأسوأ: حِمل الظهيرة
}

#: حساسية كل فراغ للحِمل الحراري (1 = حسّاس جدًا، 0 = مالوش لازمة)
HEAT_SENSITIVITY: dict[RoomKind, float] = {
    RoomKind.MASTER_BEDROOM: 1.0,
    RoomKind.BEDROOM: 1.0,
    RoomKind.KIDS_BEDROOM: 1.0,
    RoomKind.OPEN_OFFICE: 0.9,
    RoomKind.LIVING: 0.8,
    RoomKind.OFFICE_ROOM: 0.8,
    RoomKind.MEETING: 0.7,
    RoomKind.EXAM_ROOM: 0.7,
    RoomKind.DINING: 0.6,
    RoomKind.RECEPTION: 0.5,
    RoomKind.WAITING: 0.5,
    RoomKind.KITCHEN: 0.3,       # بيولّد حرارة أصلًا، فأحسن يكون غربي
    RoomKind.CORRIDOR: 0.2,
    RoomKind.BATH: 0.1,
    RoomKind.WC: 0.1,
    RoomKind.LAUNDRY: 0.1,
    RoomKind.PANTRY: 0.1,
    RoomKind.STAIR: 0.1,
    RoomKind.STORAGE: 0.0,
    RoomKind.BALCONY: 0.0,
    RoomKind.SHAFT: 0.0,
}


def orientation_penalty(kind: RoomKind, facade: str) -> float:
    """عقوبة حط الفراغ ده على الواجهة دي — 0 يعني توجيه مثالي."""
    return FACADE_PENALTY_HOT.get(facade, 0.5) * HEAT_SENSITIVITY.get(kind, 0.5)


def needs_daylight(kind: RoomKind) -> bool:
    """هل الفراغ ده الكود بيطلب له إضاءة وتهوية طبيعية؟

    ملاحظة: دي أوسع من `RoomSpec.needs_window` اللي بيتحدّد بـ HABITABLE —
    المطبخ والحمام مش «فراغات معيشة» لكنهم بيتطلبوا تهوية طبيعية برضه، وده
    اللي المراجعة الكودية بتتحقق منه فعلًا.
    """
    return kind in DAYLIGHT_RATIO


# ---------------------------------------------------------------------------
# المباني متعددة الأدوار — النواة الرأسية والوحدات
# ---------------------------------------------------------------------------

WALL_PARTY = 0.20        # حائط فاصل بين وحدتين (عزل صوتي + إنشائي)
FLOOR_TO_FLOOR = 3.20    # ارتفاع الدور من أرضية لأرضية

# النواة الرأسية: سلم + مصعد + بسطة توزيع. أبعادها ثابتة في كل الأدوار
# لأنها بتخترق المبنى رأسيًا.
STAIR_WIDTH = 2.70       # عرض بيت السلم (قلبتين × 1.20 + منور)
STAIR_LENGTH = 5.20      # طول بيت السلم
LIFT_WIDTH = 1.90        # عرض بئر المصعد
LIFT_DEPTH = 2.10        # عمق بئر المصعد
LANDING_MIN_WIDTH = 1.50  # أقل عرض للبسطة/الممر المشترك
LANDING_IDEAL_WIDTH = 2.20
LIFT_THRESHOLD_FLOORS = 4  # من كام دور فصاعدًا المصعد يبقى إلزامي


@dataclass(frozen=True)
class UnitStandard:
    """معايير الوحدة الواحدة حسب استخدام الدور."""

    min_area: float          # أقل مساحة وحدة معقولة (م²)
    ideal_area: float        # المساحة المفضّلة
    max_area: float          # فوقها الأحسن نقسّمها لوحدتين
    min_width: float         # أقل بُعد للوحدة نفسها
    plan_internally: bool    # هل نوزّع جواها غرف بالمحرك ولا نسيبها فراغ مفتوح
    name_ar: str
    name_en: str
    label_ar: str            # اسم الدور
    label_en: str


UNIT_STANDARDS: dict[str, UnitStandard] = {
    "apartments": UnitStandard(
        55.0, 120.0, 220.0, 5.00, True, "شقة", "Apartment", "شقق سكنية", "Apartments"
    ),
    "offices": UnitStandard(
        35.0, 90.0, 260.0, 4.50, True, "مكتب", "Office Unit", "مكاتب إدارية", "Offices"
    ),
    "clinics": UnitStandard(
        45.0, 85.0, 180.0, 4.50, True, "عيادة", "Clinic", "عيادات", "Clinics"
    ),
    "retail": UnitStandard(
        18.0, 45.0, 160.0, 3.40, False, "محل", "Shop", "محلات تجارية", "Retail"
    ),
    "parking": UnitStandard(
        1e9, 1e9, 1e9, 2.50, False, "جراج", "Parking", "جراج", "Parking"
    ),
    "services": UnitStandard(
        8.0, 25.0, 120.0, 2.50, False, "خدمات", "Service Room", "خدمات", "Services"
    ),
}


def unit_standard(use: str) -> UnitStandard:
    return UNIT_STANDARDS.get(use, UNIT_STANDARDS["apartments"])


def floor_label(level: int, lang: str = "ar") -> str:
    """اسم الدور حسب منسوبه — أرضي، أول، تاني... أو بدروم."""
    if lang == "en":
        if level < 0:
            return f"Basement {abs(level)}" if level < -1 else "Basement"
        if level == 0:
            return "Ground Floor"
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(
            level if level < 20 else level % 10, "th"
        )
        if 11 <= level <= 13:
            suffix = "th"
        return f"{level}{suffix} Floor"

    if level < 0:
        return f"بدروم {abs(level)}" if level < -1 else "بدروم"
    if level == 0:
        return "الدور الأرضي"
    ordinals = {
        1: "الأول", 2: "الثاني", 3: "الثالث", 4: "الرابع", 5: "الخامس",
        6: "السادس", 7: "السابع", 8: "الثامن", 9: "التاسع", 10: "العاشر",
    }
    return f"الدور {ordinals.get(level, str(level))}"
