"""CelestAI — من مساحة إلى مخطط هندسي.

CelestAI turns a plot area (plus an optional free-text brief) into a
dimensioned architectural floor plan: SVG, PDF, DXF, 3D and a written report.
"""

__version__ = "0.2.0"


def _load_env_file() -> None:
    """يحمّل مفاتيح الـ API من ملف .env لو موجود في مجلد المشروع — عشان متحتاجش
    تعمل export في كل تيرمينال جديد. مبيغلبش متغيّر بيئة مضبوط فعليًا في الشِل."""
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True), override=False)
    except ImportError:
        pass  # python-dotenv مش متثبّتة — الأداة تفضل تشتغل بمتغيرات البيئة العادية


_load_env_file()
