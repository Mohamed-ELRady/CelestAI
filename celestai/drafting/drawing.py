"""نموذج رسم مستقل عن الصيغة — device-independent drawing model.

بنبني الرسمة مرة واحدة كعناصر هندسية بسيطة، وبعدين كل مُصدِّر (SVG / PDF / DXF)
بيحوّلها لصيغته. كده الرسم الهندسي واحد في كل المخرجات.
كل الإحداثيات بالمتر، ومحور y لأعلى.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Anchor = Literal["start", "middle", "end"]


# ---------------------------------------------------------------------------
# الطبقات
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Layer:
    name: str
    colour: str          # HEX للـ SVG/PDF
    aci: int             # رقم لون AutoCAD للـ DXF
    lineweight: float    # ملّيمتر على الورق


LAYERS: dict[str, Layer] = {
    "ROOM_FILL": Layer("A-ROOM-FILL", "#EEF2F7", 254, 0.00),
    "WALL_EXT": Layer("A-WALL-EXTR", "#1B2430", 7, 0.50),
    "WALL_INT": Layer("A-WALL-INTR", "#33404F", 8, 0.35),
    "DOOR": Layer("A-DOOR", "#0F6FBF", 5, 0.18),
    "WINDOW": Layer("A-GLAZ", "#0E8F6F", 3, 0.18),
    "FURNITURE": Layer("A-FURN", "#8A97A6", 9, 0.13),
    "RAILING": Layer("A-RAIL", "#8A97A6", 9, 0.18),
    "DIM": Layer("A-ANNO-DIMS", "#B03A2E", 1, 0.13),
    "TEXT": Layer("A-ANNO-TEXT", "#1B2430", 7, 0.13),
    "TEXT_SUB": Layer("A-ANNO-TEXT-SUB", "#5A6779", 8, 0.13),
    "GRID": Layer("A-GRID", "#C9D2DC", 253, 0.09),
    "TITLE": Layer("A-ANNO-TTLB", "#1B2430", 7, 0.25),
}


# ---------------------------------------------------------------------------
# العناصر
# ---------------------------------------------------------------------------


@dataclass
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str = "WALL_INT"
    dash: tuple[float, ...] | None = None
    width_scale: float = 1.0


@dataclass
class Poly:
    points: list[tuple[float, float]]
    layer: str = "WALL_INT"
    fill: str | None = None
    stroke: bool = True
    closed: bool = True
    dash: tuple[float, ...] | None = None
    width_scale: float = 1.0


@dataclass
class Arc:
    cx: float
    cy: float
    r: float
    a0: float            # درجات
    a1: float
    layer: str = "DOOR"
    dash: tuple[float, ...] | None = None
    width_scale: float = 1.0


@dataclass
class Circle:
    cx: float
    cy: float
    r: float
    layer: str = "FURNITURE"
    fill: str | None = None
    width_scale: float = 1.0


@dataclass
class Text:
    x: float
    y: float
    text: str
    size: float = 0.26           # ارتفاع الحرف بالمتر (في مقياس الرسم)
    layer: str = "TEXT"
    anchor: Anchor = "middle"
    rotation: float = 0.0
    bold: bool = False
    rtl: bool = False


Entity = Line | Poly | Arc | Circle | Text


@dataclass
class Drawing:
    """رسمة كاملة + بيانات الإطار."""

    entities: list[Entity] = field(default_factory=list)
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)  # xmin,ymin,xmax,ymax
    title: str = ""
    subtitle: str = ""
    scale_note: str = ""
    meta: dict[str, str] = field(default_factory=dict)

    # -- أدوات إضافة سريعة -------------------------------------------------

    def add(self, *entities: Entity) -> None:
        self.entities.extend(entities)

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        layer: str = "WALL_INT",
        fill: str | None = None,
        stroke: bool = True,
        dash: tuple[float, ...] | None = None,
        width_scale: float = 1.0,
    ) -> None:
        self.add(
            Poly(
                [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                layer=layer, fill=fill, stroke=stroke, dash=dash, width_scale=width_scale,
            )
        )

    @property
    def width(self) -> float:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> float:
        return self.bounds[3] - self.bounds[1]
