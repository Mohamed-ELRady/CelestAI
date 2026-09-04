"""نماذج البيانات الأساسية لـ CelestAI — Core domain models."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# التعدادات — Enumerations
# ---------------------------------------------------------------------------


class BuildingType(str, Enum):
    APARTMENT = "apartment"        # شقة سكنية
    VILLA_FLOOR = "villa_floor"    # دور فيلا
    OFFICE = "office"              # مكتب إداري
    CLINIC = "clinic"              # عيادة
    GENERIC = "generic"            # فراغ عام


class RoomKind(str, Enum):
    RECEPTION = "reception"        # صالة / ريسبشن (فراغ التوزيع المركزي)
    LIVING = "living"              # معيشة
    DINING = "dining"              # سفرة
    BEDROOM = "bedroom"            # غرفة نوم
    MASTER_BEDROOM = "master_bedroom"
    KIDS_BEDROOM = "kids_bedroom"
    KITCHEN = "kitchen"            # مطبخ
    BATH = "bath"                  # حمام
    WC = "wc"                      # دورة مياه
    OFFICE_ROOM = "office_room"    # مكتب / دراسة
    MEETING = "meeting"            # غرفة اجتماعات
    OPEN_OFFICE = "open_office"    # مساحة عمل مفتوحة
    PANTRY = "pantry"              # بانتري
    STORAGE = "storage"            # تخزين
    LAUNDRY = "laundry"            # غسيل
    BALCONY = "balcony"            # بلكونة / تراس
    SHAFT = "shaft"                # منور (فراغ مكشوف للتهوية والإضاءة)
    STAIR = "stair"                # سلم
    CORRIDOR = "corridor"          # ممر
    EXAM_ROOM = "exam_room"        # غرفة كشف
    WAITING = "waiting"            # انتظار


class Zone(str, Enum):
    DAY = "day"                    # نهاري
    NIGHT = "night"                # ليلي
    SERVICE = "service"            # خدمي
    CIRCULATION = "circulation"    # حركة


Side = Literal["north", "south", "east", "west", "auto"]
OutputFormat = Literal["svg", "pdf", "dxf", "json3d", "report"]
Language = Literal["ar", "en"]


# ---------------------------------------------------------------------------
# طلب التصميم — Design request
# ---------------------------------------------------------------------------


class DesignRequest(BaseModel):
    """المدخلات اللي المستخدم بيديها للأداة."""

    building_type: BuildingType = BuildingType.APARTMENT
    area: float = Field(..., gt=15, le=5000, description="المساحة الإجمالية بالمتر المربع")
    width: Optional[float] = Field(None, gt=2, description="عرض قطعة الأرض/الوحدة (م)")
    depth: Optional[float] = Field(None, gt=2, description="عمق قطعة الأرض/الوحدة (م)")

    bedrooms: Optional[int] = Field(None, ge=0, le=8)
    bathrooms: Optional[int] = Field(None, ge=0, le=6)
    receptions: Optional[int] = Field(None, ge=0, le=3)

    entry_side: Side = "auto"
    north_angle: float = Field(0.0, description="زاوية الشمال بالدرجات (0 = الشمال لأعلى)")

    brief: str = Field("", max_length=2000, description="وصف حر بالعربي أو الإنجليزي")
    language: Language = "ar"
    outputs: list[OutputFormat] = Field(default_factory=lambda: ["svg", "report"])

    use_ai: bool = True
    model: str = "claude-opus-5"
    seed: int = 0

    # الواجهات المطلّة على الخارج فعليًا. الوحدة المستقلة عندها الأربعة، لكن
    # الشقة جوه عمارة بتلاصق جيرانها فبعض أضلاعها حوائط مشتركة من غير شبابيك.
    exterior_sides: list[Literal["north", "south", "east", "west"]] = Field(
        default_factory=lambda: ["north", "south", "east", "west"]
    )

    # عدد الأدوار اللي المنور بيخدمها — بيكبّر المنور كل ما المبنى علي، لأن
    # المنور العميق بيحتاج فتحة أوسع عشان الهوا والضوء يوصلوا لتحت.
    shaft_floors: int = Field(1, ge=1, le=60)

    #: حصر كميات من غير أسعار — الكميات حتمية فمتاحة دايمًا
    want_boq: bool = False

    #: كود البناء المطبَّق (ج-1). "eg" هو المصري المراجَع.
    code_id: str = "eg"

    @field_validator("width", "depth")
    @classmethod
    def _round_dim(cls, v: Optional[float]) -> Optional[float]:
        return None if v is None else round(v, 2)

    @property
    def lang_key(self) -> str:
        """اللغة كمفتاح مضمون إنه 'ar' أو 'en'."""
        return "en" if self.language == "en" else "ar"


# ---------------------------------------------------------------------------
# البرنامج المعماري — Architectural program (AI or rules output)
# ---------------------------------------------------------------------------


class RoomSpec(BaseModel):
    """مواصفة فراغ واحد قبل التوزيع الهندسي."""

    id: str = Field(..., description="معرف فريد بالإنجليزي، مثال: bed_1")
    name_ar: str
    name_en: str
    kind: RoomKind
    target_area: float = Field(..., gt=0, description="المساحة المستهدفة بالمتر المربع")
    min_width: float = Field(2.4, gt=0.8, description="أقل بُعد مسموح به (م)")
    zone: Zone = Zone.DAY
    needs_window: bool = True
    is_wet: bool = False
    priority: int = Field(3, ge=1, le=5, description="1 = الأهم")
    attach_to: Optional[str] = Field(
        None, description="لو الفراغ ملحق بغرفة تانية (حمام داخل ماستر) اكتب id الغرفة الأم"
    )
    notes: str = ""


class ArchitecturalProgram(BaseModel):
    """ناتج مرحلة التخطيط: قائمة الفراغات وعلاقاتها."""

    building_type: BuildingType = BuildingType.APARTMENT
    summary_ar: str = ""
    summary_en: str = ""
    rooms: list[RoomSpec]
    adjacency: list[tuple[str, str]] = Field(
        default_factory=list, description="أزواج ids يفضَّل تجاورها"
    )
    design_notes: list[str] = Field(default_factory=list)
    source: Literal["ai", "rules", "hybrid"] = "rules"

    def by_id(self, rid: str) -> Optional[RoomSpec]:
        return next((r for r in self.rooms if r.id == rid), None)


# ---------------------------------------------------------------------------
# الهندسة — Geometry
# ---------------------------------------------------------------------------


class Rect(BaseModel):
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def inset(self, d: float) -> "Rect":
        return Rect(x=self.x + d, y=self.y + d, w=max(self.w - 2 * d, 0.01), h=max(self.h - 2 * d, 0.01))


class Opening(BaseModel):
    """فتحة (باب أو شباك) على حائط محوري."""

    kind: Literal["door", "window", "entry", "opening"]
    axis: Literal["h", "v"]          # اتجاه الحائط: h = أفقي، v = رأسي
    coord: float                      # y للحوائط الأفقية، x للرأسية
    start: float                      # بداية الفتحة على محور الحائط
    width: float
    room_id: str = ""
    swing: int = 1                    # اتجاه فتح الباب (+1 / -1)
    hinge: int = 1                    # جهة المفصلة (+1 = البداية)
    sill: float = 0.0                 # منسوب الجلسة للشبابيك (م)
    height: float = 2.1               # ارتفاع الفتحة (م)

    @property
    def end(self) -> float:
        return self.start + self.width

    @property
    def mid(self) -> float:
        return self.start + self.width / 2


class WallSegment(BaseModel):
    axis: Literal["h", "v"]
    coord: float
    start: float
    end: float
    thickness: float
    exterior: bool = False

    @property
    def length(self) -> float:
        return self.end - self.start


class PlacedRoom(BaseModel):
    spec_id: str
    name_ar: str
    name_en: str
    kind: RoomKind
    zone: Zone
    rect: Rect                        # حدود محورية (centerline)
    net_rect: Rect                    # الصافي بعد خصم نص سُمك الحوائط
    target_area: float
    is_wet: bool = False
    has_window: bool = False
    daylight_area: float = 0.0

    @property
    def net_area(self) -> float:
        return self.net_rect.area


class Issue(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message_ar: str
    message_en: str
    room_id: str = ""


class Layout(BaseModel):
    """المخطط النهائي جاهز للرسم."""

    plot: Rect
    rooms: list[PlacedRoom]
    walls: list[WallSegment]
    openings: list[Opening]
    entry_side: Side = "south"
    north_angle: float = 0.0
    score: float = 0.0
    metrics: dict[str, float] = Field(default_factory=dict)
    issues: list[Issue] = Field(default_factory=list)

    def room(self, rid: str) -> Optional[PlacedRoom]:
        return next((r for r in self.rooms if r.spec_id == rid), None)


class DesignResult(BaseModel):
    """الناتج الكامل: البرنامج + المخطط + الملفات."""

    request: DesignRequest
    program: ArchitecturalProgram
    layout: Layout
    alternatives: list[Layout] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict, description="format -> path")
    report_md: str = ""
    model3d: dict = Field(default_factory=dict)

    # -- مخرجات الطبقات التحليلية (كلها اختيارية) ------------------------
    #: سجل القرارات (و-2) — ليه كل حاجة اتعملت كده
    rationale: list[dict] = Field(default_factory=list)
    #: حصر الكميات (د-1)
    boq: dict = Field(default_factory=dict)
    #: التحليل الشمسي (د-2)
    solar: dict = Field(default_factory=dict)
    #: شرح المخالفات وحلولها (أ-3)
    review: dict = Field(default_factory=dict)
    #: جدول التشطيبات (د-3)
    finishes: dict = Field(default_factory=dict)
    #: الفرش (د-4)
    furniture: dict = Field(default_factory=dict)
    #: مقارنة البدائل بالنيّة (أ-4)
    options: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# المباني متعددة الأدوار — Multi-storey buildings
# ---------------------------------------------------------------------------


class FloorUse(str, Enum):
    APARTMENTS = "apartments"      # شقق سكنية
    OFFICES = "offices"            # مكاتب إدارية
    CLINICS = "clinics"            # عيادات
    RETAIL = "retail"              # محلات تجارية
    PARKING = "parking"            # جراج
    SERVICES = "services"          # خدمات / بدروم / سطح


class FloorSpec(BaseModel):
    """تعريف دور واحد في المبنى."""

    level: int = Field(..., ge=-3, le=60, description="0 = الدور الأرضي")
    use: FloorUse = FloorUse.APARTMENTS
    units: Optional[int] = Field(
        None, ge=1, le=8, description="عدد الوحدات في الدور، None = تلقائي حسب المساحة"
    )
    label: str = ""


class BuildingRequest(BaseModel):
    """طلب تصميم مبنى متعدد الأدوار."""

    area: float = Field(..., gt=40, le=5000, description="مساحة الدور النموذجي (م²)")
    width: Optional[float] = Field(None, gt=4)
    depth: Optional[float] = Field(None, gt=4)

    floors: list[FloorSpec] = Field(..., min_length=1, max_length=60)

    entry_side: Side = "auto"
    north_angle: float = 0.0

    brief: str = Field("", max_length=2000)
    language: Language = "ar"
    outputs: list[OutputFormat] = Field(default_factory=lambda: ["svg", "report"])

    use_ai: bool = True
    model: str = "claude-opus-5"

    @field_validator("width", "depth")
    @classmethod
    def _round_dim(cls, v: Optional[float]) -> Optional[float]:
        return None if v is None else round(v, 2)

    @property
    def lang_key(self) -> str:
        return "en" if self.language == "en" else "ar"

    @property
    def floor_count(self) -> int:
        return len(self.floors)


class CoreElement(BaseModel):
    """عنصر في النواة الرأسية المشتركة (سلم، مصعد، بسطة)."""

    kind: Literal["stair", "lift", "landing", "shaft"]
    name_ar: str
    name_en: str
    rect: Rect
    net_rect: Rect


class UnitPlan(BaseModel):
    """وحدة واحدة في دور — شقة أو مكتب أو محل."""

    unit_id: str
    name_ar: str
    name_en: str
    use: FloorUse
    rect: Rect                      # بإحداثيات الدور
    net_rect: Rect
    exterior_sides: list[str] = Field(default_factory=list)
    entry_side: str = "south"
    layout: Optional[Layout] = None  # المخطط الداخلي، بإحداثيات الدور كمان
    issues: list[Issue] = Field(default_factory=list)

    @property
    def area(self) -> float:
        return self.net_rect.area


class FloorPlan(BaseModel):
    """دور كامل: نواة + وحدات + مخطط قابل للرسم."""

    level: int
    use: FloorUse
    label_ar: str = ""
    label_en: str = ""
    plot: Rect
    units: list[UnitPlan] = Field(default_factory=list)
    core: list[CoreElement] = Field(default_factory=list)
    plate: Layout                    # المخطط المدمج الجاهز للرسم
    #: مناور الدور — المنور بيخترق الأدوار لفوق لحد السطح، فمكانه بيتقارن
    #: بين الأدوار عشان نتأكد إنه متصل.
    shafts: list[Rect] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    issues: list[Issue] = Field(default_factory=list)


class BuildingResult(BaseModel):
    """الناتج الكامل لمبنى متعدد الأدوار."""

    request: BuildingRequest
    floors: list[FloorPlan]
    files: dict[str, str] = Field(default_factory=dict)
    report_md: str = ""
    model3d: dict = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
