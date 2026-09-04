"""اختبارات الثنائية اللغوية — every user-facing surface must follow `language`."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from celestai.drafting import compose, render_svg
from celestai.engine import solve
from celestai.models import BuildingType, DesignRequest
from celestai.planner.rules import build_program, normalise_program
from celestai.service import generate, sheet_titles

ARABIC = re.compile(r"[؀-ۿ]")


def _result(lang: str, **kw):
    req = DesignRequest(area=120, use_ai=False, language=lang, outputs=["svg"], **kw)
    return req, generate(req)


# ---------------------------------------------------------------------------
# التقرير
# ---------------------------------------------------------------------------


def test_report_language_follows_the_request():
    _, ar = _result("ar")
    _, en = _result("en")

    assert ARABIC.search(ar.report_md), "التقرير العربي لازم يكون عربي"
    assert not ARABIC.search(en.report_md), (
        "التقرير الإنجليزي فيه حروف عربية:\n"
        + "\n".join(l for l in en.report_md.splitlines() if ARABIC.search(l))[:400]
    )


def test_report_headings_are_translated():
    _, en = _result("en")
    for heading in ("Key figures", "Planning concept", "Area schedule", "Code review"):
        assert heading in en.report_md, heading


# ---------------------------------------------------------------------------
# المخطط نفسه
# ---------------------------------------------------------------------------


def _svg_texts(svg: str) -> list[str]:
    return re.findall(r">([^<>]+)</text>", svg)


def test_plan_labels_follow_the_request_language():
    req_ar, ar = _result("ar")
    req_en, en = _result("en")

    ar_svg = render_svg(compose(ar.layout, *sheet_titles(req_ar), language="ar"))
    en_svg = render_svg(compose(en.layout, *sheet_titles(req_en), language="en"))

    assert any(ARABIC.search(t) for t in _svg_texts(ar_svg))
    leftovers = [t for t in _svg_texts(en_svg) if ARABIC.search(t)]
    assert not leftovers, f"نصوص عربية في المخطط الإنجليزي: {leftovers}"


def test_scale_bar_and_entrance_label_are_translated():
    req, res = _result("en")
    svg = render_svg(compose(res.layout, *sheet_titles(req), language="en"))
    texts = _svg_texts(svg)
    assert "metres" in texts
    assert "Entrance" in texts


def test_title_block_keys_are_translated():
    req, res = _result("en")
    dw = compose(res.layout, *sheet_titles(req), language="en")
    for key in dw.meta:
        assert not ARABIC.search(key), key
    for value in dw.meta.values():
        assert not ARABIC.search(value), value


def test_sheet_titles_switch_language():
    ar_title, ar_sub = sheet_titles(DesignRequest(area=120, language="ar"))
    en_title, en_sub = sheet_titles(DesignRequest(area=120, language="en"))
    assert ARABIC.search(ar_title) and ARABIC.search(ar_sub)
    assert not ARABIC.search(en_title) and not ARABIC.search(en_sub)
    assert "Apartment" in en_title


# ---------------------------------------------------------------------------
# المخالفات الكودية
# ---------------------------------------------------------------------------


def test_every_issue_carries_both_languages():
    """أي مخالفة لازم يكون ليها نص بالعربي والإنجليزي — مفيش نص ناقص."""
    for area, bt in [(55, BuildingType.APARTMENT), (200, BuildingType.VILLA_FLOOR),
                     (160, BuildingType.OFFICE)]:
        req = DesignRequest(area=area, building_type=bt, use_ai=False)
        layout = solve(normalise_program(build_program(req), area), req)[0]
        for issue in layout.issues:
            assert issue.message_ar.strip(), f"{issue.code}: ناقص نص عربي"
            assert issue.message_en.strip(), f"{issue.code}: ناقص نص إنجليزي"
            assert ARABIC.search(issue.message_ar)
            assert not ARABIC.search(issue.message_en), issue.message_en


# ---------------------------------------------------------------------------
# نصوص الواجهة
# ---------------------------------------------------------------------------


def test_web_ui_dictionaries_have_identical_keys():
    """أي مفتاح موجود في لغة لازم يكون موجود في التانية — مفيش نص مترجم ناقص."""
    src = (Path(__file__).resolve().parents[1] / "celestai/web/i18n.js").read_text()

    blocks = re.findall(r"\n  (ar|en): \{(.*?)\n  \},", src, re.S)
    assert len(blocks) == 2, "لازم يكون فيه قاموسين بالظبط"

    keys = {}
    for lang, body in blocks:
        keys[lang] = set(re.findall(r"^\s{4}(\w+):", body, re.M))

    assert keys["ar"] == keys["en"], (
        f"مفاتيح ناقصة — بس في العربي: {keys['ar'] - keys['en']} · "
        f"بس في الإنجليزي: {keys['en'] - keys['ar']}"
    )
    assert len(keys["ar"]) > 30, "القاموس صغير أوي، يبدو إن الاستخراج فشل"


def test_html_i18n_keys_all_exist_in_the_dictionaries():
    """كل data-i18n في الـ HTML لازم يلاقي نص في القاموسين."""
    root = Path(__file__).resolve().parents[1] / "celestai/web"
    html = (root / "index.html").read_text()
    src = (root / "i18n.js").read_text()

    used = set(re.findall(r'data-i18n(?:-ph|-title)?="([\w]+)"', html))
    defined = set(re.findall(r"^\s{4}(\w+):", src, re.M))

    missing = used - defined
    assert not missing, f"مفاتيح مستخدمة في الـ HTML ومش معرّفة: {missing}"


def test_removed_tagline_is_gone_everywhere():
    """الجملة اللي المستخدم طلب حذفها ما تكونش رجعت في أي ملف."""
    root = Path(__file__).resolve().parents[1]
    # مبنية بالتقطيع عشان الاختبار ما يلاقيش نفسه
    tagline = "تديها" + " مساحة"
    hits = []
    for path in root.rglob("*"):
        if path.is_dir() or ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        if path.suffix not in {".py", ".js", ".html", ".css", ".md", ".json"}:
            continue
        if path.name == Path(__file__).name:
            continue
        try:
            if tagline in path.read_text(encoding="utf-8"):
                hits.append(str(path.relative_to(root)))
        except (UnicodeDecodeError, OSError):
            continue
    assert not hits, f"الجملة المحذوفة لسه موجودة في: {hits}"


def test_signature_is_present_in_the_page():
    html = (Path(__file__).resolve().parents[1] / "celestai/web/index.html").read_text()
    assert "Mohamed ELRady" in html
    assert "Made with" in html
