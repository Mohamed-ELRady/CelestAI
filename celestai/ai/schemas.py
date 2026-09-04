"""نماذج المخرجات المُهيكلة لكل مزايا الـ AI.

كل استدعاء للموديل بيرجّع واحد من دول، وبيتحقق بـ Pydantic قبل ما يوصل لأي
منطق. مفيش أي مكان في المشروع بياخد نص حر من الموديل ويستخدمه كبيانات.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..models import ArchitecturalProgram, RoomKind

# ---------------------------------------------------------------------------
# تعديلات البرنامج — العملة المشتركة بين الحوار والإصلاح والمراجعة
# ---------------------------------------------------------------------------

EditOp = Literal[
    "resize",      # غيّر مساحة فراغ
    "add",         # ضيف فراغ
    "remove",      # شيل فراغ
    "rename",      # غيّر اسم فراغ
    "min_width",   # غيّر أقل بُعد
    "attach",      # اربط فراغ كملحق بغرفة (حمام داخلي)
    "detach",      # فك الارتباط
    "retype",      # غيّر نوع الفراغ
]


class ProgramEdit(BaseModel):
    """تعديل واحد على البرنامج المعماري.

    الموديل بيرجّع **تعديلات** مش برنامج جديد — كده باقي التصميم بيفضل ثابت،
    والمستخدم يقدر يشوف بالظبط اتغيّر إيه ويتراجع عنه.
    """

    op: EditOp
    room_id: str = Field("", description="معرّف الفراغ المستهدف (فاضي مع add)")
    value: Optional[float] = Field(
        None, description="القيمة الجديدة: مساحة بالمتر المربع أو أقل بُعد بالمتر"
    )
    kind: Optional[RoomKind] = Field(None, description="نوع الفراغ مع add/retype")
    name_ar: str = ""
    name_en: str = ""
    target_id: str = Field("", description="الغرفة الأم مع attach")
    reason_ar: str = Field("", description="سبب التعديل بالعامية المصرية")
    reason_en: str = ""


class EditPlan(BaseModel):
    """رد الموديل على طلب تعديل."""

    understood_ar: str = Field("", description="فهمك للطلب في جملة")
    understood_en: str = ""
    edits: list[ProgramEdit] = Field(default_factory=list)
    refused_ar: str = Field(
        "", description="لو الطلب مستحيل هندسيًا، اشرح ليه بدل ما تنفّذ حاجة غلط"
    )
    refused_en: str = ""


# ---------------------------------------------------------------------------
# أ-1 · الإصلاح الذاتي
# ---------------------------------------------------------------------------


class RepairPlan(BaseModel):
    """برنامج معدّل يستهدف مخالفات محدّدة."""

    diagnosis_ar: str = Field(
        "", description="سبب المخالفات في جملة أو اتنين بالعامية المصرية"
    )
    diagnosis_en: str = ""
    program: ArchitecturalProgram


# ---------------------------------------------------------------------------
# أ-3 · المراجع الكودي الذكي
# ---------------------------------------------------------------------------


class FixOption(BaseModel):
    """حل عملي واحد لمخالفة."""

    title_ar: str
    title_en: str = ""
    detail_ar: str = Field("", description="الخطوة بالأرقام: كبّر كذا كام سم على حساب إيه")
    detail_en: str = ""
    trade_off_ar: str = Field("", description="الثمن — إيه اللي هيصغر مقابل ده")
    trade_off_en: str = ""
    edits: list[ProgramEdit] = Field(
        default_factory=list, description="التعديلات اللي تنفّذ الحل ده آليًا"
    )


class IssueAdvice(BaseModel):
    code: str = Field("", description="كود المخالفة زي MIN_WIDTH")
    room_id: str = ""
    root_cause_ar: str = ""
    root_cause_en: str = ""
    fixes: list[FixOption] = Field(default_factory=list)


class ReviewAdvice(BaseModel):
    summary_ar: str = Field("", description="الحالة العامة للمخطط في سطرين")
    summary_en: str = ""
    advice: list[IssueAdvice] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# أ-4 · البدائل بالنيّة
# ---------------------------------------------------------------------------


class DesignThesis(BaseModel):
    """أطروحة تصميمية واحدة — بديل بنيّة واضحة مش مجرد ترتيب مختلف."""

    slug: str = Field(..., description="معرّف قصير بالإنجليزي: generous_living")
    title_ar: str
    title_en: str
    idea_ar: str = Field("", description="الفكرة في جملة: بنكبّر المعيشة على حساب إيه")
    idea_en: str = ""
    program: ArchitecturalProgram


class AlternativeSet(BaseModel):
    options: list[DesignThesis] = Field(default_factory=list)


class AlternativeComparison(BaseModel):
    """مقارنة مكتوبة بين البدائل بعد ما المحرك حلّها."""

    recommendation_slug: str = Field("", description="أنسب بديل ولمين")
    verdict_ar: str = ""
    verdict_en: str = ""
    per_option_ar: dict[str, str] = Field(
        default_factory=dict, description="slug → مكسبه وثمنه في سطرين"
    )
    per_option_en: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# ب-1 · الاسكتش  ·  ب-2 · كروكي الأرض
# ---------------------------------------------------------------------------


class SketchRoom(BaseModel):
    name_ar: str = ""
    name_en: str = ""
    kind: RoomKind = RoomKind.BEDROOM
    approx_area: Optional[float] = Field(None, description="لو مكتوب في الاسكتش")
    relative_size: Literal["small", "medium", "large"] = "medium"
    notes: str = ""


class SketchReading(BaseModel):
    """قراءة اسكتش يد أو bubble diagram."""

    confidence: Literal["low", "medium", "high"] = "low"
    rooms: list[SketchRoom] = Field(default_factory=list)
    adjacency: list[tuple[str, str]] = Field(
        default_factory=list, description="أزواج أسماء إنجليزية متجاورة في الاسكتش"
    )
    entry_side: Literal["north", "south", "east", "west", "auto"] = "auto"
    total_area: Optional[float] = None
    read_back_ar: str = Field("", description="اللي فهمته من الرسمة، للمستخدم يراجعه")
    read_back_en: str = ""
    unreadable_ar: str = Field("", description="حاجات مش واضحة في الرسمة")
    unreadable_en: str = ""


class SiteReading(BaseModel):
    """قراءة كروكي أرض أو رخصة بناء. كل قيمة لازم يأكّدها المستخدم."""

    confidence: Literal["low", "medium", "high"] = "low"
    plot_width: Optional[float] = None
    plot_depth: Optional[float] = None
    plot_area: Optional[float] = None
    street_sides: list[Literal["north", "south", "east", "west"]] = Field(
        default_factory=list, description="الأضلاع المطلّة على شارع"
    )
    setback_front: Optional[float] = None
    setback_back: Optional[float] = None
    setback_sides: Optional[float] = None
    max_floors: Optional[int] = None
    far: Optional[float] = Field(None, description="نسبة البناء لو مذكورة")
    read_back_ar: str = ""
    read_back_en: str = ""
    unreadable_ar: str = ""
    unreadable_en: str = ""


# ---------------------------------------------------------------------------
# د-1 · التكلفة  ·  د-3 · المواصفات
# ---------------------------------------------------------------------------


class CostNarrative(BaseModel):
    summary_ar: str = ""
    summary_en: str = ""
    assumptions_ar: list[str] = Field(default_factory=list)
    assumptions_en: list[str] = Field(default_factory=list)
    savings_ar: list[str] = Field(
        default_factory=list, description="فرص تقليل التكلفة من المخطط ده تحديدًا"
    )
    savings_en: list[str] = Field(default_factory=list)


class RoomFinish(BaseModel):
    room_id: str
    floor_ar: str = ""
    floor_en: str = ""
    walls_ar: str = ""
    walls_en: str = ""
    ceiling_ar: str = ""
    ceiling_en: str = ""
    notes_ar: str = ""
    notes_en: str = ""


class FinishSchedule(BaseModel):
    tier_ar: str = ""
    tier_en: str = ""
    rooms: list[RoomFinish] = Field(default_factory=list)
    general_ar: list[str] = Field(default_factory=list)
    general_en: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# د-2 · التحليل الشمسي (السرد بس — الفيزياء حتمية)
# ---------------------------------------------------------------------------


class SolarAdvice(BaseModel):
    summary_ar: str = ""
    summary_en: str = ""
    per_room_ar: dict[str, str] = Field(default_factory=dict)
    per_room_en: dict[str, str] = Field(default_factory=dict)
    actions_ar: list[str] = Field(default_factory=list)
    actions_en: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# د-4 · الفرش الذكي
# ---------------------------------------------------------------------------


class FurniturePiece(BaseModel):
    name_ar: str
    name_en: str = ""
    width: float = Field(..., gt=0.1, le=6.0, description="بالمتر")
    depth: float = Field(..., gt=0.1, le=6.0)
    against: Literal["wall", "corner", "centre", "any"] = "wall"
    priority: int = Field(3, ge=1, le=5, description="1 = لازم يدخل")
    clearance: float = Field(0.6, ge=0.0, le=2.0, description="خلوص مطلوب قدامه")


class RoomFurnishing(BaseModel):
    room_id: str
    pieces: list[FurniturePiece] = Field(default_factory=list)
    intent_ar: str = ""
    intent_en: str = ""


class FurniturePlan(BaseModel):
    rooms: list[RoomFurnishing] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# هـ-1 · الجدوى (السرد بس — البحث حتمي)
# ---------------------------------------------------------------------------


class ScenarioVerdict(BaseModel):
    scenario_id: str
    pitch_ar: str = Field("", description="السيناريو ده مناسب لمين وليه")
    pitch_en: str = ""
    risk_ar: str = ""
    risk_en: str = ""


class FeasibilityAdvice(BaseModel):
    recommendation_id: str = ""
    reasoning_ar: str = ""
    reasoning_en: str = ""
    verdicts: list[ScenarioVerdict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# ج-1/ج-2 · الكود
# ---------------------------------------------------------------------------


class ExtractedStandard(BaseModel):
    """معيار فراغ مستخرج من نص كود — لازم مراجعة بشرية قبل الاعتماد."""

    kind: RoomKind
    min_area: Optional[float] = None
    min_width: Optional[float] = None
    daylight_ratio: Optional[float] = Field(
        None, description="نسبة الشباك للأرضية كعدد عشري: 0.125 لـ 1:8"
    )
    clause: str = Field("", description="رقم البند في المستند")
    quote: str = Field("", description="نص البند حرفيًا — مصدر الرقم")


class CodeExtraction(BaseModel):
    jurisdiction_ar: str = ""
    jurisdiction_en: str = ""
    source_title: str = ""
    standards: list[ExtractedStandard] = Field(default_factory=list)
    uncertain: list[str] = Field(
        default_factory=list, description="بنود مش متأكد منها — للمراجعة البشرية"
    )


class CodeAnswer(BaseModel):
    answer_ar: str = ""
    answer_en: str = ""
    citations: list[str] = Field(
        default_factory=list, description="البنود اللي الإجابة مبنية عليها"
    )
    confident: bool = True


# ---------------------------------------------------------------------------
# ز-1 · ذاكرة الأسلوب
# ---------------------------------------------------------------------------


class StylePreference(BaseModel):
    key: str = Field(..., description="معرّف قصير: open_kitchen")
    statement_ar: str
    statement_en: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"
    evidence: str = Field("", description="من إيه اتعلمناها")


class StyleProfile(BaseModel):
    preferences: list[StylePreference] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# و-2 · سجل القرارات
# ---------------------------------------------------------------------------


class RationaleNarrative(BaseModel):
    intro_ar: str = ""
    intro_en: str = ""
    sections_ar: dict[str, str] = Field(default_factory=dict)
    sections_en: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# و-1 · حَكَم التقييم
# ---------------------------------------------------------------------------


class BriefCompliance(BaseModel):
    """حَكَم بيقيس: هل المخطط نفّذ الوصف؟ (الجزء الذاتي بس)"""

    score: int = Field(..., ge=0, le=10)
    honoured_ar: list[str] = Field(default_factory=list)
    missed_ar: list[str] = Field(default_factory=list)
    justification_ar: str = ""


# ---------------------------------------------------------------------------
# و-4 · التعريب
# ---------------------------------------------------------------------------


class TranslationBundle(BaseModel):
    language_code: str
    direction: Literal["ltr", "rtl"] = "ltr"
    strings: dict[str, str] = Field(default_factory=dict)
    glossary_notes: list[str] = Field(
        default_factory=list, description="مصطلحات معمارية محتاجة مراجعة بشرية"
    )
