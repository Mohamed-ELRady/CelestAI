"""تحليلات حتمية فوق المخطط — deterministic analyses on top of a solved plan.

الحاجات دي **مش بتستخدم AI** في الحساب. الهندسة عندنا مضبوطة، فالكميات
والتحليل الشمسي والجدوى كلها حساب مباشر. الـ AI بيتنادى بعدين وبس عشان
يفسّر النتيجة بلغة بني آدمين — ولو مش متاح، الأرقام بتفضل موجودة كاملة.
"""

from .quantities import BillOfQuantities, take_off
from .solar import SolarReport, analyse_solar
from .feasibility import FeasibilityStudy, Scenario, study_feasibility

__all__ = [
    "BillOfQuantities",
    "take_off",
    "SolarReport",
    "analyse_solar",
    "FeasibilityStudy",
    "Scenario",
    "study_feasibility",
]
