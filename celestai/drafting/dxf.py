"""مُصدِّر DXF — يفتح مباشرة في AutoCAD / Revit / BricsCAD.

الوحدات: متر حقيقي (INSUNITS = 6)، وكل عنصر على طبقته الصحيحة عشان المهندس
يقدر يشتغل على الملف على طول.
"""

from __future__ import annotations

from pathlib import Path

from .drawing import LAYERS, Arc, Circle, Drawing, Line, Poly, Text


def render_dxf(dw: Drawing, path: str | Path) -> str:
    import ezdxf

    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 6            # متر
    doc.header["$MEASUREMENT"] = 1         # متري
    msp = doc.modelspace()

    for key, layer in LAYERS.items():
        if layer.name not in doc.layers:
            doc.layers.add(
                name=layer.name,
                color=layer.aci,
                lineweight=int(round(layer.lineweight * 100)) or -3,
            )

    def L(key: str) -> str:
        return LAYERS[key].name

    for e in dw.entities:
        if isinstance(e, Line):
            msp.add_line((e.x1, e.y1), (e.x2, e.y2), dxfattribs={"layer": L(e.layer)})

        elif isinstance(e, Poly):
            msp.add_lwpolyline(
                e.points, close=e.closed, dxfattribs={"layer": L(e.layer)}
            )
            if e.fill:
                hatch = msp.add_hatch(
                    color=LAYERS[e.layer].aci, dxfattribs={"layer": L(e.layer)}
                )
                hatch.paths.add_polyline_path(e.points, is_closed=True)

        elif isinstance(e, Arc):
            msp.add_arc(
                center=(e.cx, e.cy), radius=e.r,
                start_angle=e.a0, end_angle=e.a1,
                dxfattribs={"layer": L(e.layer)},
            )

        elif isinstance(e, Circle):
            msp.add_circle((e.cx, e.cy), e.r, dxfattribs={"layer": L(e.layer)})

        elif isinstance(e, Text):
            align = {"start": "LEFT", "middle": "CENTER", "end": "RIGHT"}[e.anchor]
            t = msp.add_text(
                e.text,
                height=e.size,
                rotation=e.rotation,
                dxfattribs={"layer": L(e.layer), "style": "OpenSans"},
            )
            t.set_placement((e.x, e.y), align=ezdxf.enums.TextEntityAlignment[align])

    path = Path(path)
    doc.saveas(path)
    return str(path)
