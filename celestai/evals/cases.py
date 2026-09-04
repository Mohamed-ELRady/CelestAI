"""حالات التقييم الثابتة — the fixed brief set.

الحالات دي **مينفعش تتغيّر** من غير سبب واضح. لو غيّرناها، النتايج القديمة
بتبقى غير قابلة للمقارنة، والحزمة بتفقد فايدتها كلها.

مختارة عشان تغطي الحالات اللي المشروع فعلًا بيقع فيها:
  • مساحات ضيقة جدًا (الحد اللي التقليم بيشتغل فيه)
  • مساحات كبيرة (الحد اللي التوزيع بيبوظ فيه)
  • طلبات صريحة في الوصف (اختبار إن الوصف اتقرا أصلًا)
  • أنواع مباني غير سكنية (اللي المخالفات بتظهر فيها أكتر)
  • واجهات محدودة (شقة جوه عمارة)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import BuildingType


@dataclass
class EvalCase:
    """حالة واحدة: طلب + التوقعات المفروض تتحقق."""

    case_id: str
    area: float
    building_type: BuildingType
    brief: str = ""
    bedrooms: int | None = None
    bathrooms: int | None = None
    receptions: int | None = None
    entry_side: str = "auto"
    exterior_sides: list[str] = field(default_factory=lambda: [
        "north", "south", "east", "west"
    ])
    #: توقعات موضوعية بتتحقق آليًا
    expect_max_errors: int = 0
    expect_min_rooms: int = 3
    expect_kinds: list[str] = field(default_factory=list)
    note: str = ""


CASES: list[EvalCase] = [
    # -- الحدود الضيقة -----------------------------------------------------
    EvalCase(
        case_id="tiny-studio-40",
        area=40, building_type=BuildingType.APARTMENT,
        brief="استوديو لشخص واحد، أهم حاجة يبقى مفتوح ومريح",
        expect_max_errors=0, expect_min_rooms=3,
        note="أصغر مساحة معقولة — بيختبر التقليم",
    ),
    EvalCase(
        case_id="squeeze-2bed-65",
        area=65, building_type=BuildingType.APARTMENT,
        brief="شقة لأسرة صغيرة، غرفتين نوم لو المساحة تسمح",
        bedrooms=2,
        expect_max_errors=0, expect_min_rooms=5,
        note="مساحة على الحافة — غرفتين نوم في 65 م² صعبة",
    ),

    # -- الحالة الشائعة ----------------------------------------------------
    EvalCase(
        case_id="family-3bed-120",
        area=120, building_type=BuildingType.APARTMENT,
        brief="شقة عيلة، 3 غرف نوم، صالة كبيرة نستقبل فيها ضيوف، ومطبخ أمريكاني",
        bedrooms=3, bathrooms=2,
        expect_max_errors=0, expect_min_rooms=7,
        expect_kinds=["kitchen", "bath"],
        note="الحالة المرجعية — لازم تطلع نضيفة",
    ),
    EvalCase(
        case_id="home-office-95",
        area=95, building_type=BuildingType.APARTMENT,
        brief="شقة لجوز شغال من البيت، عايزين مكتب مقفول بباب، وغرفة نوم واحدة",
        bedrooms=1,
        expect_max_errors=0, expect_min_rooms=5,
        expect_kinds=["office_room"],
        note="بيختبر إن الوصف الحر اتقرا — المكتب مطلوب صراحةً",
    ),
    EvalCase(
        case_id="storage-heavy-110",
        area=110, building_type=BuildingType.APARTMENT,
        brief="عايز مساحة تخزين كبيرة جدًا وغرفة غسيل منفصلة، غرفتين نوم كفاية",
        bedrooms=2,
        expect_max_errors=0, expect_min_rooms=6,
        expect_kinds=["storage"],
        note="طلب صريح غير معتاد — بيختبر الطاعة للوصف",
    ),

    # -- المساحات الكبيرة --------------------------------------------------
    EvalCase(
        case_id="large-villa-220",
        area=220, building_type=BuildingType.VILLA_FLOOR,
        brief="فيلا دور واحد، 4 غرف نوم منها ماستر بحمام داخلي، وصالة معيشة وسفرة منفصلين",
        bedrooms=4, bathrooms=3,
        expect_max_errors=0, expect_min_rooms=9,
        note="مساحة كبيرة — بيختبر إن التوزيع مبيبوظش مع كتر الفراغات",
    ),

    # -- واجهات محدودة -----------------------------------------------------
    EvalCase(
        case_id="party-walls-90",
        area=90, building_type=BuildingType.APARTMENT,
        brief="شقة في عمارة، الواجهة على الشارع بس",
        bedrooms=2,
        exterior_sides=["south"],
        expect_max_errors=0, expect_min_rooms=5,
        note="أصعب حالة إضاءة — 3 حوائط مشتركة",
    ),
    EvalCase(
        case_id="corner-unit-100",
        area=100, building_type=BuildingType.APARTMENT,
        brief="شقة ناصية، واجهتين",
        bedrooms=2, bathrooms=2,
        exterior_sides=["south", "east"],
        expect_max_errors=0, expect_min_rooms=6,
        note="واجهتين — الحالة الشائعة في العمارات",
    ),

    # -- غير سكني ----------------------------------------------------------
    EvalCase(
        case_id="clinic-140",
        area=140, building_type=BuildingType.CLINIC,
        brief="عيادة أسنان، 3 غرف كشف، واستقبال وانتظار محترم",
        expect_max_errors=0, expect_min_rooms=6,
        expect_kinds=["exam_room", "waiting"],
        note="نوع غير سكني — المخالفات بتظهر هنا أكتر",
    ),
    EvalCase(
        case_id="office-180",
        area=180, building_type=BuildingType.OFFICE,
        brief="مكتب شركة صغيرة، مساحة عمل مفتوحة وغرفة اجتماعات",
        expect_max_errors=0, expect_min_rooms=5,
        expect_kinds=["meeting"],
        note="حالة كانت بتطلّع مخالفات كتير قبل الإصلاح الذاتي",
    ),
    EvalCase(
        case_id="office-350",
        area=350, building_type=BuildingType.OFFICE,
        brief="مقر إداري، أوبن سبيس كبير، 3 غرف اجتماعات، ومطبخ صغير",
        expect_max_errors=0, expect_min_rooms=7,
        note="الحالة المرجعية للإصلاح الذاتي — كانت بتطلّع 60 مخالفة",
    ),

    # -- اللغة -------------------------------------------------------------
    EvalCase(
        case_id="english-brief-105",
        area=105, building_type=BuildingType.APARTMENT,
        brief="Two bedrooms, a study nook, and a large open living-dining space. "
              "We entertain often.",
        bedrooms=2,
        expect_max_errors=0, expect_min_rooms=6,
        note="وصف إنجليزي — بيختبر إن اللغة مش بتكسر الفهم",
    ),
]


def case_by_id(case_id: str) -> EvalCase | None:
    return next((c for c in CASES if c.case_id == case_id), None)
