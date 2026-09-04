"""طبقة التنسيق — the one function the Web / API / CLI all call.

    DesignRequest → ArchitecturalProgram → Layout → ملفات المخرجات
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rationale import RationaleLog

from .drafting import compose, render_svg
from .engine.solver import solve
from .models import (
    ArchitecturalProgram,
    BuildingRequest,
    BuildingResult,
    DesignResult,
    DesignRequest,
    Layout,
    RoomKind,
)
from .planner import ai as ai_planner
from .planner.rules import normalise_program
from .knowledge import profile
from .report import build_building_report, build_report
from .viz3d import build_building_model, build_model


# ---------------------------------------------------------------------------
# تقليم البرنامج لما المساحة متكفّيش
# ---------------------------------------------------------------------------


def _trim_program(
    program: ArchitecturalProgram, language: str = "ar"
) -> ArchitecturalProgram | None:
    """يشيل أقل فراغ أهمية ويعيد توزيع مساحته على الباقي.

    بيتنادى لما أفضل مخطط يطلع فيه مخالفات: بدل ما نسلّم مخطط بغرف تحت الحد
    الأدنى، بنقلّل عدد الفراغات ونسلّم مخطط سليم — وده اللي أي معماري هيعمله.
    """
    # فراغات مينفعش يتشالوا آخر واحد منهم — شقة من غير حمام أو مطبخ مش شقة.
    # الحماية دي على مستوى *النوع* مش الأولوية، عشان لما القائمة الأولى تفضى
    # وننزل للأولوية الأقل، ما نلاقيش نفسنا شايلين آخر حمام.
    essential = {
        RoomKind.KITCHEN: [RoomKind.KITCHEN],
        RoomKind.BATH: [RoomKind.BATH, RoomKind.WC],
        RoomKind.WC: [RoomKind.BATH, RoomKind.WC],
        RoomKind.BEDROOM: [
            RoomKind.BEDROOM, RoomKind.MASTER_BEDROOM, RoomKind.KIDS_BEDROOM,
        ],
        RoomKind.MASTER_BEDROOM: [
            RoomKind.BEDROOM, RoomKind.MASTER_BEDROOM, RoomKind.KIDS_BEDROOM,
        ],
        RoomKind.KIDS_BEDROOM: [
            RoomKind.BEDROOM, RoomKind.MASTER_BEDROOM, RoomKind.KIDS_BEDROOM,
        ],
    }

    def is_last_of_kind(room) -> bool:
        group = essential.get(room.kind)
        if group is None:
            return False
        return sum(1 for r in program.rooms if r.kind in group) <= 1

    candidates = [r for r in program.rooms[1:] if not is_last_of_kind(r)]

    droppable = [
        r for r in candidates
        if r.priority >= 3 and r.kind not in (RoomKind.KITCHEN, RoomKind.BATH)
    ]
    if not droppable:
        droppable = [r for r in candidates if r.priority >= 2]
    if not droppable:
        droppable = candidates
    if not droppable:
        return None

    victim = min(droppable, key=lambda r: (-r.priority, r.target_area))
    freed = victim.target_area
    remaining = [r for r in program.rooms if r.id != victim.id]
    if len(remaining) < 3:
        return None

    # نوزّع المساحة المحرَّرة بالتناسب على اللي فاضل
    total = sum(r.target_area for r in remaining)
    for r in remaining:
        r.target_area = round(r.target_area * (1 + freed / total), 3)
    for r in remaining:
        if r.attach_to == victim.id:
            r.attach_to = None

    trimmed = program.model_copy(deep=True)
    trimmed.rooms = remaining
    trimmed.adjacency = [
        (a, b) for a, b in program.adjacency if victim.id not in (a, b)
    ]
    if language == "en":
        note = (
            f"“{victim.name_en}” ({freed:.1f} m²) was dropped — the area could not "
            "carry it at a workable size, so its space went to the other rooms."
        )
    else:
        note = (
            f"اتشال «{victim.name_ar}» ({freed:.1f} م²) عشان المساحة متسمحش بيه "
            "بأبعاد محترمة، والمساحة اتوزّعت على باقي الفراغات."
        )
    trimmed.design_notes = list(program.design_notes) + [note]
    return trimmed


def _errors(layout: Layout) -> int:
    return int(layout.metrics.get("errors", 0))


def solve_with_trimming(
    program: ArchitecturalProgram,
    req: DesignRequest,
    plot=None,
    attempts: int = 3,
) -> tuple[Layout | None, ArchitecturalProgram, list[Layout]]:
    """يحل التوزيع، ولو طلع مخالف بيقلّم البرنامج ويعيد المحاولة.

    مشتركة بين الوحدة المستقلة والوحدة اللي جوه عمارة — الشقة اللي واجهاتها
    محدودة محتاجة التقليم أكتر من غيرها، فمينفعش يبقى الفرق بينهم إن دي
    بتستفيد من الحلقة ودي لأ.
    """
    from .engine.plot import candidate_plots

    area_ref = plot.area if plot is not None else candidate_plots(req)[0].area
    best: Layout | None = None
    best_program = program
    alts: list[Layout] = []

    current = program
    for _ in range(attempts):
        try:
            layouts = solve(current, req, plot)
        except RuntimeError:
            break
        if not layouts:
            break
        if best is None or layouts[0].score > best.score:
            best, best_program, alts = layouts[0], current, layouts[1:]
        if _errors(layouts[0]) == 0:
            break
        trimmed = _trim_program(current, req.lang_key)
        if trimmed is None:
            break
        current = normalise_program(trimmed, area_ref)

    return best, best_program, alts


# ---------------------------------------------------------------------------
# التوليد
# ---------------------------------------------------------------------------


def generate(
    req: DesignRequest,
    out_dir: str | Path | None = None,
    alternatives: int = 2,
    *,
    repair: bool = False,
    explain: bool = False,
    solar_city: str = "",
    prices=None,
    finishes_tier: str = "",
    furnish: bool = False,
    rationale: "RationaleLog | None" = None,
) -> DesignResult:
    """ينفّذ المسار كامل ويرجّع النتيجة + الملفات.

    الأعلام الاختيارية بتشغّل طبقات إضافية. كلها بتفشل بأمان: لو الـ AI مش
    متاح، المخطط والأرقام بيفضلوا كاملين واللي بيضيع هو السرد بس.
    """
    t0 = time.time()

    from .engine.plot import candidate_plots
    from .rationale import RationaleLog

    log = rationale if rationale is not None else RationaleLog()
    plots = candidate_plots(req)
    base_plot = plots[0]

    # 1) البرنامج المعماري (الـ AI أو القواعد)
    program, warning = ai_planner.build_program(
        req, base_plot.area, base_plot.w, base_plot.h
    )
    program = normalise_program(program, base_plot.area)
    log.add(
        "program",
        f"البرنامج فيه {len(program.rooms)} فراغ",
        what_en=f"Programme with {len(program.rooms)} spaces",
        why_ar=(program.design_notes[0] if program.design_notes else ""),
        by="ai" if program.source == "ai" else "rules",
        rooms=len(program.rooms),
        source=program.source,
    )

    # 2) التوزيع الهندسي — تقليم قواعدي، وإصلاح ذاتي بالـ AI لو مطلوب
    # plot=None للوحدة المستقلة عشان المحرك يجرّب نِسَب قطعة مختلفة
    if repair:
        from .ai.repair import repair_loop

        best, best_program, alts = repair_loop(program, req, None, log_to=log)
    else:
        best, best_program, alts = solve_with_trimming(program, req, None)

    if best is None:
        raise RuntimeError(
            "تعذّر إنتاج مخطط صالح — جرّب مساحة أكبر أو عدد غرف أقل."
        )

    log.add(
        "plot",
        f"القطعة {best.plot.w:.2f} × {best.plot.h:.2f} م، المدخل من {best.entry_side}",
        what_en=(f"Plot {best.plot.w:.2f} x {best.plot.h:.2f} m, "
                 f"entry from the {best.entry_side}"),
        why_ar="النسبة دي طلّعت أقل مخالفات وأحسن أبعاد للفراغات.",
        why_en="This proportion gave the fewest violations and the best room shapes.",
        width=round(best.plot.w, 2), depth=round(best.plot.h, 2),
    )
    log.add(
        "layout",
        f"{int(best.metrics.get('rooms', 0))} فراغ · "
        f"{int(best.metrics.get('errors', 0))} مخالفة · "
        f"كفاءة {best.metrics.get('efficiency', 0) * 100:.1f}%",
        what_en=(f"{int(best.metrics.get('rooms', 0))} spaces · "
                 f"{int(best.metrics.get('errors', 0))} violations · "
                 f"{best.metrics.get('efficiency', 0) * 100:.1f}% efficiency"),
        errors=int(best.metrics.get("errors", 0)),
        warnings=int(best.metrics.get("warnings", 0)),
    )

    result = DesignResult(
        request=req,
        program=best_program,
        layout=best,
        alternatives=alts[:alternatives] if alternatives else [],
        report_md="",
        model3d=build_model(best),
    )

    # 3) الطبقات التحليلية الاختيارية
    extras = _analyse(
        result, req, log,
        explain=explain, solar_city=solar_city, prices=prices,
        finishes_tier=finishes_tier, furnish=furnish,
    )

    # 4) التقرير — بعد التحليل عشان يضم أقسامه
    result.report_md = build_report(req, best_program, best, warning) + extras
    result.rationale = log.as_list()

    # 5) الملفات
    if out_dir:
        result.files = _write_files(result, Path(out_dir))

    result.layout.metrics["solve_seconds"] = round(time.time() - t0, 3)
    return result


def _analyse(
    result: DesignResult,
    req: DesignRequest,
    log,
    *,
    explain: bool = False,
    solar_city: str = "",
    prices=None,
    finishes_tier: str = "",
    furnish: bool = False,
) -> str:
    """يشغّل التحليلات المطلوبة ويرجّع أقسام الماركداون بتاعتها.

    كل طبقة مستقلة: فشل واحدة مبيوقّفش الباقي.
    """
    sections: list[str] = []
    layout, program = result.layout, result.program

    # -- التحليل الشمسي (حتمي) + سرده (AI اختياري) ---------------------
    if solar_city:
        from .analysis.solar import analyse_solar, solar_markdown

        report = analyse_solar(layout, solar_city)
        try:
            from .ai.content import solar_advice

            report.advice = solar_advice(report, req.language)
        except Exception:  # noqa: BLE001
            pass
        result.solar = report.as_dict()
        sections.append("\n\n" + solar_markdown(report, req.language))
        log.add(
            "analysis",
            f"مؤشر الحِمل الصيفي {report.summer_load_index:.2f}",
            what_en=f"Summer load index {report.summer_load_index:.2f}",
            why_ar=f"محسوب لخط عرض {report.city_ar} ({report.latitude:.2f}°).",
            stage_detail="solar",
        )

    # -- حصر الكميات (حتمي) + سرده (AI اختياري) ------------------------
    if prices is not None or req.want_boq:
        from .analysis.quantities import boq_markdown, take_off

        boq = take_off(layout, prices=prices)
        result.boq = boq.as_dict()
        section = boq_markdown(boq, req.language)
        try:
            from .ai.content import cost_narrative, cost_narrative_markdown

            narrative = cost_narrative(boq, layout, req)
            if narrative:
                section += cost_narrative_markdown(narrative, req.language)
        except Exception:  # noqa: BLE001
            pass
        sections.append("\n\n" + section)
        log.add(
            "analysis",
            f"حصر {len(boq.items)} بند"
            + (f" بإجمالي {boq.low:,.0f}–{boq.high:,.0f}" if boq.priced else " بدون أسعار"),
            what_en=f"{len(boq.items)} BoQ items"
                    + (" priced" if boq.priced else ", unpriced"),
            why_ar="الكميات محسوبة من هندسة المخطط مباشرة.",
            stage_detail="boq",
        )

    # -- المراجعة الذكية (AI) ------------------------------------------
    if explain and layout.issues:
        from .ai.review import advice_markdown, explain_issues

        advice = explain_issues(layout, program, req)
        if advice is not None:
            result.review = advice.model_dump()
            sections.append(
                ("\n\n## مراجعة المخالفات\n" if req.lang_key != "en"
                 else "\n\n## Issue review\n")
                + advice_markdown(advice, req.language)
            )

    # -- المواصفات (AI) ------------------------------------------------
    if finishes_tier:
        from .ai.content import finishes_markdown, finishes_schedule

        schedule = finishes_schedule(layout, req, finishes_tier)
        if schedule is not None:
            result.finishes = schedule.model_dump()
            sections.append("\n\n" + finishes_markdown(schedule, req.language))

    # -- الفرش (AI ينوي + مُرصِّف حتمي) ---------------------------------
    if furnish:
        from .ai.furnish import furnish as furnish_plan, furnish_markdown

        plan = furnish_plan(layout, req.language)
        if plan is not None:
            result.furniture = plan.as_dict()
            sections.append("\n\n" + furnish_markdown(plan, req.language))
            log.add(
                "analysis",
                f"{len(plan.placed)} قطعة أثاث اتحطّت، {len(plan.dropped)} مدخلتش",
                what_en=f"{len(plan.placed)} pieces placed, {len(plan.dropped)} dropped",
                by="ai", stage_detail="furniture",
            )

    return "".join(sections)


def generate_options(
    req: DesignRequest,
    out_dir: str | Path | None = None,
    count: int = 3,
    *,
    repair: bool = False,
) -> DesignResult:
    """أ-4 · بدائل بأطروحات تصميمية مختلفة، مش ترتيبات هندسية.

    بيرجّع `DesignResult` للبديل المرشَّح، والباقي في `alternatives`،
    والمقارنة المكتوبة في `options`.

    لو الـ AI مش متاح، بيرجع لـ `generate()` العادية — نفس المخرجات بالظبط.
    """
    from .ai.alternatives import (
        compare_alternatives,
        comparison_markdown,
        generate_alternatives,
    )
    from .engine.plot import candidate_plots
    from .rationale import RationaleLog

    plots = candidate_plots(req)
    base_plot = plots[0]

    theses = generate_alternatives(
        req, base_plot.area, base_plot.w, base_plot.h, count
    )
    if not theses:
        return generate(req, out_dir, alternatives=count - 1, repair=repair)

    log = RationaleLog()
    solved: list[tuple] = []
    for thesis in theses:
        try:
            program = normalise_program(thesis.program, base_plot.area)
            if repair:
                from .ai.repair import repair_loop

                layout, program, _alts = repair_loop(program, req, None, log_to=log)
            else:
                layout, program, _alts = solve_with_trimming(program, req, None)
        except Exception:  # noqa: BLE001 — بديل فاشل مبيوقّفش الباقي
            continue
        if layout is None:
            continue
        thesis.program = program
        solved.append((thesis, layout))
        log.add(
            "program",
            f"بديل «{thesis.title_ar}»: "
            f"{int(layout.metrics.get('errors', 0))} مخالفة، "
            f"كفاءة {layout.metrics.get('efficiency', 0) * 100:.1f}%",
            what_en=f"Option '{thesis.title_en}': "
                    f"{int(layout.metrics.get('errors', 0))} violations",
            why_ar=thesis.idea_ar,
            by="ai", slug=thesis.slug,
        )

    if not solved:
        return generate(req, out_dir, alternatives=count - 1, repair=repair)

    comparison = compare_alternatives(req, solved)

    # المرشَّح: اللي الموديل رشّحه لو حلّه سليم، وإلا أعلى درجة
    chosen = None
    if comparison and comparison.recommendation_slug:
        chosen = next(
            (pair for pair in solved
             if pair[0].slug == comparison.recommendation_slug), None
        )
    if chosen is None:
        chosen = max(solved, key=lambda pair: pair[1].score)

    thesis, layout = chosen
    others = [layout for t, layout in solved if t.slug != thesis.slug]

    result = DesignResult(
        request=req,
        program=thesis.program,
        layout=layout,
        alternatives=others,
        model3d=build_model(layout),
    )
    result.report_md = build_report(req, thesis.program, layout, None)
    if comparison is not None:
        result.options = comparison.model_dump()
        result.report_md += "\n\n" + comparison_markdown(
            comparison, solved, req.language
        )
    result.rationale = log.as_list()

    if out_dir:
        result.files = _write_files(result, Path(out_dir))
    return result


def _slug(req: DesignRequest) -> str:
    return f"celestai-{req.building_type.value}-{req.area:.0f}m2"


def sheet_titles(req: DesignRequest) -> tuple[str, str]:
    """عنوان اللوحة وعنوانها الفرعي باللغة المطلوبة."""
    prof = profile(req.building_type)
    if req.language == "en":
        return (
            f"{prof.label_en} — {req.area:.0f} m\u00b2",
            "Schematic floor plan · CelestAI",
        )
    return (
        f"{prof.label_ar} — {req.area:.0f} م²",
        "مخطط أفقي مبدئي · CelestAI",
    )


def _alt_title(req: DesignRequest, base: str, i: int) -> str:
    return f"{base} — Option {i}" if req.language == "en" else f"{base} — بديل {i}"


def _write_files(result: DesignResult, out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    req = result.request
    base = out_dir / _slug(req)
    files: dict[str, str] = {}

    title, subtitle = sheet_titles(req)
    drawing = compose(
        result.layout, title=title, subtitle=subtitle, language=req.language
    )

    wanted = set(req.outputs)

    if "svg" in wanted:
        p = base.with_suffix(".svg")
        p.write_text(render_svg(drawing, language=req.language), encoding="utf-8")
        files["svg"] = str(p)

    if "pdf" in wanted:
        from .drafting.pdf import render_pdf

        files["pdf"] = render_pdf(drawing, base.with_suffix(".pdf"))

    if "dxf" in wanted:
        from .drafting.dxf import render_dxf

        files["dxf"] = render_dxf(drawing, base.with_suffix(".dxf"))

    if "json3d" in wanted:
        p = base.with_name(base.name + "-3d").with_suffix(".json")
        p.write_text(json.dumps(result.model3d, ensure_ascii=False, indent=2), encoding="utf-8")
        files["json3d"] = str(p)

    if "report" in wanted:
        p = base.with_suffix(".md")
        p.write_text(result.report_md, encoding="utf-8")
        files["report"] = str(p)

    # سجل القرارات — دفتر التصميم (و-2)
    if result.rationale:
        p = base.with_name(base.name + "-rationale").with_suffix(".json")
        p.write_text(json.dumps(result.rationale, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        files["rationale"] = str(p)

    # حصر الكميات كـ CSV — الصيغة اللي بتتفتح في أي برنامج حسابات (د-1)
    if result.boq.get("items"):
        p = base.with_name(base.name + "-boq").with_suffix(".csv")
        p.write_text(_boq_csv(result.boq, req.lang_key), encoding="utf-8-sig")
        files["boq"] = str(p)

    # البدائل كـ SVG
    for i, alt in enumerate(result.alternatives, start=1):
        alt_dw = compose(
            alt, title=_alt_title(req, title, i), subtitle=subtitle,
            language=req.language,
        )
        p = base.with_name(f"{base.name}-alt{i}").with_suffix(".svg")
        p.write_text(render_svg(alt_dw, language=req.language), encoding="utf-8")
        files[f"alt{i}_svg"] = str(p)

    return files


def _boq_csv(boq: dict, lang: str = "ar") -> str:
    """حصر الكميات كـ CSV. utf-8-sig عشان إكسل العربي يفتحه صح."""
    import csv
    import io

    ar = lang != "en"
    buf = io.StringIO()
    w = csv.writer(buf)
    header = (["الكود", "البند", "الوحدة", "الكمية"] if ar
              else ["Code", "Item", "Unit", "Quantity"])
    if boq.get("priced"):
        header += (["سعر الوحدة", "الإجمالي"] if ar else ["Rate", "Total"])
    w.writerow(header)

    for i in boq.get("items", []):
        row = [
            i["code"],
            i["name_ar"] if ar else i["name_en"],
            i["unit_ar"] if ar else i["unit_en"],
            i["quantity"],
        ]
        if boq.get("priced"):
            row += [i.get("unit_rate") or "", i.get("total") or ""]
        w.writerow(row)

    if boq.get("priced"):
        w.writerow([])
        w.writerow(["", "من" if ar else "Low", boq.get("currency", ""), boq.get("low")])
        w.writerow(["", "إلى" if ar else "High", boq.get("currency", ""), boq.get("high")])
    return buf.getvalue()


def render_layout_svg(layout: Layout, req: DesignRequest, title: str = "") -> str:
    default_title, subtitle = sheet_titles(req)
    dw = compose(
        layout,
        title=title or default_title,
        subtitle=subtitle,
        language=req.language,
    )
    return render_svg(dw, language=req.language)


# ---------------------------------------------------------------------------
# المباني متعددة الأدوار
# ---------------------------------------------------------------------------


def building_sheet_titles(req: BuildingRequest, floor) -> tuple[str, str]:
    """عنوان لوحة الدور وعنوانها الفرعي."""
    if req.lang_key == "en":
        return floor.label_en, f"Floor plate · {req.area:.0f} m² · CelestAI"
    return floor.label_ar, f"مخطط دور · {req.area:.0f} م² · CelestAI"


def render_floor_svg(req: BuildingRequest, floor) -> str:
    from .drafting.floorplate import compose_floor_plate

    title, subtitle = building_sheet_titles(req, floor)
    dw = compose_floor_plate(
        floor, title=title, subtitle=subtitle, language=req.language
    )
    return render_svg(dw, language=req.language)


def generate_building(
    req: BuildingRequest, out_dir: str | Path | None = None
) -> BuildingResult:
    """المسار الكامل لمبنى متعدد الأدوار."""
    from .engine.building import compose_building

    t0 = time.time()
    floors = compose_building(req)

    result = BuildingResult(
        request=req,
        floors=floors,
        report_md=build_building_report(req, floors, None),
        model3d=build_building_model(req, floors),
    )

    total_built = sum(f.metrics.get("gross_area", 0) for f in floors)
    result.metrics = {
        "floors": float(len(floors)),
        "units": float(sum(len(f.units) for f in floors)),
        "floor_area": round(req.area, 2),
        "total_built_area": round(total_built, 2),
        "plot_width": round(floors[0].plot.w, 2) if floors else 0.0,
        "plot_depth": round(floors[0].plot.h, 2) if floors else 0.0,
        "avg_efficiency": round(
            sum(f.metrics.get("efficiency", 0) for f in floors) / max(len(floors), 1), 4
        ),
        "errors": float(sum(int(f.metrics.get("errors", 0)) for f in floors)),
        "warnings": float(sum(int(f.metrics.get("warnings", 0)) for f in floors)),
        "solve_seconds": round(time.time() - t0, 3),
    }

    if out_dir:
        result.files = _write_building_files(result, Path(out_dir))
    return result


def _write_building_files(result: BuildingResult, out_dir: Path) -> dict[str, str]:
    from .drafting.floorplate import compose_floor_plate

    out_dir.mkdir(parents=True, exist_ok=True)
    req = result.request
    base = out_dir / f"celestai-building-{req.area:.0f}m2-{len(result.floors)}f"
    files: dict[str, str] = {}
    wanted = set(req.outputs)

    drawings = []
    for floor in result.floors:
        title, subtitle = building_sheet_titles(req, floor)
        drawings.append((floor, compose_floor_plate(
            floor, title=title, subtitle=subtitle, language=req.language
        )))

    if "svg" in wanted:
        for floor, dw in drawings:
            p = base.with_name(f"{base.name}-L{floor.level}").with_suffix(".svg")
            p.write_text(render_svg(dw, language=req.language), encoding="utf-8")
            files[f"svg_L{floor.level}"] = str(p)

    if "pdf" in wanted:
        from .drafting.pdf import render_pdf_multi

        files["pdf"] = render_pdf_multi(
            [dw for _f, dw in drawings], base.with_suffix(".pdf")
        )

    if "dxf" in wanted:
        from .drafting.dxf import render_dxf

        for floor, dw in drawings:
            p = base.with_name(f"{base.name}-L{floor.level}").with_suffix(".dxf")
            files[f"dxf_L{floor.level}"] = render_dxf(dw, p)

    if "json3d" in wanted:
        p = base.with_name(base.name + "-3d").with_suffix(".json")
        p.write_text(json.dumps(result.model3d, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        files["json3d"] = str(p)

    if "report" in wanted:
        p = base.with_suffix(".md")
        p.write_text(result.report_md, encoding="utf-8")
        files["report"] = str(p)

    return files
