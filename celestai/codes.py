"""أكواد البناء متعددة الولايات — ج-1 · Code-as-data with citations.

`knowledge.py` فيه تفسير واحد ثابت للكود المصري: أرقام مكتوبة في الكود، من غير
مصدر، ومن غير طريقة تحديث، ومن غير دعم لولاية تانية.

الملف ده بيحوّل الكود من **ثوابت في الكود المصدري** لـ **بيانات ليها مصدر**:

  • `CodeBook` = مجموعة معايير + استشهاد لكل رقم
  • كل مخالفة تقدر تحمل رقم البند اللي اتبنت عليه
  • تبديل الولاية بيبدّل الجدول

**والحد الفاصل الأهم:** الـ AI بيستخدم **مرة واحدة وقت الاستيعاب** عشان يستخرج
الأرقام من نص الكود لجدول مُهيكل، **مش وقت التشغيل**. التنفيذ بيفضل حتمي، وكل
جدول مستخرج بيتعلّم عليه `reviewed: false` لحد ما بني آدم يراجعه.

مفيش رقم كودي مستخرج بالـ AI بيتعرض كمرجع معتمد من غير مراجعة.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import RoomKind

log = logging.getLogger("celestai.codes")


# ---------------------------------------------------------------------------
# المعيار الواحد + مصدره
# ---------------------------------------------------------------------------


@dataclass
class CodedStandard:
    """معيار فراغ + البند اللي جه منه."""

    min_area: Optional[float] = None
    min_width: Optional[float] = None
    daylight_ratio: Optional[float] = None
    clause: str = ""
    quote: str = ""

    def as_dict(self) -> dict:
        return {
            "min_area": self.min_area,
            "min_width": self.min_width,
            "daylight_ratio": self.daylight_ratio,
            "clause": self.clause,
            "quote": self.quote,
        }


@dataclass
class CodeBook:
    """كود بناء لولاية واحدة."""

    code_id: str
    name_ar: str
    name_en: str
    source_title: str = ""
    reviewed: bool = False           # راجعه متخصص؟
    standards: dict[RoomKind, CodedStandard] = field(default_factory=dict)
    notes_ar: list[str] = field(default_factory=list)
    notes_en: list[str] = field(default_factory=list)

    def citation(self, kind: RoomKind) -> str:
        st = self.standards.get(kind)
        return st.clause if st else ""

    def as_dict(self) -> dict:
        return {
            "code_id": self.code_id,
            "name_ar": self.name_ar, "name_en": self.name_en,
            "source_title": self.source_title,
            "reviewed": self.reviewed,
            "standards": {k.value: v.as_dict() for k, v in self.standards.items()},
            "notes_ar": self.notes_ar, "notes_en": self.notes_en,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CodeBook":
        standards: dict[RoomKind, CodedStandard] = {}
        for key, raw in (data.get("standards") or {}).items():
            try:
                kind = RoomKind(key)
            except ValueError:
                continue
            standards[kind] = CodedStandard(
                min_area=raw.get("min_area"),
                min_width=raw.get("min_width"),
                daylight_ratio=raw.get("daylight_ratio"),
                clause=raw.get("clause", ""),
                quote=raw.get("quote", ""),
            )
        return cls(
            code_id=data.get("code_id", "custom"),
            name_ar=data.get("name_ar", ""),
            name_en=data.get("name_en", ""),
            source_title=data.get("source_title", ""),
            reviewed=bool(data.get("reviewed", False)),
            standards=standards,
            notes_ar=list(data.get("notes_ar") or []),
            notes_en=list(data.get("notes_en") or []),
        )

    @classmethod
    def load(cls, path: str | Path) -> "CodeBook":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return str(p)


# ---------------------------------------------------------------------------
# الأكواد المدمجة
# ---------------------------------------------------------------------------


def _egyptian() -> CodeBook:
    """الكود المصري — الافتراضي، وهو نفس أرقام `knowledge.py`.

    مراجَع لأن الأرقام دي هي اللي المشروع اتبنى واتختبر عليها من الأول، مش
    مستخرجة آليًا.
    """
    from .knowledge import DAYLIGHT_RATIO, STANDARDS

    standards = {}
    for kind, st in STANDARDS.items():
        standards[kind] = CodedStandard(
            min_area=st.min_area,
            min_width=st.min_width,
            daylight_ratio=DAYLIGHT_RATIO.get(kind),
            clause="",
            quote="",
        )
    return CodeBook(
        code_id="eg",
        name_ar="الكود المصري للأعمال المعمارية",
        name_en="Egyptian Code for Architectural Works",
        source_title="الكود المصري + Neufert Architects' Data",
        reviewed=True,
        standards=standards,
        notes_ar=["الأرقام دي هي أساس المحرك، ومتختبرة في 190 اختبار."],
        notes_en=["These figures are the engine's baseline, covered by 190 tests."],
    )


#: أكواد إضافية بفروق معروفة عن المصري. **غير مراجَعة** — للتجربة بس.
_VARIANTS: dict[str, dict] = {
    "gulf": {
        "name_ar": "متغيّر خليجي (غير مراجَع)",
        "name_en": "Gulf variant (unreviewed)",
        "overrides": {
            RoomKind.BEDROOM: {"min_area": 10.0, "min_width": 3.00},
            RoomKind.MASTER_BEDROOM: {"min_area": 14.0, "min_width": 3.30},
            RoomKind.LIVING: {"min_area": 14.0, "min_width": 3.50},
            RoomKind.KITCHEN: {"min_area": 7.0, "min_width": 2.10},
            RoomKind.BATH: {"min_area": 3.5, "min_width": 1.65},
        },
        "notes_ar": [
            "متغيّر تجريبي بحدود دنيا أكبر شوية — **مش مراجَع من متخصص**، "
            "ومينفعش يُعتمد عليه في ترخيص.",
        ],
        "notes_en": [
            "Experimental variant with slightly larger minimums — **not reviewed** "
            "by a specialist and not usable for permitting.",
        ],
    },
}


def _variant(code_id: str) -> CodeBook:
    spec = _VARIANTS[code_id]
    book = _egyptian()
    book.code_id = code_id
    book.name_ar = spec["name_ar"]
    book.name_en = spec["name_en"]
    book.source_title = ""
    book.reviewed = False
    book.notes_ar = spec["notes_ar"]
    book.notes_en = spec["notes_en"]
    for kind, over in spec["overrides"].items():
        st = book.standards.get(kind) or CodedStandard()
        for key, value in over.items():
            setattr(st, key, value)
        book.standards[kind] = st
    return book


_BUILTIN = {"eg": _egyptian, **{k: (lambda k=k: _variant(k)) for k in _VARIANTS}}

_cache: dict[str, CodeBook] = {}


def available_codes() -> list[dict]:
    out = []
    for code_id in _BUILTIN:
        book = get_code(code_id)
        out.append({
            "id": book.code_id,
            "name_ar": book.name_ar,
            "name_en": book.name_en,
            "reviewed": book.reviewed,
        })
    return out


def get_code(code_id: str = "eg") -> CodeBook:
    key = (code_id or "eg").strip().lower()
    if key not in _cache:
        factory = _BUILTIN.get(key, _BUILTIN["eg"])
        _cache[key] = factory()
    return _cache[key]


def register_code(book: CodeBook) -> None:
    """يسجّل كود مستخرج أو محمّل من ملف."""
    _cache[book.code_id] = book


# ---------------------------------------------------------------------------
# ج-2 · مساعد كودي بالمصادر — استرجاع معجمي بدون أي تبعيات
# ---------------------------------------------------------------------------


@dataclass
class Clause:
    """بند واحد من نص الكود."""

    clause_id: str
    text: str
    source: str = ""
    page: Optional[int] = None


_WORD = re.compile(r"[\w؀-ۿ]+")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text) if len(t) > 1]


class CodeCorpus:
    """فهرس بنود بسيط باسترجاع BM25.

    اخترنا استرجاع معجمي مش embeddings عن قصد: مفيش تبعيات جديدة، مفيش خدمة
    خارجية، وبيشتغل أوفلاين — ونصوص الأكواد مصطلحاتها ثابتة فالمعجمي كفاية.
    """

    K1 = 1.5
    B = 0.75

    def __init__(self) -> None:
        self.clauses: list[Clause] = []
        self._docs: list[list[str]] = []
        self._df: dict[str, int] = {}
        self._avg_len = 0.0

    def add(self, clause: Clause) -> None:
        self.clauses.append(clause)
        toks = _tokens(clause.text)
        self._docs.append(toks)
        for t in set(toks):
            self._df[t] = self._df.get(t, 0) + 1
        self._avg_len = sum(len(d) for d in self._docs) / max(len(self._docs), 1)

    def add_text(self, text: str, source: str = "") -> int:
        """يقسّم نص لبنود. البند بيبدأ برقم زي «3-2-1» أو «المادة 5»."""
        # الفاصل بيبقى مسافة أو نقطة أو شرطة. مهم إن رقم البند المركّب («3-1»)
        # يتاخد كامل، مش «3» والباقي يبقى جزء من النص.
        pattern = re.compile(r"(?m)^[ \t]*(?:(?:المادة|البند|Article|Clause)[ \t]*)?"
                             r"(\d+(?:[-.]\d+)*)[\s.:)–-]+")
        parts = pattern.split(text)
        added = 0
        if len(parts) > 1:
            for i in range(1, len(parts) - 1, 2):
                cid, body = parts[i].strip(), parts[i + 1].strip()
                if len(body) > 20:
                    self.add(Clause(clause_id=cid, text=body, source=source))
                    added += 1
        if added == 0:
            for i, para in enumerate(p.strip() for p in text.split("\n\n")):
                if len(para) > 40:
                    self.add(Clause(clause_id=f"§{i + 1}", text=para, source=source))
                    added += 1
        return added

    def load_file(self, path: str | Path) -> int:
        p = Path(path)
        return self.add_text(p.read_text(encoding="utf-8"), source=p.name)

    def search(self, query: str, top_k: int = 5) -> list[tuple[Clause, float]]:
        if not self.clauses:
            return []
        q = _tokens(query)
        n = len(self._docs)
        scored: list[tuple[Clause, float]] = []
        for clause, doc in zip(self.clauses, self._docs):
            if not doc:
                continue
            score = 0.0
            length = len(doc)
            for term in q:
                tf = doc.count(term)
                if tf == 0:
                    continue
                df = self._df.get(term, 0) or 1
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                denom = tf + self.K1 * (
                    1 - self.B + self.B * length / max(self._avg_len, 1e-6)
                )
                score += idf * (tf * (self.K1 + 1)) / denom
            if score > 0:
                scored.append((clause, score))
        scored.sort(key=lambda kv: -kv[1])
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self.clauses)


corpus = CodeCorpus()


# ---------------------------------------------------------------------------
# الاستخراج بالـ AI — مرة واحدة وقت الاستيعاب، مش وقت التشغيل
# ---------------------------------------------------------------------------

EXTRACT_SYSTEM = """You are extracting numeric building-code requirements from the \
text of a building code, into a structured table for CelestAI.

This is regulatory data. The bar is higher than usual.

Rules:
1. **Extract only what the text explicitly states.** Never infer a value from \
convention, from another clause, or from what is "typical". A missing value is fine.
2. Every extracted standard MUST carry the clause number and a verbatim quote of the \
sentence the number came from. No quote = do not extract it.
3. Convert daylight ratios to decimals (1:8 → 0.125).
4. Units: areas in m², widths in m. If the text uses different units, convert and note \
it in `uncertain`.
5. Anything ambiguous — unclear which room type, unclear whether a minimum or a \
recommendation, conflicting clauses — goes in `uncertain`, NOT in `standards`.
6. If the text is not a building code, return zero standards and say so in `uncertain`."""


def extract_code_from_text(
    text: str, code_id: str, source_title: str = ""
) -> CodeBook | None:
    """يستخرج كود من نص. الناتج **غير مراجَع** — لازم متخصص يراجعه.

    بيرجّع None لو الـ AI مش متاح.
    """
    from .ai.client import AIUnavailable, ask
    from .ai.schemas import CodeExtraction

    try:
        result = ask(
            EXTRACT_SYSTEM,
            f"Source: {source_title or code_id}\n\n"
            "Extract the room standards from this code text:\n\n" + text[:120000],
            CodeExtraction, task="code_extract", max_tokens=20000,
        )
    except AIUnavailable as exc:
        log.info("استخراج الكود مش متاح: %s", exc)
        return None

    standards: dict[RoomKind, CodedStandard] = {}
    for s in result.standards:
        if not s.clause or not s.quote:
            continue        # مفيش استشهاد = مفيش اعتماد
        standards[s.kind] = CodedStandard(
            min_area=s.min_area, min_width=s.min_width,
            daylight_ratio=s.daylight_ratio,
            clause=s.clause, quote=s.quote,
        )

    book = CodeBook(
        code_id=code_id,
        name_ar=result.jurisdiction_ar or code_id,
        name_en=result.jurisdiction_en or code_id,
        source_title=result.source_title or source_title,
        reviewed=False,
        standards=standards,
        notes_ar=(
            ["⚠ مستخرج آليًا — محتاج مراجعة متخصص قبل الاعتماد."]
            + [f"غير مؤكد: {u}" for u in result.uncertain]
        ),
        notes_en=(
            ["⚠ Automatically extracted — needs specialist review before use."]
            + [f"Uncertain: {u}" for u in result.uncertain]
        ),
    )
    return book


# ---------------------------------------------------------------------------
# ج-2 · الإجابة على أسئلة الكود
# ---------------------------------------------------------------------------

QA_SYSTEM = """You answer questions about building code requirements inside CelestAI.

You are given retrieved clauses from the code corpus, and the numeric standards the \
engine actually applies.

Rules:
1. Answer ONLY from the retrieved clauses and the given standards. If they do not \
contain the answer, set `confident: false` and say what is missing. Do not fill the \
gap from memory — a plausible-sounding wrong code number is the worst possible output.
2. Cite the clause ids you used in `citations`. An answer with no citation must have \
`confident: false`.
3. If the retrieved clauses conflict, say so and quote both.
4. Distinguish clearly between "the code requires" and "CelestAI's engine applies" — \
they can differ, and the user needs to know which is which.
5. Natural Egyptian Arabic in `answer_ar`."""


def ask_code(question: str, code_id: str = "eg", language: str = "ar"):
    """يجاوب سؤال كودي بالمصادر. None لو الـ AI مش متاح."""
    from .ai.client import AIUnavailable, ask
    from .ai.schemas import CodeAnswer

    book = get_code(code_id)
    hits = corpus.search(question, top_k=6)

    retrieved = "\n\n".join(
        f"[{c.clause_id}] (source: {c.source or '—'}, score {s:.2f})\n{c.text[:1200]}"
        for c, s in hits
    ) or "(no code documents have been indexed)"

    applied = "\n".join(
        f"  - {kind.value}: "
        + ", ".join(
            filter(None, [
                f"min_area {st.min_area} m²" if st.min_area else "",
                f"min_width {st.min_width} m" if st.min_width else "",
                f"daylight {st.daylight_ratio}" if st.daylight_ratio else "",
            ])
        )
        + (f"  [clause {st.clause}]" if st.clause else "")
        for kind, st in sorted(book.standards.items(), key=lambda kv: kv[0].value)
    )

    try:
        return ask(
            QA_SYSTEM,
            f"## Code in use\n{book.name_en} (reviewed={book.reviewed})\n\n"
            f"## Standards the engine applies\n{applied}\n\n"
            f"## Retrieved clauses\n{retrieved}\n\n"
            f"## Question\n{question.strip()}",
            CodeAnswer, task="code_qa", max_tokens=5000,
        )
    except AIUnavailable as exc:
        log.info("مساعد الكود مش متاح: %s", exc)
        return None
