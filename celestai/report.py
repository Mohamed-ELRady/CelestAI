"""التقرير الوصفي — the written design report (Arabic / English)."""

from __future__ import annotations

from .knowledge import profile
from .models import ArchitecturalProgram, DesignRequest, Layout

SIDE_AR = {"south": "الجنوب", "north": "الشمال", "east": "الشرق", "west": "الغرب"}
SIDE_EN = {"south": "south", "north": "north", "east": "east", "west": "west"}


def _area_table_ar(layout: Layout) -> str:
    rows = [
        "| الفراغ | الأبعاد الصافية (م) | المساحة (م²) | النسبة | الشبابيك (م²) |",
        "|---|---|---|---|---|",
    ]
    total = sum(r.net_area for r in layout.rooms)
    for r in sorted(layout.rooms, key=lambda r: -r.net_area):
        n = r.net_rect
        share = (r.net_area / total * 100) if total else 0
        glaz = f"{r.daylight_area:.2f}" if r.daylight_area else "—"
        rows.append(
            f"| {r.name_ar} | {n.w:.2f} × {n.h:.2f} | {r.net_area:.2f} | "
            f"{share:.1f}% | {glaz} |"
        )
    rows.append(f"| **الإجمالي الصافي** | | **{total:.2f}** | **100%** | |")
    return "\n".join(rows)


def _area_table_en(layout: Layout) -> str:
    rows = ["| Space | Clear dims (m) | Area (m²) | Share | Glazing (m²) |", "|---|---|---|---|---|"]
    total = sum(r.net_area for r in layout.rooms)
    for r in sorted(layout.rooms, key=lambda r: -r.net_area):
        n = r.net_rect
        share = (r.net_area / total * 100) if total else 0
        rows.append(
            f"| {r.name_en} | {n.w:.2f} × {n.h:.2f} | {r.net_area:.2f} | "
            f"{share:.1f}% | {r.daylight_area:.2f} |"
        )
    rows.append(f"| **Net total** | | **{total:.2f}** | **100%** | |")
    return "\n".join(rows)


def build_report(
    req: DesignRequest,
    program: ArchitecturalProgram,
    layout: Layout,
    warning: str | None = None,
) -> str:
    if req.language == "en":
        return _report_en(req, program, layout, warning)
    return _report_ar(req, program, layout, warning)


# ---------------------------------------------------------------------------
# عربي
# ---------------------------------------------------------------------------


def _report_ar(req, program, layout, warning) -> str:
    prof = profile(req.building_type)
    m = layout.metrics
    errors = [i for i in layout.issues if i.severity == "error"]
    warnings = [i for i in layout.issues if i.severity == "warning"]

    parts: list[str] = []
    parts.append(f"# {prof.label_ar} — {req.area:.0f} م²\n")
    parts.append(
        f"> {program.summary_ar}\n"
        if program.summary_ar
        else ""
    )

    if warning:
        parts.append(f"> ⚠️ **ملاحظة تشغيلية:** {warning}\n")

    parts.append("## المعطيات الأساسية\n")
    parts.append(
        f"- **أبعاد القطعة:** {layout.plot.w:.2f} × {layout.plot.h:.2f} م "
        f"({m.get('gross_area', 0):.2f} م² إجمالي)\n"
        f"- **المساحة الصافية القابلة للاستخدام:** {m.get('net_area', 0):.2f} م²\n"
        f"- **كفاءة التوزيع:** {m.get('efficiency', 0) * 100:.1f}% "
        f"(الباقي حوائط — الطبيعي في السكني 80–90%)\n"
        f"- **نسبة فراغ الحركة:** {m.get('circulation_share', 0) * 100:.1f}%\n"
        f"- **جهة المدخل:** {SIDE_AR.get(layout.entry_side, layout.entry_side)}\n"
        f"- **إجمالي أطوال الحوائط:** {m.get('wall_length', 0):.1f} م\n"
        f"- **إجمالي مساحة الشبابيك:** {m.get('glazing_area', 0):.2f} م²\n"
    )

    parts.append("\n## فكرة التوزيع\n")
    parts.append(
        f"التوزيع قائم على **{program.rooms[0].name_ar} مركزية** عمودية على واجهة "
        f"{SIDE_AR.get(layout.entry_side, '')}، بتوزّع على كل الفراغات مباشرة من "
        "غير ممرات ضايعة. كل غرفة بتلمس فراغ الحركة من ناحية (فبتاخد بابها منه) "
        "وبتلمس الواجهة الخارجية من الناحية التانية (فبتاخد شبابيكها منها)، وده "
        "بيضمن إن مفيش فراغ محبوس بدون تهوية.\n"
    )

    if program.design_notes:
        parts.append("\n### قرارات التصميم\n")
        for note in program.design_notes:
            parts.append(f"- {note}\n")

    parts.append("\n## جدول المساحات\n")
    parts.append(_area_table_ar(layout) + "\n")

    parts.append("\n## المراجعة الكودية\n")
    if not errors and not warnings:
        parts.append("✅ المخطط مطابق لكل المعايير المفحوصة: أقل أبعاد للفراغات، "
                     "نسب الإضاءة والتهوية الطبيعية، عروض الأبواب، ووصول كل فراغ "
                     "لمسار الحركة.\n")
    else:
        if errors:
            parts.append(f"\n**مخالفات ({len(errors)})** — محتاجة تعديل قبل التنفيذ:\n")
            for i in errors:
                parts.append(f"- ❌ {i.message_ar}\n")
        if warnings:
            parts.append(f"\n**تنبيهات ({len(warnings)})** — مقبولة بس ممكن تتحسّن:\n")
            for i in warnings:
                parts.append(f"- ⚠️ {i.message_ar}\n")
        if errors:
            parts.append(
                "\n> المخالفات دي نتيجة ضغط البرنامج على المساحة المتاحة. "
                "أسرع حل: تكبّر المساحة، أو تقلّل عدد الغرف، أو تدخل أبعاد قطعة "
                "أطول وأضيق عشان الشرائط تبقى أقل عمقًا.\n"
            )

    parts.append("\n## المعايير المستخدمة\n")
    parts.append(
        "| البند | القيمة المطبَّقة |\n|---|---|\n"
        "| سُمك الحوائط الخارجية | 25 سم |\n"
        "| سُمك الحوائط الداخلية | 12 سم (15 سم للفراغات الرطبة) |\n"
        "| ارتفاع الدور الصافي | 3.00 م |\n"
        "| نسبة الإضاءة للفراغات المعيشية | 1:8 من مساحة الأرضية |\n"
        "| نسبة الإضاءة للمطابخ | 1:10 |\n"
        "| نسبة الإضاءة للحمامات | 1:12 |\n"
        "| أقل عرض باب | 75 سم |\n"
        "| عرض باب المدخل | 105 سم |\n"
    )

    parts.append(
        "\n---\n*اتولّد بواسطة CelestAI — "
        f"مصدر البرنامج المعماري: "
        f"{'الذكاء الاصطناعي (Claude)' if program.source == 'ai' else 'القواعد الهندسية المدمجة'}.*\n"
    )
    return "".join(parts)


# ---------------------------------------------------------------------------
# English
# ---------------------------------------------------------------------------


def _report_en(req, program, layout, warning) -> str:
    prof = profile(req.building_type)
    m = layout.metrics
    errors = [i for i in layout.issues if i.severity == "error"]
    warnings = [i for i in layout.issues if i.severity == "warning"]

    parts = [f"# {prof.label_en} — {req.area:.0f} m²\n"]
    if program.summary_en:
        parts.append(f"> {program.summary_en}\n")
    if warning:
        parts.append(f"> ⚠️ **Note:** {warning}\n")

    parts.append("\n## Key figures\n")
    parts.append(
        f"- **Plot:** {layout.plot.w:.2f} × {layout.plot.h:.2f} m "
        f"({m.get('gross_area', 0):.2f} m² gross)\n"
        f"- **Net usable area:** {m.get('net_area', 0):.2f} m²\n"
        f"- **Planning efficiency:** {m.get('efficiency', 0) * 100:.1f}%\n"
        f"- **Circulation share:** {m.get('circulation_share', 0) * 100:.1f}%\n"
        f"- **Entrance:** {SIDE_EN.get(layout.entry_side, layout.entry_side)}\n"
        f"- **Total wall run:** {m.get('wall_length', 0):.1f} m\n"
        f"- **Total glazing:** {m.get('glazing_area', 0):.2f} m²\n"
    )

    parts.append("\n## Planning concept\n")
    parts.append(
        f"The plan is organised around a central {program.rooms[0].name_en.lower()} "
        f"running perpendicular to the {SIDE_EN.get(layout.entry_side, '')} entrance "
        "façade. Every room touches the circulation space on one side (giving it a "
        "door) and the external façade on the other (giving it daylight and "
        "ventilation), so no space is landlocked.\n"
    )

    if program.design_notes:
        parts.append("\n### Design decisions\n")
        for note in program.design_notes:
            parts.append(f"- {note}\n")

    parts.append("\n## Area schedule\n")
    parts.append(_area_table_en(layout) + "\n")

    parts.append("\n## Code review\n")
    if not errors and not warnings:
        parts.append("✅ Compliant with every rule checked: minimum room dimensions, "
                     "daylight and ventilation ratios, door widths, and circulation "
                     "access to every space.\n")
    else:
        for i in errors:
            parts.append(f"- ❌ {i.message_en}\n")
        for i in warnings:
            parts.append(f"- ⚠️ {i.message_en}\n")

    parts.append(
        f"\n---\n*Generated by CelestAI — program source: "
        f"{'Claude (AI)' if program.source == 'ai' else 'built-in rules'}.*\n"
    )
    return "".join(parts)


# ---------------------------------------------------------------------------
# تقرير المبنى متعدد الأدوار
# ---------------------------------------------------------------------------


def build_building_report(req, floors, warning: str | None = None) -> str:
    """تقرير مبنى: جدول الأدوار، جدول الوحدات، والمراجعة الكودية."""
    from .knowledge import (
        FLOOR_TO_FLOOR,
        SHAFT_MIN_AREA,
        SHAFT_MIN_WIDTH,
        unit_standard,
    )

    ar = req.lang_key == "ar"
    m2 = "م²" if ar else "m²"

    total_built = sum(f.metrics.get("gross_area", 0) for f in floors)
    total_units = sum(len(f.units) for f in floors)
    errors = sum(int(f.metrics.get("errors", 0)) for f in floors)
    warnings = sum(int(f.metrics.get("warnings", 0)) for f in floors)
    plot = floors[0].plot if floors else None
    height = len(floors) * FLOOR_TO_FLOOR

    p: list[str] = []

    if ar:
        p.append(f"# مبنى متعدد الأدوار — {len(floors)} أدوار\n")
        if warning:
            p.append(f"> ⚠️ **ملاحظة تشغيلية:** {warning}\n")
        p.append("## المعطيات الأساسية\n")
        p.append(
            f"- **بصمة المبنى:** {plot.w:.2f} × {plot.h:.2f} م "
            f"({req.area:.2f} {m2} للدور)\n"
            f"- **عدد الأدوار:** {len(floors)}\n"
            f"- **إجمالي المسطح المبني:** {total_built:.2f} {m2}\n"
            f"- **إجمالي الوحدات:** {total_units} وحدة\n"
            f"- **ارتفاع المبنى التقريبي:** {height:.2f} م "
            f"(بواقع {FLOOR_TO_FLOOR:.2f} م للدور)\n"
        )
        p.append("\n## فكرة التوزيع\n")
        p.append(
            "المبنى قائم على **نواة رأسية واحدة** (سلم + مصعد + بسطة توزيع) في "
            "نفس المكان في كل الأدوار، لأنها بتخترق المبنى من تحت لفوق. باقي "
            "مساحة الدور بتتقسّم لوحدات حوالين النواة، وكل وحدة بتلمس البسطة "
            "من ناحية (فبتاخد بابها منها) وواجهة خارجية أو أكتر (فبتاخد "
            "شبابيكها منها).\n\n"
            "الحائط اللي بين وحدتين حائط مشترك، فمش بياخد شبابيك — وده متحسوب "
            "في التوزيع الداخلي لكل وحدة، فالشقة اللي واجهاتها محدودة بتظهر "
            "مخالفات إضاءة صريحة بدل ما نرسم شبابيك على حائط مشترك.\n"
        )

        total_shafts = sum(int(f.metrics.get("shafts", 0)) for f in floors)
        if total_shafts:
            p.append("\n## المناور\n")
            p.append(
                "الوحدة اللي واجهاتها محدودة (وحدة ركن مثلًا) بيبقى فيها فراغ "
                "خدمي مالوش واجهة خارجية. الحل الكودي هو **المنور**: فراغ مكشوف "
                "للسما بيخترق المبنى رأسيًا، والفراغات الملاصقة له بتاخد شبابيك "
                "تهوية وإضاءة عليه.\n\n"
                f"- المنور بيتحسب على ارتفاع المبنى ({len(floors)} أدوار): كل ما "
                f"المبنى علي، المنور بيكبر عشان الهوا والضوء يوصلوا لأقل دور.\n"
                f"- أقل بُعد {SHAFT_MIN_WIDTH:.2f} م، وأقل مساحة "
                f"{SHAFT_MIN_AREA:.2f} {m2}.\n"
                "- **غرف النوم والمعيشة مبتتخدمش بمنور** — الكود بيطلب لها واجهة "
                "خارجية حقيقية، فلو طلعت من غير واجهة بتتسجّل مخالفة صريحة.\n"
                "- المنور لازم يفضل مفتوح لحد السطح: أي دور فوق بيبني مكانه "
                "بيتسجّل كتنبيه في المراجعة.\n"
            )

        p.append("\n## جدول الأدوار\n")
        p.append(
            "| الدور | الاستخدام | الوحدات | مساحة الوحدات | النواة | المناور | الكفاءة |\n"
        )
        p.append("|---|---|---|---|---|---|---|\n")
        for f in floors:
            st = unit_standard(f.use.value)
            fm = f.metrics
            n_sh = int(fm.get("shafts", 0))
            sh = f"{n_sh} · {fm.get('shaft_area', 0):.1f}" if n_sh else "—"
            p.append(
                f"| {f.label_ar} | {st.label_ar} | {int(fm.get('units', 0))} | "
                f"{fm.get('unit_area', 0):.1f} | {fm.get('core_area', 0):.1f} | "
                f"{sh} | {fm.get('efficiency', 0) * 100:.1f}% |\n"
            )
        p.append(f"| **الإجمالي** | | **{total_units}** | | | | |\n")

        p.append("\n## جدول الوحدات\n")
        p.append("| الوحدة | الدور | النوع | الأبعاد (م) | المساحة | الواجهات |\n")
        p.append("|---|---|---|---|---|---|\n")
        for f in floors:
            st = unit_standard(f.use.value)
            for u in f.units:
                n = u.net_rect
                sides = len(u.exterior_sides)
                p.append(
                    f"| {u.name_ar} | {f.label_ar} | {st.name_ar} | "
                    f"{n.w:.2f} × {n.h:.2f} | {u.area:.1f} | {sides} |\n"
                )

        p.append("\n## المراجعة الكودية\n")
        if not errors and not warnings:
            p.append("✅ كل الأدوار مطابقة للمعايير المفحوصة.\n")
        else:
            for f in floors:
                fl_errors = [i for i in f.issues if i.severity == "error"]
                fl_warns = [i for i in f.issues if i.severity == "warning"]
                if not fl_errors and not fl_warns:
                    continue
                p.append(f"\n### {f.label_ar}\n")
                for i in fl_errors:
                    p.append(f"- ❌ {i.message_ar}\n")
                for i in fl_warns:
                    p.append(f"- ⚠️ {i.message_ar}\n")
        p.append(
            "\n---\n*اتولّد بواسطة CelestAI — المخطط مبدئي (schematic): نقطة "
            "بداية للمهندس، مش بديل عن رسومات تنفيذية معتمدة.*\n"
        )
        return "".join(p)

    p.append(f"# Multi-storey building — {len(floors)} floors\n")
    if warning:
        p.append(f"> ⚠️ **Note:** {warning}\n")
    p.append("\n## Key figures\n")
    p.append(
        f"- **Footprint:** {plot.w:.2f} × {plot.h:.2f} m ({req.area:.2f} m² per floor)\n"
        f"- **Floors:** {len(floors)}\n"
        f"- **Total built area:** {total_built:.2f} m²\n"
        f"- **Total units:** {total_units}\n"
        f"- **Approximate height:** {height:.2f} m "
        f"({FLOOR_TO_FLOOR:.2f} m floor-to-floor)\n"
    )
    p.append("\n## Planning concept\n")
    p.append(
        "The building is organised around a **single vertical core** (stair, lift "
        "and landing) held in the same position on every floor, because it runs "
        "the full height of the building. The rest of each floor plate is divided "
        "into units around that core: every unit touches the landing on one side "
        "(giving it a front door) and an external façade on another (giving it "
        "daylight).\n\n"
        "A wall between two units is a party wall and carries no windows. That is "
        "modelled explicitly, so a unit with limited façade exposure reports honest "
        "daylight violations rather than being drawn with windows onto a shared "
        "wall.\n"
    )

    total_shafts = sum(int(f.metrics.get("shafts", 0)) for f in floors)
    if total_shafts:
        p.append("\n## Light wells\n")
        p.append(
            "A unit with limited façade exposure — a corner unit, for instance — "
            "ends up with a service space that has no external wall. The code "
            "answer is a **light well**: an open shaft running the full height of "
            "the building, with the spaces beside it taking ventilation and "
            "daylight windows onto it.\n\n"
            f"- The shaft is sized against the building height ({len(floors)} "
            "floors): the taller the building, the wider the shaft has to be for "
            "air and light to reach the lowest floor it serves.\n"
            f"- Minimum clear dimension {SHAFT_MIN_WIDTH:.2f} m, minimum area "
            f"{SHAFT_MIN_AREA:.2f} m².\n"
            "- **Bedrooms and living rooms are never served by a light well** — "
            "the code requires a real external façade, so a habitable room without "
            "one is reported as an explicit violation.\n"
            "- A shaft has to stay open to the sky: any floor above that builds "
            "over it is flagged in the code review.\n"
        )

    p.append("\n## Floor schedule\n")
    p.append("| Floor | Use | Units | Unit area | Core | Shafts | Efficiency |\n")
    p.append("|---|---|---|---|---|---|---|\n")
    for f in floors:
        st = unit_standard(f.use.value)
        fm = f.metrics
        n_sh = int(fm.get("shafts", 0))
        sh = f"{n_sh} · {fm.get('shaft_area', 0):.1f}" if n_sh else "—"
        p.append(
            f"| {f.label_en} | {st.label_en} | {int(fm.get('units', 0))} | "
            f"{fm.get('unit_area', 0):.1f} | {fm.get('core_area', 0):.1f} | "
            f"{sh} | {fm.get('efficiency', 0) * 100:.1f}% |\n"
        )
    p.append(f"| **Total** | | **{total_units}** | | | | |\n")

    p.append("\n## Unit schedule\n")
    p.append("| Unit | Floor | Type | Dimensions (m) | Area | Façades |\n")
    p.append("|---|---|---|---|---|---|\n")
    for f in floors:
        st = unit_standard(f.use.value)
        for u in f.units:
            n = u.net_rect
            p.append(
                f"| {u.name_en} | {f.label_en} | {st.name_en} | "
                f"{n.w:.2f} × {n.h:.2f} | {u.area:.1f} | {len(u.exterior_sides)} |\n"
            )

    p.append("\n## Code review\n")
    if not errors and not warnings:
        p.append("✅ Every floor complies with the rules checked.\n")
    else:
        for f in floors:
            fl_errors = [i for i in f.issues if i.severity == "error"]
            fl_warns = [i for i in f.issues if i.severity == "warning"]
            if not fl_errors and not fl_warns:
                continue
            p.append(f"\n### {f.label_en}\n")
            for i in fl_errors:
                p.append(f"- ❌ {i.message_en}\n")
            for i in fl_warns:
                p.append(f"- ⚠️ {i.message_en}\n")
    p.append(
        "\n---\n*Generated by CelestAI — this is a schematic plan: a starting "
        "point for the engineer, not a substitute for approved construction "
        "drawings.*\n"
    )
    return "".join(p)
