"""حالة الجلسة — the state that makes conversation possible.

`POST /api/design` كان بلا ذاكرة: بيولّد ويرجّع ويخلص. فالمستخدم مش قادر يقول
«كبّر الماستر» — لازم يبدأ من الأول ويخسر كل حاجة.

الملف ده بيضيف الحاجة الوحيدة الناقصة: **ذاكرة**. البرنامج الحالي، المخطط
الحالي، وسجل التعديلات — ومعاهم **مكدس تراجع**.

التخزين في الذاكرة عن قصد: الجلسات مؤقتة، ومفيش بيانات مستخدم بتتحفظ على
القرص من غير ما يطلب.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .models import ArchitecturalProgram, DesignRequest, DesignResult, Layout
from .rationale import RationaleLog

SESSION_TTL = 3 * 60 * 60      # 3 ساعات
MAX_SESSIONS = 200
MAX_HISTORY = 40


@dataclass
class Snapshot:
    """لقطة كاملة لحالة التصميم — الوحدة اللي بنتراجع ليها."""

    program: ArchitecturalProgram
    layout: Layout
    label_ar: str = ""
    label_en: str = ""
    applied: list[str] = field(default_factory=list)


@dataclass
class Turn:
    """دورة حوار واحدة."""

    role: str                      # user · assistant
    text: str
    applied: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    metrics_before: dict = field(default_factory=dict)
    metrics_after: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "role": self.role,
            "text": self.text,
            "applied": self.applied,
            "rejected": self.rejected,
            "metrics_before": self.metrics_before,
            "metrics_after": self.metrics_after,
        }


@dataclass
class Session:
    session_id: str
    request: DesignRequest
    result: DesignResult
    rationale: RationaleLog = field(default_factory=RationaleLog)
    history: list[Turn] = field(default_factory=list)
    undo_stack: list[Snapshot] = field(default_factory=list)
    redo_stack: list[Snapshot] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)

    # -- الحالة الحالية -----------------------------------------------------

    @property
    def program(self) -> ArchitecturalProgram:
        return self.result.program

    @property
    def layout(self) -> Layout:
        return self.result.layout

    def snapshot(self, label_ar: str = "", label_en: str = "") -> Snapshot:
        return Snapshot(
            program=self.result.program.model_copy(deep=True),
            layout=self.result.layout.model_copy(deep=True),
            label_ar=label_ar, label_en=label_en,
        )

    def push_undo(self, snap: Snapshot) -> None:
        self.undo_stack.append(snap)
        if len(self.undo_stack) > MAX_HISTORY:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.snapshot())
        snap = self.undo_stack.pop()
        self.result.program = snap.program
        self.result.layout = snap.layout
        self.touched = time.time()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.snapshot())
        snap = self.redo_stack.pop()
        self.result.program = snap.program
        self.result.layout = snap.layout
        self.touched = time.time()
        return True

    def add_turn(self, turn: Turn) -> None:
        self.history.append(turn)
        if len(self.history) > MAX_HISTORY * 2:
            self.history = self.history[-MAX_HISTORY * 2:]
        self.touched = time.time()

    def transcript(self, limit: int = 8) -> str:
        """آخر الحوار كنص، عشان الموديل يفهم السياق."""
        lines = []
        for t in self.history[-limit:]:
            who = "User" if t.role == "user" else "Assistant"
            lines.append(f"{who}: {t.text}")
        return "\n".join(lines)


class SessionStore:
    """مخزن جلسات في الذاكرة مع تنظيف تلقائي."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def create(self, request: DesignRequest, result: DesignResult,
               rationale: RationaleLog | None = None) -> Session:
        sid = uuid.uuid4().hex[:16]
        session = Session(
            session_id=sid, request=request, result=result,
            rationale=rationale or RationaleLog(),
        )
        with self._lock:
            self._sessions[sid] = session
            self._prune_locked()
        return session

    def get(self, session_id: str) -> Optional[Session]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if time.time() - session.touched > SESSION_TTL:
                self._sessions.pop(session_id, None)
                return None
            session.touched = time.time()
            return session

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _prune_locked(self) -> None:
        now = time.time()
        stale = [k for k, s in self._sessions.items() if now - s.touched > SESSION_TTL]
        for k in stale:
            self._sessions.pop(k, None)
        if len(self._sessions) > MAX_SESSIONS:
            oldest = sorted(self._sessions.items(), key=lambda kv: kv[1].touched)
            for k, _ in oldest[: len(self._sessions) - MAX_SESSIONS]:
                self._sessions.pop(k, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)


sessions = SessionStore()
