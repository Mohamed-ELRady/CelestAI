"""تطبيق تعديلات البرنامج — the one place a ProgramEdit becomes geometry.

الموديل بيرجّع **تعديلات** مش برنامج جديد. كده:
  • باقي التصميم بيفضل ثابت — تعديل غرفة مبيعملش مخطط مختلف تمامًا
  • المستخدم يقدر يشوف اتغيّر إيه بالظبط
  • التراجع ممكن

وكل تعديل بيتحقق هنا قبل ما يتنفّذ. لو الموديل طلب حاجة مستحيلة هندسيًا،
بترجع كسبب مرفوض مش كمخطط مكسور.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..knowledge import standard
from ..models import ArchitecturalProgram, RoomKind, RoomSpec
from .schemas import ProgramEdit

#: أنواع تنفع تبقى ملحق بغرفة نوم
ATTACHABLE = {RoomKind.BATH, RoomKind.WC, RoomKind.STORAGE}


@dataclass
class EditOutcome:
    applied: list[str]
    rejected: list[str]
    program: ArchitecturalProgram

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def _find(program: ArchitecturalProgram, room_id: str) -> RoomSpec | None:
    return next((r for r in program.rooms if r.id == room_id), None)


def _unique_id(program: ArchitecturalProgram, base: str) -> str:
    rid = base
    existing = {r.id for r in program.rooms}
    n = 1
    while rid in existing:
        n += 1
        rid = f"{base}_{n}"
    return rid


def apply_edits(
    program: ArchitecturalProgram,
    edits: list[ProgramEdit],
    *,
    language: str = "ar",
) -> EditOutcome:
    """يطبّق التعديلات على نسخة من البرنامج ويرجّع اللي نجح واللي اترفض.

    المساحة الكلية بتفضل ثابتة: أي زيادة في فراغ بتتخصم بالتناسب من الباقي،
    عشان المحرك بيملأ القطعة بالكامل ومفيش مكان لمساحة زايدة.
    """
    ar = language != "en"
    out = program.model_copy(deep=True)
    applied: list[str] = []
    rejected: list[str] = []
    hub_id = out.rooms[0].id if out.rooms else ""

    for e in edits:
        room = _find(out, e.room_id) if e.room_id else None

        if e.op == "resize":
            if room is None:
                rejected.append(f"«{e.room_id}» مش موجود" if ar
                                else f"'{e.room_id}' not found")
                continue
            if e.value is None or e.value <= 0:
                rejected.append("مساحة غير صالحة" if ar else "invalid area")
                continue
            st = standard(room.kind)
            if e.value < st.min_area:
                rejected.append(
                    f"{room.name_ar}: {e.value:.1f} م² أقل من الحد الكودي "
                    f"{st.min_area:.1f} م²" if ar else
                    f"{room.name_en}: {e.value:.1f} m² is below the "
                    f"{st.min_area:.1f} m² code minimum"
                )
                continue
            old = room.target_area
            room.target_area = round(e.value, 2)
            applied.append(
                f"{room.name_ar}: {old:.1f} → {room.target_area:.1f} م²" if ar
                else f"{room.name_en}: {old:.1f} → {room.target_area:.1f} m²"
            )

        elif e.op == "min_width":
            if room is None or e.value is None:
                rejected.append("طلب غير مكتمل" if ar else "incomplete request")
                continue
            room.min_width = round(max(0.9, min(e.value, room.target_area ** 0.5)), 2)
            applied.append(
                f"{room.name_ar}: أقل بُعد {room.min_width:.2f} م" if ar
                else f"{room.name_en}: min width {room.min_width:.2f} m"
            )

        elif e.op == "remove":
            if room is None:
                rejected.append(f"«{e.room_id}» مش موجود" if ar
                                else f"'{e.room_id}' not found")
                continue
            if room.id == hub_id:
                rejected.append(
                    "مينفعش نشيل فراغ التوزيع المركزي" if ar
                    else "the circulation hub cannot be removed"
                )
                continue
            if len(out.rooms) <= 3:
                rejected.append(
                    "البرنامج بقى صغير أوي" if ar else "programme is already minimal"
                )
                continue
            freed = room.target_area
            out.rooms = [r for r in out.rooms if r.id != room.id]
            for r in out.rooms:
                if r.attach_to == room.id:
                    r.attach_to = None
            out.adjacency = [(a, b) for a, b in out.adjacency if room.id not in (a, b)]
            total = sum(r.target_area for r in out.rooms) or 1.0
            for r in out.rooms:
                r.target_area = round(r.target_area * (1 + freed / total), 2)
            applied.append(
                f"اتشال {room.name_ar} ({freed:.1f} م²)" if ar
                else f"removed {room.name_en} ({freed:.1f} m²)"
            )

        elif e.op == "add":
            kind = e.kind or RoomKind.STORAGE
            st = standard(kind)
            area = round(e.value or st.ideal_area, 2)
            if area < st.min_area:
                area = st.min_area
            pool = sum(r.target_area for r in out.rooms[1:]) or 1.0
            if area > pool * 0.5:
                rejected.append(
                    f"{st.name_ar}: {area:.1f} م² أكبر من اللي المساحة تستحمله" if ar
                    else f"{st.name_en}: {area:.1f} m² is more than the plot can give"
                )
                continue
            rid = _unique_id(out, (e.room_id or kind.value).lower().replace(" ", "_"))
            new = RoomSpec(
                id=rid,
                name_ar=e.name_ar or st.name_ar,
                name_en=e.name_en or st.name_en,
                kind=kind,
                target_area=area,
                min_width=st.min_width,
                zone=st.zone,
                priority=3,
            )
            for r in out.rooms:
                r.target_area = round(r.target_area * (1 - area / pool), 2)
            out.rooms.append(new)
            applied.append(
                f"اتضاف {new.name_ar} ({area:.1f} م²)" if ar
                else f"added {new.name_en} ({area:.1f} m²)"
            )

        elif e.op == "rename":
            if room is None:
                rejected.append(f"«{e.room_id}» مش موجود" if ar
                                else f"'{e.room_id}' not found")
                continue
            if e.name_ar:
                room.name_ar = e.name_ar
            if e.name_en:
                room.name_en = e.name_en
            applied.append(
                f"الاسم بقى {room.name_ar}" if ar else f"renamed to {room.name_en}"
            )

        elif e.op == "retype":
            if room is None or e.kind is None:
                rejected.append("طلب غير مكتمل" if ar else "incomplete request")
                continue
            st = standard(e.kind)
            room.kind = e.kind
            room.zone = st.zone
            room.min_width = st.min_width
            room.target_area = max(room.target_area, st.min_area)
            if not e.name_ar:
                room.name_ar = st.name_ar
                room.name_en = st.name_en
            applied.append(
                f"{room.name_ar} بقى {st.name_ar}" if ar
                else f"{room.name_en} is now a {st.name_en}"
            )

        elif e.op == "attach":
            parent = _find(out, e.target_id)
            if room is None or parent is None:
                rejected.append("الغرفة أو الأم مش موجودة" if ar
                                else "room or parent not found")
                continue
            if room.kind not in ATTACHABLE:
                rejected.append(
                    f"{room.name_ar} مينفعش يبقى ملحق — الملحقات حمّامات وتخزين بس"
                    if ar else
                    f"{room.name_en} cannot be en-suite — only baths and storage can"
                )
                continue
            if parent.id == hub_id or parent.attach_to:
                rejected.append(
                    "الأم لازم تكون غرفة عادية مش ملحق ولا فراغ التوزيع" if ar
                    else "the parent must be a normal room, not the hub or an en-suite"
                )
                continue
            room.attach_to = parent.id
            applied.append(
                f"{room.name_ar} بقى داخل {parent.name_ar}" if ar
                else f"{room.name_en} now opens off {parent.name_en}"
            )

        elif e.op == "detach":
            if room is None:
                rejected.append(f"«{e.room_id}» مش موجود" if ar
                                else f"'{e.room_id}' not found")
                continue
            room.attach_to = None
            applied.append(
                f"{room.name_ar} بقى بابه من الصالة" if ar
                else f"{room.name_en} now opens off the hub"
            )

        else:
            rejected.append(f"عملية غير معروفة: {e.op}")

    return EditOutcome(applied=applied, rejected=rejected, program=out)
