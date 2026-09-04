"""التحليل الشمسي والتوجيه — د-2 · Solar & orientation analysis.

`north_angle` كان موجود في النموذج وبيرسم **سهم الشمال وبس**. حقل ميّت. وفي
مناخ زي مصر، التوجيه من أهم قرارات التصميم: غرفة نوم غربية بتبقى فرن بعد العصر.

الملف ده بيحسب التعرّض الشمسي **حتميًا** (هندسة شمسية، مفيش AI):
  • زاوية الشمس وسمتها لأي خط عرض ويوم وساعة
  • كمية الإشعاع الواقع على كل شباك حسب اتجاهه
  • حِمل الصيف مقابل مكسب الشتا

والنتيجة بتتحوّل لعقوبة توجيه في `_score_room`، فالمحرك **يصمّم أحسن** مش بس
يعلّق على التصميم.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..knowledge import (
    FACADE_PENALTY_HOT,
    HEAT_SENSITIVITY,
    orientation_penalty,
)
from ..models import Layout, RoomKind

__all__ = [
    "CITIES", "SolarReport", "WindowExposure", "analyse_solar", "solar_markdown",
    "orientation_penalty", "FACADE_PENALTY_HOT", "HEAT_SENSITIVITY",
    "facade_irradiation", "sun_position",
]

# ---------------------------------------------------------------------------
# مدن مرجعية (خط العرض بالدرجات)
# ---------------------------------------------------------------------------

CITIES: dict[str, tuple[float, str, str]] = {
    "cairo":     (30.04, "القاهرة", "Cairo"),
    "alex":      (31.20, "الإسكندرية", "Alexandria"),
    "aswan":     (24.09, "أسوان", "Aswan"),
    "hurghada":  (27.26, "الغردقة", "Hurghada"),
    "riyadh":    (24.71, "الرياض", "Riyadh"),
    "jeddah":    (21.49, "جدة", "Jeddah"),
    "dubai":     (25.20, "دبي", "Dubai"),
    "amman":     (31.95, "عمّان", "Amman"),
    "casablanca": (33.57, "الدار البيضاء", "Casablanca"),
    "tunis":     (36.80, "تونس", "Tunis"),
}
DEFAULT_CITY = "cairo"

#: اليوم من السنة لكل موسم
SUMMER_DAY = 172      # 21 يونيو
WINTER_DAY = 355      # 21 ديسمبر

SOLAR_CONSTANT = 1000.0     # واط/م² تقريبي على سطح عمودي في سما صافية


# ---------------------------------------------------------------------------
# هندسة شمسية
# ---------------------------------------------------------------------------


def declination(day_of_year: int) -> float:
    """ميل الشمس بالراديان."""
    return math.radians(23.45) * math.sin(math.radians(360 * (284 + day_of_year) / 365))


def sun_position(lat_deg: float, day: int, hour: float) -> tuple[float, float]:
    """يرجّع (الارتفاع، السمت) بالراديان. السمت 0 = الشمال، بيزيد مع عقارب الساعة."""
    lat = math.radians(lat_deg)
    dec = declination(day)
    hour_angle = math.radians(15.0 * (hour - 12.0))

    sin_alt = (
        math.sin(lat) * math.sin(dec)
        + math.cos(lat) * math.cos(dec) * math.cos(hour_angle)
    )
    sin_alt = max(-1.0, min(1.0, sin_alt))
    altitude = math.asin(sin_alt)

    cos_alt = math.cos(altitude)
    if abs(cos_alt) < 1e-6:
        return altitude, 0.0
    cos_az = (math.sin(dec) - math.sin(altitude) * math.sin(lat)) / (cos_alt * math.cos(lat))
    cos_az = max(-1.0, min(1.0, cos_az))
    azimuth = math.acos(cos_az)
    if hour > 12.0:
        azimuth = 2 * math.pi - azimuth
    return altitude, azimuth


#: اتجاه العمود الخارج من كل واجهة، بالدرجات من الشمال
FACADE_AZIMUTH = {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}


def facade_irradiation(
    facade: str, lat_deg: float, day: int, north_angle: float = 0.0
) -> float:
    """إشعاع يومي تقريبي على واجهة رأسية (واط·ساعة/م²).

    `north_angle` بيدوّر المبنى: 0 = الشمال لأعلى في الرسمة.
    """
    base = FACADE_AZIMUTH.get(facade)
    if base is None:
        return 0.0
    normal = math.radians((base + north_angle) % 360.0)

    total = 0.0
    hour = 5.0
    while hour <= 19.0:
        alt, az = sun_position(lat_deg, day, hour)
        if alt > 0.0:
            # جيب زاوية السقوط على سطح رأسي
            cos_incidence = math.cos(alt) * math.cos(az - normal)
            if cos_incidence > 0:
                total += SOLAR_CONSTANT * cos_incidence * 0.5   # خطوة نص ساعة
        hour += 0.5
    return round(total, 1)


# ---------------------------------------------------------------------------
# تقييم الواجهات — الأساس اللي المحرك بيستخدمه
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# التقرير
# ---------------------------------------------------------------------------


@dataclass
class WindowExposure:
    room_id: str
    room_name_ar: str
    room_name_en: str
    kind: RoomKind
    facade: str
    area: float
    summer_wh: float
    winter_wh: float
    severity: str = "ok"          # ok · watch · hot

    def as_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "room_name_ar": self.room_name_ar, "room_name_en": self.room_name_en,
            "facade": self.facade, "area": round(self.area, 2),
            "summer_wh": self.summer_wh, "winter_wh": self.winter_wh,
            "severity": self.severity,
        }


@dataclass
class SolarReport:
    city: str
    latitude: float
    city_ar: str = ""
    city_en: str = ""
    windows: list[WindowExposure] = field(default_factory=list)
    by_facade: dict[str, float] = field(default_factory=dict)
    summer_load_index: float = 0.0    # 0 = ممتاز، 1+ = مشكلة
    advice: object = None             # SolarAdvice لو الـ AI اشتغل

    @property
    def hot_windows(self) -> list[WindowExposure]:
        return [w for w in self.windows if w.severity == "hot"]

    def as_dict(self) -> dict:
        return {
            "city": self.city, "latitude": self.latitude,
            "city_ar": self.city_ar, "city_en": self.city_en,
            "windows": [w.as_dict() for w in self.windows],
            "by_facade": {k: round(v, 2) for k, v in self.by_facade.items()},
            "summer_load_index": round(self.summer_load_index, 3),
        }


def _window_facade(o, plot) -> str | None:
    """الواجهة اللي الشباك عليها — من إحداثيه على محيط القطعة."""
    if o.axis == "v":
        if abs(o.coord - plot.x) < 1e-3:
            return "west"
        if abs(o.coord - plot.x2) < 1e-3:
            return "east"
    else:
        if abs(o.coord - plot.y) < 1e-3:
            return "south"
        if abs(o.coord - plot.y2) < 1e-3:
            return "north"
    return None          # شباك على منور — مفيش تعرّض مباشر


def analyse_solar(layout: Layout, city: str = DEFAULT_CITY) -> SolarReport:
    """تحليل حتمي بالكامل — مفيش أي استدعاء AI هنا."""
    key = (city or DEFAULT_CITY).strip().lower()
    if key not in CITIES:
        key = DEFAULT_CITY
    lat, city_ar, city_en = CITIES[key]

    rooms = {r.spec_id: r for r in layout.rooms}
    report = SolarReport(city=key, latitude=lat, city_ar=city_ar, city_en=city_en)

    # الإشعاع لكل واجهة يتحسب مرة واحدة
    summer = {f: facade_irradiation(f, lat, SUMMER_DAY, layout.north_angle)
              for f in FACADE_AZIMUTH}
    winter = {f: facade_irradiation(f, lat, WINTER_DAY, layout.north_angle)
              for f in FACADE_AZIMUTH}
    peak = max(summer.values()) or 1.0

    load = 0.0
    total_glass = 0.0
    for o in layout.openings:
        if o.kind != "window":
            continue
        facade = _window_facade(o, layout.plot)
        if facade is None:
            continue
        room = rooms.get(o.room_id)
        if room is None:
            continue

        area = o.width * o.height
        total_glass += area
        report.by_facade[facade] = report.by_facade.get(facade, 0.0) + area

        sensitivity = HEAT_SENSITIVITY.get(room.kind, 0.5)
        share = summer[facade] / peak
        contribution = area * share * sensitivity
        load += contribution

        if share > 0.75 and sensitivity >= 0.8:
            sev = "hot"
        elif share > 0.6 and sensitivity >= 0.5:
            sev = "watch"
        else:
            sev = "ok"

        report.windows.append(WindowExposure(
            room_id=o.room_id,
            room_name_ar=room.name_ar, room_name_en=room.name_en,
            kind=room.kind, facade=facade, area=area,
            summer_wh=summer[facade], winter_wh=winter[facade],
            severity=sev,
        ))

    report.summer_load_index = round(load / total_glass, 3) if total_glass else 0.0
    return report


def solar_markdown(report: SolarReport, language: str = "ar") -> str:
    ar = language != "en"
    p: list[str] = []
    p.append("## التوجيه والتحليل الشمسي\n" if ar else "## Orientation & solar analysis\n")

    city = report.city_ar if ar else report.city_en
    p.append(
        f"\nمحسوب لخط عرض **{city}** ({report.latitude:.2f}°) على شمس 21 يونيو "
        f"و21 ديسمبر. الحساب هندسة شمسية بحتة — مش تقدير.\n"
        if ar else
        f"\nComputed for **{city}** (latitude {report.latitude:.2f}°) against the "
        f"21 June and 21 December sun. Pure solar geometry — not an estimate.\n"
    )

    if report.by_facade:
        p.append("\n| الواجهة | مساحة الزجاج | إشعاع الصيف | إشعاع الشتا |\n" if ar
                 else "\n| Façade | Glazing | Summer | Winter |\n")
        p.append("|---|---|---|---|\n")
        names = {"north": ("شمالية", "North"), "south": ("جنوبية", "South"),
                 "east": ("شرقية", "East"), "west": ("غربية", "West")}
        for facade, glass in sorted(report.by_facade.items(), key=lambda kv: -kv[1]):
            sample = next((w for w in report.windows if w.facade == facade), None)
            s = f"{sample.summer_wh:,.0f}" if sample else "—"
            w = f"{sample.winter_wh:,.0f}" if sample else "—"
            label = names.get(facade, (facade, facade))
            p.append(f"| {label[0] if ar else label[1]} | {glass:.2f} م² | {s} | {w} |\n")

    idx = report.summer_load_index
    verdict_ar = (
        "توجيه ممتاز — الحِمل الصيفي منخفض." if idx < 0.35 else
        "توجيه مقبول، فيه واجهات محتاجة تظليل." if idx < 0.6 else
        "توجيه فيه مشكلة — حِمل صيفي عالي."
    )
    verdict_en = (
        "Excellent orientation — low summer load." if idx < 0.35 else
        "Acceptable, some façades need shading." if idx < 0.6 else
        "Problematic orientation — high summer load."
    )
    p.append(
        f"\n**مؤشر الحِمل الصيفي: {idx:.2f}** — {verdict_ar}\n" if ar else
        f"\n**Summer load index: {idx:.2f}** — {verdict_en}\n"
    )

    hot = report.hot_windows
    if hot:
        p.append("\n### فراغات محتاجة انتباه\n" if ar else "\n### Spaces needing attention\n")
        for w in hot:
            name = w.room_name_ar if ar else w.room_name_en
            face = {"west": ("غربية", "west"), "south": ("جنوبية", "south"),
                    "east": ("شرقية", "east"), "north": ("شمالية", "north")}
            f = face.get(w.facade, (w.facade, w.facade))
            p.append(
                f"- **{name}** — واجهة {f[0]}، {w.area:.2f} م² زجاج. "
                "محتاجة كاسر شمس أو تقليل مساحة الشباك.\n" if ar else
                f"- **{name}** — {f[1]}-facing, {w.area:.2f} m² of glazing. "
                "Needs shading or a smaller opening.\n"
            )

    advice = report.advice
    if advice is not None:
        actions = advice.actions_ar if ar else (advice.actions_en or advice.actions_ar)
        summary = advice.summary_ar if ar else (advice.summary_en or advice.summary_ar)
        if summary:
            p.append(f"\n{summary}\n")
        if actions:
            p.append("\n### توصيات\n" if ar else "\n### Recommendations\n")
            for a in actions:
                p.append(f"- {a}\n")
    return "".join(p)
