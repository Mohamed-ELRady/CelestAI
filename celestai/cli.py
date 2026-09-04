"""واجهة سطر الأوامر — celestai CLI."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .knowledge import PROFILES
from .models import BuildingType, DesignRequest
from pathlib import Path

from .planner.ai import active_provider_label, credentials_available
from .service import generate, generate_options

BOLD, DIM, RED, YEL, GRN, CYN, OFF = (
    "\033[1m", "\033[2m", "\033[31m", "\033[33m", "\033[32m", "\033[36m", "\033[0m"
)

# نصوص ملخّص سطر الأوامر بلغتين
CLI_STRINGS = {
    "ar": {
        "m": "م", "m2": "م²", "seconds": "ث",
        "programSource": "البرنامج المعماري",
        "srcAi": "Claude", "srcOpenai": "مزوّد متوافق مع OpenAI", "srcRules": "القواعد المدمجة",
        "generating": "جاري التوليد…",
        "spaces": "الفراغات", "figures": "الأرقام",
        "plot": "أبعاد القطعة", "netArea": "المساحة الصافية",
        "efficiency": "كفاءة", "circulation": "فراغ الحركة",
        "glazing": "مساحة الشبابيك", "solveTime": "زمن التوليد",
        "codeReview": "المراجعة الكودية",
        "allGood": "مطابق لكل المعايير المفحوصة",
        "files": "الملفات",
        "notANumber": "المساحة لازم تكون رقم (أو 'serve' لتشغيل الويب).",
        "serveRunning": "تطبيق الويب شغّال على",
        "aiOn": "الذكاء الاصطناعي متاح ✦",
        "aiOff": "الذكاء الاصطناعي مش متاح — القواعد المدمجة هتشتغل",
    },
    "en": {
        "m": "m", "m2": "m²", "seconds": "s",
        "programSource": "Architectural programme",
        "srcAi": "Claude", "srcOpenai": "OpenAI-compatible provider", "srcRules": "built-in rules",
        "generating": "generating…",
        "spaces": "Spaces", "figures": "Figures",
        "plot": "Plot", "netArea": "Net area",
        "efficiency": "efficiency", "circulation": "Circulation",
        "glazing": "Glazing", "solveTime": "Solve time",
        "codeReview": "Code review",
        "allGood": "Compliant with every rule checked",
        "files": "Files",
        "notANumber": "Area must be a number (or 'serve' to start the web app).",
        "serveRunning": "web app running at",
        "aiOn": "AI available ✦",
        "aiOff": "AI unavailable — the built-in rules will be used",
    },
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="celestai",
        description="CelestAI — مخططات معمارية بالذكاء الاصطناعي / AI-assisted architectural floor plans.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "أمثلة:\n"
            "  celestai 120                       # شقة 120 م²، مخرجات SVG + تقرير\n"
            "  celestai 180 --type villa_floor --bedrooms 4 -f svg pdf dxf\n"
            "  celestai 95 --brief 'مطبخ أمريكاني ومكتب للشغل من البيت'\n"
            "  celestai 250 --type office --width 20 -o ./out\n"
            "  celestai serve                     # يشغّل تطبيق الويب\n"
        ),
    )
    p.add_argument("area", nargs="?", help="المساحة بالمتر المربع، أو 'serve' لتشغيل الويب")
    p.add_argument("--type", "-t", default="apartment",
                   choices=[b.value for b in BuildingType], help="نوع المبنى")
    p.add_argument("--width", type=float, help="عرض القطعة (م)")
    p.add_argument("--depth", type=float, help="عمق القطعة (م)")
    p.add_argument("--bedrooms", type=int, help="عدد غرف النوم")
    p.add_argument("--bathrooms", type=int, help="عدد الحمّامات")
    p.add_argument("--receptions", type=int, help="عدد الصالات")
    p.add_argument("--entry", default="auto",
                   choices=["auto", "north", "south", "east", "west"], help="جهة المدخل")
    p.add_argument("--brief", "-b", default="", help="وصف حر بالعربي أو الإنجليزي")
    p.add_argument("--formats", "-f", nargs="+", default=["svg", "report"],
                   choices=["svg", "pdf", "dxf", "json3d", "report"], help="صيغ المخرجات")
    p.add_argument("--out", "-o", default="./celestai-output", help="مجلد المخرجات")
    p.add_argument("--lang", default="ar", choices=["ar", "en"],
                   help="لغة المخططات والتقارير والمخرجات / output language")
    p.add_argument("--no-ai", action="store_true", help="استخدم القواعد المدمجة فقط")
    p.add_argument("--model", default="claude-opus-5",
                   help="موديل Claude (بيتجاهله لو CELESTAI_AI_PROVIDER=openai — استخدم "
                        "CELESTAI_AI_MODEL بدل منه)")
    p.add_argument("--alternatives", type=int, default=2, help="عدد البدائل")
    p.add_argument("--json", action="store_true", help="اطبع النتيجة JSON بدل التقرير")
    p.add_argument("--port", type=int, default=8000, help="بورت الويب مع serve")
    p.add_argument("--host", default="127.0.0.1", help="عنوان الويب مع serve")
    b = p.add_argument_group("مبنى متعدد الأدوار / multi-storey building")
    b.add_argument("--building", action="store_true",
                   help="وضع المبنى: المساحة بتبقى مساحة الدور النموذجي")
    b.add_argument("--floors", type=int, default=5,
                   help="عدد الأدوار (مع --building)")
    b.add_argument("--floor-plan", "-F", action="append", default=[],
                   metavar="SPEC",
                   help=("استخدام الأدوار بالصيغة LEVELS:USE[:UNITS] — "
                         "مثال: -F 0:retail:4 -F 1-4:apartments:2"))
    a = p.add_argument_group("تحليل ومزايا الذكاء الاصطناعي / analysis & AI")
    a.add_argument("--repair", action="store_true",
                   help="أ-1 حلقة إصلاح ذاتي: يودّي المخالفات للموديل ويعيد الحل")
    a.add_argument("--explain", action="store_true",
                   help="أ-3 اشرح كل مخالفة واقترح حلول عملية بالأرقام")
    a.add_argument("--options", type=int, default=0, metavar="N",
                   help="أ-4 ولّد N بدائل بأطروحات تصميمية مختلفة (مش ترتيبات)")
    a.add_argument("--boq", action="store_true",
                   help="د-1 حصر كميات (حتمي، شغال من غير AI)")
    a.add_argument("--prices", metavar="FILE",
                   help="د-1 جدول أسعار JSON — من غيره الكميات بتطلع بدون أسعار")
    a.add_argument("--solar", nargs="?", const="cairo", metavar="CITY",
                   help="د-2 تحليل شمسي للمدينة دي (الافتراضي القاهرة)")
    a.add_argument("--finishes", nargs="?", const="standard", metavar="TIER",
                   choices=["economy", "standard", "premium"],
                   help="د-3 جدول تشطيبات بفئة الميزانية")
    a.add_argument("--furnish", action="store_true",
                   help="د-4 فرش ذكي: الموديل بينوي ومُرصِّف حتمي بيحط")
    a.add_argument("--rationale", action="store_true",
                   help="و-2 اطبع دفتر التصميم: كل قرار ومين اتخذه وليه")

    f = p.add_argument_group("دراسة الجدوى والتقييم / feasibility & evals")
    f.add_argument("--feasibility", action="store_true",
                   help="هـ-1 «الأرض دي أعمل فيها إيه؟» — بحث في السيناريوهات")
    f.add_argument("--max-floors", type=int, default=6,
                   help="أقصى عدد أدوار في دراسة الجدوى")
    f.add_argument("--evals", action="store_true",
                   help="و-1 شغّل مجموعة التقييم واطبع بطاقة الجودة")
    f.add_argument("--judge", action="store_true",
                   help="و-1 ضيف حَكَم LLM لتنفيذ الوصف (ذاتي)")
    f.add_argument("--baseline", metavar="FILE",
                   help="و-1 قارن ببطاقة محفوظة — بيكشف الانحدار")
    f.add_argument("--save-card", metavar="FILE",
                   help="و-1 احفظ بطاقة الجودة JSON")

    b.add_argument("--units", type=int,
                   help="عدد الوحدات الافتراضي لكل دور (مع --building)")
    p.add_argument("--version", "-V", action="version", version=f"CelestAI {__version__}")
    return p


def parse_floor_specs(args) -> list:
    """يحوّل -F 0:retail:4 -F 1-4:apartments:2 لقائمة أدوار صريحة."""
    from .models import FloorSpec, FloorUse

    overrides: dict[int, tuple[str, int | None]] = {}
    for raw in args.floor_plan:
        parts = raw.split(":")
        if len(parts) < 2:
            raise ValueError(f"صيغة غير صحيحة: {raw} (المتوقع LEVELS:USE[:UNITS])")
        levels, use = parts[0], parts[1]
        units = int(parts[2]) if len(parts) > 2 and parts[2] else None
        try:
            FloorUse(use)
        except ValueError as exc:
            valid = ", ".join(u.value for u in FloorUse)
            raise ValueError(f"استخدام غير معروف: {use} (المتاح: {valid})") from exc
        if "-" in levels:
            lo, hi = levels.split("-", 1)
            rng = range(int(lo), int(hi) + 1)
        else:
            rng = [int(levels)]
        for lv in rng:
            overrides[lv] = (use, units)

    top = max([*overrides.keys(), args.floors - 1]) if overrides else args.floors - 1
    bottom = min([*overrides.keys(), 0]) if overrides else 0

    specs = []
    for lv in range(bottom, top + 1):
        use, units = overrides.get(lv, ("apartments", args.units))
        specs.append(FloorSpec(level=lv, use=FloorUse(use),
                               units=units if units else args.units))
    return specs


def serve(host: str, port: int, lang: str = "ar") -> int:
    import uvicorn

    tr = CLI_STRINGS[lang]
    print(f"{BOLD}CelestAI{OFF} — {tr['serveRunning']} "
          f"{CYN}http://{host}:{port}{OFF}")
    print(f"{DIM}{tr['aiOn'] if credentials_available() else tr['aiOff']}{OFF}\n")
    uvicorn.run("celestai.api:app", host=host, port=port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # و-1 · مجموعة التقييم — مش محتاجة مساحة
    if args.evals:
        return _run_evals(args)

    if args.area is None:
        build_parser().print_help()
        return 1
    if str(args.area).lower() == "serve":
        return serve(args.host, args.port, args.lang)

    try:
        area = float(args.area)
    except ValueError:
        print(f"{RED}{CLI_STRINGS[args.lang]['notANumber']}{OFF}", file=sys.stderr)
        return 2

    # هـ-1 · دراسة الجدوى
    if args.feasibility:
        return _run_feasibility(args, area)

    if args.building or args.floor_plan:
        return _run_building(args, area)

    req = DesignRequest(
        building_type=BuildingType(args.type),
        area=area,
        width=args.width,
        depth=args.depth,
        bedrooms=args.bedrooms,
        bathrooms=args.bathrooms,
        receptions=args.receptions,
        entry_side=args.entry,
        brief=args.brief,
        outputs=args.formats,
        language=args.lang,
        use_ai=not args.no_ai,
        model=args.model,
        want_boq=args.boq or bool(args.prices),
    )

    prof = PROFILES[req.building_type]
    tr = CLI_STRINGS[req.lang_key]
    if not args.json:
        label = prof.label_en if req.lang_key == "en" else prof.label_ar
        provider = active_provider_label()
        if req.use_ai and provider == "openai":
            source = tr["srcOpenai"]
        elif req.use_ai and provider == "anthropic":
            source = tr["srcAi"]
        else:
            source = tr["srcRules"]
        print(f"\n{BOLD}CelestAI{OFF} · {label} · {area:.0f} {tr['m2']}")
        print(f"{DIM}{tr['programSource']}: {source} · {tr['generating']}{OFF}\n")

    prices = None
    if args.prices:
        from .analysis.quantities import PriceBook

        try:
            prices = PriceBook.load(args.prices)
        except (OSError, ValueError) as exc:
            print(f"{RED}✗ جدول أسعار غير صالح: {exc}{OFF}", file=sys.stderr)
            return 2

    from .rationale import RationaleLog

    log = RationaleLog()
    try:
        if args.options >= 2:
            result = generate_options(
                req, out_dir=args.out, count=args.options, repair=args.repair
            )
        else:
            result = generate(
                req, out_dir=args.out, alternatives=args.alternatives,
                repair=args.repair,
                explain=args.explain,
                solar_city=args.solar or "",
                prices=prices,
                finishes_tier=args.finishes or "",
                furnish=args.furnish,
                rationale=log,
            )
    except RuntimeError as exc:
        print(f"{RED}✗ {exc}{OFF}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(
            {
                "metrics": result.layout.metrics,
                "files": result.files,
                "issues": [i.model_dump() for i in result.layout.issues],
                "program": result.program.model_dump(mode="json"),
                "boq": result.boq,
                "solar": result.solar,
                "rationale": result.rationale,
                "options": result.options,
            },
            ensure_ascii=False, indent=2,
        ))
        return 0

    _print_summary(result)

    if args.rationale and result.rationale:
        print(f"\n{BOLD}{'دفتر التصميم' if req.lang_key == 'ar' else 'Design log'}{OFF}")
        for d in result.rationale:
            what = d["what_ar"] if req.lang_key == "ar" else (
                d["what_en"] or d["what_ar"]
            )
            print(f"  {DIM}[{d['by']}]{OFF} {what}")
            why = d["why_ar"] if req.lang_key == "ar" else (
                d["why_en"] or d["why_ar"]
            )
            if why:
                print(f"      {DIM}{why}{OFF}")

    if result.boq.get("items"):
        boq = result.boq
        n = len(boq["items"])
        if boq.get("priced"):
            print(f"\n{BOLD}الكميات{OFF} · {n} بند · "
                  f"{boq['low']:,.0f}–{boq['high']:,.0f} {boq['currency']}")
        else:
            print(f"\n{BOLD}الكميات{OFF} · {n} بند · "
                  f"{DIM}بدون أسعار (استخدم --prices){OFF}")

    if result.solar:
        idx = result.solar.get("summer_load_index", 0)
        print(f"\n{BOLD}التوجيه{OFF} · مؤشر الحِمل الصيفي {idx:.2f} "
              f"{DIM}({result.solar.get('city_ar', '')}){OFF}")

    return 0


# ---------------------------------------------------------------------------
# هـ-1 · دراسة الجدوى
# ---------------------------------------------------------------------------


def _run_feasibility(args, area: float) -> int:
    from .analysis.feasibility import feasibility_markdown, study_feasibility

    lang = args.lang
    print(f"\n{BOLD}CelestAI{OFF} · "
          f"{'دراسة جدوى' if lang == 'ar' else 'Feasibility study'} · "
          f"{area:.0f} م²")
    print(f"{DIM}{'بيجرّب السيناريوهات…' if lang == 'ar' else 'Searching scenarios…'}"
          f"{OFF}\n")

    prices = None
    if args.prices:
        from .analysis.quantities import PriceBook

        try:
            prices = PriceBook.load(args.prices)
        except (OSError, ValueError):
            prices = None

    try:
        study = study_feasibility(
            area, max_floors=args.max_floors, prices=prices,
            language=lang, brief=args.brief,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"{RED}✗ {exc}{OFF}", file=sys.stderr)
        return 3

    if not args.no_ai:
        try:
            from .ai.content import feasibility_advice

            study.advice = feasibility_advice(study, lang)
        except Exception:  # noqa: BLE001
            pass

    if args.json:
        print(json.dumps(study.as_dict(), ensure_ascii=False, indent=2))
        return 0

    report = feasibility_markdown(study, lang)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"celestai-feasibility-{area:.0f}m2.md"
    path.write_text(report, encoding="utf-8")

    best = study.best
    if best:
        print(f"{BOLD}{'التوصية' if lang == 'ar' else 'Recommendation'}{OFF}: "
              f"{best.label_ar if lang == 'ar' else best.label_en}")
        print(f"  {best.total_units} {'وحدة' if lang == 'ar' else 'units'} · "
              f"{best.sellable_area:,.0f} م² {'قابلة للبيع' if lang == 'ar' else 'sellable'} · "
              f"{best.errors} {'مخالفة' if lang == 'ar' else 'violations'}")

    print(f"\n{DIM}{'السيناريوهات' if lang == 'ar' else 'Scenarios'}{OFF}")
    for s in study.scenarios[:8]:
        if s.failed:
            continue
        mark = "★" if best and s.scenario_id == best.scenario_id else " "
        print(f" {mark} {s.label_ar if lang == 'ar' else s.label_en:<52} "
              f"{s.total_units:>3} · {s.sellable_area:>8,.0f} م² · "
              f"{s.errors:>3} · {s.score:.3f}")

    print(f"\n{GRN}✓{OFF} {path}")
    return 0


# ---------------------------------------------------------------------------
# و-1 · مجموعة التقييم
# ---------------------------------------------------------------------------


def _run_evals(args) -> int:
    from .evals import run_suite
    from .evals.runner import (
        compare_scorecards,
        load_scorecard,
        save_scorecard,
        scorecard_markdown,
    )

    lang = args.lang
    print(f"\n{BOLD}CelestAI{OFF} · "
          f"{'مجموعة التقييم' if lang == 'ar' else 'Eval suite'}")

    mode = "AI" if not args.no_ai else ("قواعد" if lang == "ar" else "rules")
    if args.repair:
        mode += " + إصلاح ذاتي" if lang == "ar" else " + self-repair"
    if args.judge:
        mode += " + حَكَم" if lang == "ar" else " + judge"
    print(f"{DIM}{mode}{OFF}\n")

    def progress(i, total, case_id):
        print(f"  {DIM}[{i}/{total}]{OFF} {case_id}", flush=True)

    card = run_suite(
        label=mode,
        use_ai=not args.no_ai,
        repair=args.repair,
        judge=args.judge,
        progress=progress,
    )

    print(f"\n{BOLD}{'النتيجة' if lang == 'ar' else 'Result'}{OFF}")
    print(f"  {'الدرجة الموضوعية' if lang == 'ar' else 'Objective score'}: "
          f"{BOLD}{card.mean_objective:.3f}{OFF}")
    print(f"  {'حالات نضيفة' if lang == 'ar' else 'Clean'}: "
          f"{card.clean}/{len(card.results)}")
    print(f"  {'إجمالي المخالفات' if lang == 'ar' else 'Total violations'}: "
          f"{card.total_errors}")
    if card.crashed:
        print(f"  {RED}{'انهيارات' if lang == 'ar' else 'Crashes'}: "
              f"{card.crashed}{OFF}")
    if card.mean_judge is not None:
        print(f"  {'حَكَم الوصف (ذاتي)' if lang == 'ar' else 'Brief judge'}: "
              f"{card.mean_judge:.1f}/10")

    if args.baseline:
        try:
            base = load_scorecard(args.baseline)
        except (OSError, ValueError) as exc:
            print(f"{RED}✗ {'بطاقة المقارنة مش مقروءة' if lang == 'ar' else exc}{OFF}",
                  file=sys.stderr)
        else:
            cmp = compare_scorecards(base, card)
            colour = (RED if cmp["verdict"] == "regression"
                      else GRN if cmp["verdict"] == "improvement" else DIM)
            print(f"\n{BOLD}{'المقارنة' if lang == 'ar' else 'Comparison'}{OFF}")
            print(f"  {cmp['mean_before']:.3f} → {cmp['mean_after']:.3f} "
                  f"({cmp['mean_delta']:+.3f}) {colour}{cmp['verdict']}{OFF}")
            print(f"  {'مخالفات' if lang == 'ar' else 'violations'}: "
                  f"{cmp['errors_before']} → {cmp['errors_after']}")
            if cmp["broke"]:
                print(f"  {RED}{'حالات اتكسرت' if lang == 'ar' else 'broke'}: "
                      f"{', '.join(cmp['broke'])}{OFF}")
            for r in cmp["regressions"][:5]:
                print(f"  {RED}↓{OFF} {r['case_id']}: "
                      f"{r['before']:.3f} → {r['after']:.3f}")
            for r in cmp["improvements"][:5]:
                print(f"  {GRN}↑{OFF} {r['case_id']}: "
                      f"{r['before']:.3f} → {r['after']:.3f}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    md = out / "celestai-scorecard.md"
    md.write_text(scorecard_markdown(card, lang), encoding="utf-8")
    print(f"\n{GRN}✓{OFF} {md}")

    if args.save_card:
        print(f"{GRN}✓{OFF} {save_scorecard(card, args.save_card)}")

    # كود خروج غير صفري لو فيه انهيارات — عشان ينفع في CI
    return 1 if card.crashed else 0


def _print_summary(result) -> None:
    lang = result.request.lang_key
    tr = CLI_STRINGS[lang]
    m = result.layout.metrics
    errs = [i for i in result.layout.issues if i.severity == "error"]
    warns = [i for i in result.layout.issues if i.severity == "warning"]
    msg = (lambda i: i.message_en) if lang == "en" else (lambda i: i.message_ar)
    name = (lambda r: r.name_en) if lang == "en" else (lambda r: r.name_ar)

    print(f"{BOLD}{tr['spaces']}{OFF}")
    for r in sorted(result.layout.rooms, key=lambda r: -r.net_area):
        n = r.net_rect
        print(f"  {name(r):<22} {n.w:5.2f} × {n.h:5.2f} {tr['m']}   "
              f"{DIM}{r.net_area:6.2f} {tr['m2']}{OFF}")

    print(f"\n{BOLD}{tr['figures']}{OFF}")
    print(f"  {tr['plot']:<18} {m['plot_width']} × {m['plot_depth']} {tr['m']}")
    print(f"  {tr['netArea']:<18} {m['net_area']:.2f} {tr['m2']}  "
          f"({m['efficiency'] * 100:.1f}% {tr['efficiency']})")
    print(f"  {tr['circulation']:<18} {m['circulation_share'] * 100:.1f}%")
    print(f"  {tr['glazing']:<18} {m['glazing_area']:.2f} {tr['m2']}")
    print(f"  {tr['solveTime']:<18} {m.get('solve_seconds', 0):.2f} {tr['seconds']}")

    print(f"\n{BOLD}{tr['codeReview']}{OFF}")
    if not errs and not warns:
        print(f"  {GRN}✓ {tr['allGood']}{OFF}")
    for i in errs:
        print(f"  {RED}✗ {msg(i)}{OFF}")
    for i in warns:
        print(f"  {YEL}⚠ {msg(i)}{OFF}")

    print(f"\n{BOLD}{tr['files']}{OFF}")
    for fmt, path in result.files.items():
        print(f"  {CYN}{fmt:<10}{OFF} {path}")
    print()

# ---------------------------------------------------------------------------
# وضع المبنى متعدد الأدوار
# ---------------------------------------------------------------------------


def _run_building(args, area: float) -> int:
    from .knowledge import unit_standard
    from .models import BuildingRequest
    from .service import generate_building

    tr = CLI_STRINGS[args.lang]
    ar = args.lang == "ar"

    try:
        specs = parse_floor_specs(args)
    except ValueError as exc:
        print(f"{RED}✗ {exc}{OFF}", file=sys.stderr)
        return 2

    req = BuildingRequest(
        area=area, width=args.width, depth=args.depth, floors=specs,
        entry_side=args.entry, brief=args.brief, outputs=args.formats,
        language=args.lang, use_ai=not args.no_ai, model=args.model,
    )

    if not args.json:
        head = "مبنى متعدد الأدوار" if ar else "Multi-storey building"
        print(f"\n{BOLD}CelestAI{OFF} · {head} · "
              f"{len(specs)} {'أدوار' if ar else 'floors'} · "
              f"{area:.0f} {tr['m2']}/{'دور' if ar else 'floor'}")
        print(f"{DIM}{tr['generating']}{OFF}\n")

    try:
        result = generate_building(req, out_dir=args.out)
    except RuntimeError as exc:
        print(f"{RED}✗ {exc}{OFF}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps({
            "metrics": result.metrics,
            "files": result.files,
            "floors": [
                {
                    "level": f.level, "use": f.use.value,
                    "label": f.label_ar if ar else f.label_en,
                    "units": [
                        {"id": u.unit_id,
                         "name": u.name_ar if ar else u.name_en,
                         "area": round(u.area, 2),
                         "facades": u.exterior_sides}
                        for u in f.units
                    ],
                    "metrics": f.metrics,
                    "issues": [i.model_dump() for i in f.issues],
                }
                for f in result.floors
            ],
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"{BOLD}{'الأدوار' if ar else 'Floors'}{OFF}")
    for f in result.floors:
        st = unit_standard(f.use.value)
        label = f.label_ar if ar else f.label_en
        use_label = st.label_ar if ar else st.label_en
        errs = int(f.metrics.get("errors", 0))
        mark = f"{GRN}✓{OFF}" if errs == 0 else f"{RED}✗{errs}{OFF}"
        print(f"  {mark} {label:<16} {use_label:<14} "
              f"{len(f.units)} {'وحدة' if ar else 'units'}   "
              f"{DIM}{f.metrics.get('unit_area', 0):.0f} {tr['m2']} · "
              f"{f.metrics.get('efficiency', 0) * 100:.0f}%{OFF}")
        for u in f.units:
            n = u.net_rect
            print(f"      {(u.name_ar if ar else u.name_en):<12} "
                  f"{n.w:5.2f} × {n.h:5.2f} {tr['m']}  "
                  f"{DIM}{u.area:6.1f} {tr['m2']} · "
                  f"{len(u.exterior_sides)} {'واجهة' if ar else 'façades'}{OFF}")

    m = result.metrics
    print(f"\n{BOLD}{tr['figures']}{OFF}")
    print(f"  {'بصمة المبنى' if ar else 'Footprint':<22} "
          f"{m['plot_width']} × {m['plot_depth']} {tr['m']}")
    print(f"  {'إجمالي المسطح' if ar else 'Total built area':<22} "
          f"{m['total_built_area']:.2f} {tr['m2']}")
    print(f"  {'إجمالي الوحدات' if ar else 'Total units':<22} {int(m['units'])}")
    print(f"  {'متوسط الكفاءة' if ar else 'Avg efficiency':<22} "
          f"{m['avg_efficiency'] * 100:.1f}%")
    print(f"  {tr['solveTime']:<22} {m['solve_seconds']:.2f} {tr['seconds']}")

    errs = int(m["errors"])
    print(f"\n{BOLD}{tr['codeReview']}{OFF}")
    if errs == 0 and int(m["warnings"]) == 0:
        print(f"  {GRN}✓ {tr['allGood']}{OFF}")
    else:
        for f in result.floors:
            for i in f.issues:
                label = f.label_ar if ar else f.label_en
                msg = i.message_ar if ar else i.message_en
                colour = RED if i.severity == "error" else YEL
                mark = "✗" if i.severity == "error" else "⚠"
                print(f"  {colour}{mark} [{label}] {msg}{OFF}")

    print(f"\n{BOLD}{tr['files']}{OFF}")
    for fmt, path in result.files.items():
        print(f"  {CYN}{fmt:<12}{OFF} {path}")
    print()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
