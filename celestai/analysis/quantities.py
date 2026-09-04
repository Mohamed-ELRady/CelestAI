"""حصر الكميات والتكلفة — د-1 · Quantity take-off & costing.

**الحساب حتمي بالكامل.** الهندسة عندنا مضبوطة: أطوال الحوائط وسُمكها موجودة في
`Layout.walls`، ومساحات الفراغات في `net_rect`، وكل فتحة معروف عرضها وارتفاعها.
فحصر الكميات عملية حسابية مباشرة — مفيش أي مجال لهلوسة.

**الأسعار من ملف، مش من ذاكرة الموديل.** سعر مهلوس أسوأ من مفيش سعر خالص، فلو
مفيش جدول أسعار الأداة بتطلّع الكميات من غير فلوس وتقول كده صراحةً.

الـ AI دوره الوحيد هنا: يكتب السرد ويقترح فرص التوفير (`ai/cost.py`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..knowledge import SLAB_HEIGHT, UNROOFED, WET_ROOMS
from ..models import Layout, RoomKind

# ---------------------------------------------------------------------------
# معاملات الحصر — قواعد صنعة، متغيّرة من مشروع لمشروع
# ---------------------------------------------------------------------------

PLASTER_FACES = 2          # الحائط بيتلبّس من الوشين
CEILING_FACTOR = 1.0       # مساحة السقف = مساحة الأرضية
SKIRTING_HEIGHT = 0.10     # وزرة
WASTE_FACTOR = 1.05        # 5% هالك تنفيذ

#: نقاط الكهرباء لكل فراغ (تقدير صنعة: إنارة + بريزة + مفتاح)
ELECTRICAL_POINTS: dict[RoomKind, int] = {
    RoomKind.RECEPTION: 8, RoomKind.LIVING: 8, RoomKind.DINING: 6,
    RoomKind.MASTER_BEDROOM: 7, RoomKind.BEDROOM: 6, RoomKind.KIDS_BEDROOM: 6,
    RoomKind.KITCHEN: 10, RoomKind.BATH: 4, RoomKind.WC: 3,
    RoomKind.OFFICE_ROOM: 6, RoomKind.MEETING: 6, RoomKind.OPEN_OFFICE: 12,
    RoomKind.PANTRY: 4, RoomKind.STORAGE: 2, RoomKind.LAUNDRY: 4,
    RoomKind.BALCONY: 2, RoomKind.CORRIDOR: 3, RoomKind.STAIR: 3,
    RoomKind.EXAM_ROOM: 6, RoomKind.WAITING: 6, RoomKind.SHAFT: 0,
}
ELECTRICAL_DEFAULT = 4

#: نقاط السباكة (صرف + تغذية) لكل فراغ رطب
PLUMBING_POINTS: dict[RoomKind, int] = {
    RoomKind.KITCHEN: 3, RoomKind.BATH: 6, RoomKind.WC: 3,
    RoomKind.LAUNDRY: 3, RoomKind.PANTRY: 2,
}


# ---------------------------------------------------------------------------
# نماذج المخرج
# ---------------------------------------------------------------------------


@dataclass
class BoQItem:
    """بند حصر واحد."""

    code: str
    name_ar: str
    name_en: str
    unit_ar: str
    unit_en: str
    quantity: float
    unit_rate: Optional[float] = None      # سعر الوحدة لو متاح
    note_ar: str = ""
    note_en: str = ""

    @property
    def total(self) -> Optional[float]:
        if self.unit_rate is None:
            return None
        return round(self.quantity * self.unit_rate, 2)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "name_ar": self.name_ar, "name_en": self.name_en,
            "unit_ar": self.unit_ar, "unit_en": self.unit_en,
            "quantity": round(self.quantity, 2),
            "unit_rate": self.unit_rate,
            "total": self.total,
            "note_ar": self.note_ar, "note_en": self.note_en,
        }


@dataclass
class BillOfQuantities:
    items: list[BoQItem] = field(default_factory=list)
    priced: bool = False
    currency: str = ""
    price_source: str = ""
    price_date: str = ""
    #: نطاق التكلفة (من–إلى) — مش رقم واحد، لأن التقدير المبدئي بطبيعته نطاق
    spread: float = 0.15

    @property
    def subtotal(self) -> Optional[float]:
        if not self.priced:
            return None
        totals = [i.total for i in self.items if i.total is not None]
        return round(sum(totals), 2) if totals else None

    @property
    def low(self) -> Optional[float]:
        s = self.subtotal
        return round(s * (1 - self.spread), 2) if s is not None else None

    @property
    def high(self) -> Optional[float]:
        s = self.subtotal
        return round(s * (1 + self.spread), 2) if s is not None else None

    def as_dict(self) -> dict:
        return {
            "items": [i.as_dict() for i in self.items],
            "priced": self.priced,
            "currency": self.currency,
            "price_source": self.price_source,
            "price_date": self.price_date,
            "subtotal": self.subtotal,
            "low": self.low,
            "high": self.high,
        }


# ---------------------------------------------------------------------------
# جدول الأسعار
# ---------------------------------------------------------------------------


@dataclass
class PriceBook:
    """جدول أسعار محلي. **بيتحمّل من ملف — مش من الموديل.**"""

    currency: str = "EGP"
    source: str = ""
    date: str = ""
    rates: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "PriceBook":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            currency=data.get("currency", "EGP"),
            source=data.get("source", str(path)),
            date=data.get("date", ""),
            rates={str(k): float(v) for k, v in data.get("rates", {}).items()},
        )


# ---------------------------------------------------------------------------
# الحصر
# ---------------------------------------------------------------------------


def _opening_area_on(wall, openings) -> float:
    """مساحة الفتحات الواقعة على الحائط ده — بتتخصم من المباني والمحارة."""
    total = 0.0
    for o in openings:
        if o.axis != wall.axis or abs(o.coord - wall.coord) > 1e-3:
            continue
        overlap = min(o.end, wall.end) - max(o.start, wall.start)
        if overlap > 1e-3:
            total += overlap * o.height
    return total


def take_off(
    layout: Layout,
    *,
    floor_height: float = SLAB_HEIGHT,
    prices: PriceBook | None = None,
    floors: int = 1,
) -> BillOfQuantities:
    """يحسب كميات المخطط. `floors` بتضرب الكميات لمبنى متعدد الأدوار."""
    rooms = [r for r in layout.rooms if r.kind != RoomKind.SHAFT]
    roofed = [r for r in rooms if r.kind not in UNROOFED]

    # --- المباني ---
    wall_volume_ext = 0.0
    wall_volume_int = 0.0
    plaster_area = 0.0
    for w in layout.walls:
        gross = w.length * floor_height
        holes = _opening_area_on(w, layout.openings)
        net = max(gross - holes, 0.0)
        if w.exterior:
            wall_volume_ext += net * w.thickness
        else:
            wall_volume_int += net * w.thickness
        plaster_area += net * PLASTER_FACES

    # --- الأرضيات والأسقف ---
    floor_area = sum(r.net_area for r in roofed)
    wet_floor = sum(r.net_area for r in roofed if r.kind in WET_ROOMS)
    dry_floor = floor_area - wet_floor
    ceiling_area = floor_area * CEILING_FACTOR
    balcony_area = sum(r.net_area for r in rooms if r.kind in UNROOFED)

    # --- الوزر ---
    skirting_len = sum(
        2 * (r.net_rect.w + r.net_rect.h) for r in roofed if r.kind not in WET_ROOMS
    )

    # --- الفتحات ---
    doors = [o for o in layout.openings if o.kind == "door"]
    entries = [o for o in layout.openings if o.kind == "entry"]
    windows = [o for o in layout.openings if o.kind == "window"]
    window_area = sum(o.width * o.height for o in windows)

    # --- الكهرباء والسباكة ---
    elec_points = sum(
        ELECTRICAL_POINTS.get(r.kind, ELECTRICAL_DEFAULT) for r in roofed
    )
    plumb_points = sum(PLUMBING_POINTS.get(r.kind, 0) for r in roofed)

    m = floors
    raw: list[BoQItem] = [
        BoQItem("BLK-EXT", "مباني حوائط خارجية", "External blockwork",
                "م³", "m³", wall_volume_ext * m * WASTE_FACTOR),
        BoQItem("BLK-INT", "مباني حوائط داخلية", "Internal blockwork",
                "م³", "m³", wall_volume_int * m * WASTE_FACTOR),
        BoQItem("PLS", "محارة (بياض)", "Plaster",
                "م²", "m²", plaster_area * m * WASTE_FACTOR,
                note_ar="وشين لكل حائط بعد خصم الفتحات",
                note_en="both faces, openings deducted"),
        BoQItem("FLR-DRY", "أرضيات (مناطق جافة)", "Flooring — dry areas",
                "م²", "m²", dry_floor * m * WASTE_FACTOR),
        BoQItem("FLR-WET", "أرضيات وحوائط (مناطق رطبة)", "Flooring & wall tiling — wet areas",
                "م²", "m²", wet_floor * m * WASTE_FACTOR,
                note_ar="سيراميك أرضيات وحوائط", note_en="floor + wall ceramic"),
        BoQItem("CLG", "تشطيب أسقف", "Ceiling finish",
                "م²", "m²", ceiling_area * m),
        BoQItem("SKT", "وزر", "Skirting",
                "م.ط", "lm", skirting_len * m * WASTE_FACTOR),
        BoQItem("DR-INT", "أبواب داخلية", "Internal doors",
                "عدد", "no.", float(len(doors)) * m),
        BoQItem("DR-MAIN", "باب رئيسي", "Entrance door",
                "عدد", "no.", float(len(entries)) * m),
        BoQItem("WIN", "شبابيك", "Windows",
                "م²", "m²", window_area * m,
                note_ar=f"{len(windows) * m} شباك", note_en=f"{len(windows) * m} units"),
        BoQItem("ELE", "نقاط كهرباء", "Electrical points",
                "نقطة", "point", float(elec_points) * m),
        BoQItem("PLB", "نقاط صحية", "Plumbing points",
                "نقطة", "point", float(plumb_points) * m),
    ]
    if balcony_area > 0.05:
        raw.append(BoQItem(
            "BAL", "بلاط بلكونات ودرابزين", "Balcony paving & railing",
            "م²", "m²", balcony_area * m,
        ))

    items = [i for i in raw if i.quantity > 0.005]

    boq = BillOfQuantities(items=items)
    if prices and prices.rates:
        boq.priced = True
        boq.currency = prices.currency
        boq.price_source = prices.source
        boq.price_date = prices.date
        for item in boq.items:
            item.unit_rate = prices.rates.get(item.code)
        if not any(i.unit_rate is not None for i in boq.items):
            boq.priced = False
    return boq


def take_off_building(building_floors, *, prices: PriceBook | None = None):
    """حصر مبنى كامل: كل دور بمخططه المدمج."""
    from ..knowledge import FLOOR_TO_FLOOR

    per_floor = []
    for f in building_floors:
        per_floor.append((f, take_off(f.plate, floor_height=FLOOR_TO_FLOOR,
                                      prices=prices)))

    merged: dict[str, BoQItem] = {}
    for _f, boq in per_floor:
        for item in boq.items:
            if item.code in merged:
                merged[item.code].quantity += item.quantity
            else:
                merged[item.code] = BoQItem(
                    code=item.code, name_ar=item.name_ar, name_en=item.name_en,
                    unit_ar=item.unit_ar, unit_en=item.unit_en,
                    quantity=item.quantity, unit_rate=item.unit_rate,
                    note_ar=item.note_ar, note_en=item.note_en,
                )

    total = BillOfQuantities(items=list(merged.values()))
    if prices and prices.rates:
        total.priced = True
        total.currency = prices.currency
        total.price_source = prices.source
        total.price_date = prices.date
    return total, per_floor


# ---------------------------------------------------------------------------
# التقرير
# ---------------------------------------------------------------------------


def boq_markdown(boq: BillOfQuantities, language: str = "ar") -> str:
    ar = language != "en"
    p: list[str] = []
    p.append("## حصر الكميات\n" if ar else "## Bill of quantities\n")
    p.append(
        "\nالكميات دي **محسوبة من هندسة المخطط مباشرة** — أطوال الحوائط وسُمكها، "
        "ومساحات الفراغات، وعدد الفتحات وأبعادها. مفيش تقدير ولا تخمين فيها.\n"
        if ar else
        "\nThese quantities are **computed directly from the plan geometry** — wall "
        "lengths and thicknesses, room areas, opening counts and sizes. Nothing here "
        "is estimated or guessed.\n"
    )

    if boq.priced:
        p.append("\n| البند | الوحدة | الكمية | سعر الوحدة | الإجمالي |\n" if ar
                 else "\n| Item | Unit | Qty | Rate | Total |\n")
        p.append("|---|---|---|---|---|\n")
        for i in boq.items:
            rate = f"{i.unit_rate:,.2f}" if i.unit_rate is not None else "—"
            total = f"{i.total:,.2f}" if i.total is not None else "—"
            p.append(
                f"| {i.name_ar if ar else i.name_en} | "
                f"{i.unit_ar if ar else i.unit_en} | {i.quantity:,.2f} | "
                f"{rate} | {total} |\n"
            )
        p.append(
            f"\n**التقدير: {boq.low:,.0f} – {boq.high:,.0f} {boq.currency}**\n"
            if ar else
            f"\n**Estimate: {boq.low:,.0f} – {boq.high:,.0f} {boq.currency}**\n"
        )
        p.append(
            f"\n> نطاق مش رقم واحد — التقدير المبدئي بطبيعته نطاق. "
            f"مصدر الأسعار: {boq.price_source or '—'}"
            + (f" · بتاريخ {boq.price_date}" if boq.price_date else "")
            + "\n"
            if ar else
            f"\n> A range, not a single number — a schematic estimate is a range by "
            f"nature. Price source: {boq.price_source or '—'}"
            + (f" · dated {boq.price_date}" if boq.price_date else "")
            + "\n"
        )
    else:
        p.append("\n| البند | الوحدة | الكمية |\n" if ar else "\n| Item | Unit | Qty |\n")
        p.append("|---|---|---|\n")
        for i in boq.items:
            p.append(
                f"| {i.name_ar if ar else i.name_en} | "
                f"{i.unit_ar if ar else i.unit_en} | {i.quantity:,.2f} |\n"
            )
        p.append(
            "\n> **مفيش أسعار.** الكميات دقيقة، لكن الأسعار محتاجة جدول أسعار محلي "
            "(`--prices ملف.json`). مبنحطّش أسعار من ذاكرة الموديل — سعر مهلوس أسوأ "
            "من مفيش سعر.\n"
            if ar else
            "\n> **No prices applied.** The quantities are exact, but pricing needs a "
            "local price book (`--prices file.json`). We never take prices from the "
            "model's memory — a hallucinated price is worse than no price.\n"
        )
    return "".join(p)
