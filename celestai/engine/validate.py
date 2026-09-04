"""مراجعة كودية للمخطط — Building-code compliance checks."""

from __future__ import annotations

from ..knowledge import (
    DOOR_MIN_CLEAR,
    HABITABLE,
    SHAFT_MIN_AREA,
    SHAFT_MIN_WIDTH,
    UNROOFED,
    required_glazing,
    standard,
)
from ..models import Issue, Layout, RoomKind, Zone


def validate(layout: Layout) -> list[Issue]:
    issues: list[Issue] = []

    for room in layout.rooms:
        st = standard(room.kind)
        r = room.net_rect
        short, long = (r.w, r.h) if r.w <= r.h else (r.h, r.w)

        if room.kind == RoomKind.SHAFT:
            # المنور مش فراغ مسقوف، فمعاييره مختلفة: بُعد ومساحة كافيين عشان
            # الهوا والضوء يوصلوا لآخر دور
            if short < SHAFT_MIN_WIDTH - 0.02 or r.area < SHAFT_MIN_AREA - 0.05:
                issues.append(
                    Issue(
                        severity="warning",
                        code="SHAFT_TOO_SMALL",
                        room_id=room.spec_id,
                        message_ar=(
                            f"{room.name_ar}: {short:.2f} م × {long:.2f} م "
                            f"({r.area:.2f} م²) أقل من الحد الأدنى "
                            f"{SHAFT_MIN_WIDTH:.2f} م / {SHAFT_MIN_AREA:.2f} م²."
                        ),
                        message_en=(
                            f"{room.name_en}: {short:.2f} × {long:.2f} m "
                            f"({r.area:.2f} m²) is below the "
                            f"{SHAFT_MIN_WIDTH:.2f} m / {SHAFT_MIN_AREA:.2f} m² minimum."
                        ),
                    )
                )
            continue

        if room.kind in UNROOFED:
            continue

        if short < st.min_width - 0.02:
            issues.append(
                Issue(
                    severity="error",
                    code="MIN_WIDTH",
                    room_id=room.spec_id,
                    message_ar=(
                        f"{room.name_ar}: أقل بُعد {short:.2f} م أقل من الحد الأدنى "
                        f"{st.min_width:.2f} م."
                    ),
                    message_en=(
                        f"{room.name_en}: clear width {short:.2f} m is below the "
                        f"{st.min_width:.2f} m minimum."
                    ),
                )
            )

        if r.area < st.min_area - 0.15:
            issues.append(
                Issue(
                    severity="error",
                    code="MIN_AREA",
                    room_id=room.spec_id,
                    message_ar=(
                        f"{room.name_ar}: المساحة {r.area:.2f} م² أقل من الحد الأدنى "
                        f"{st.min_area:.2f} م²."
                    ),
                    message_en=(
                        f"{room.name_en}: {r.area:.2f} m² is below the "
                        f"{st.min_area:.2f} m² minimum."
                    ),
                )
            )

        aspect = long / max(short, 0.05)
        if aspect > st.max_aspect + 0.25:
            issues.append(
                Issue(
                    severity="warning",
                    code="ASPECT",
                    room_id=room.spec_id,
                    message_ar=(
                        f"{room.name_ar}: الفراغ مستطيل أكتر من اللازم "
                        f"(نسبة {aspect:.1f}:1) وده بيصعّب الفرش."
                    ),
                    message_en=(
                        f"{room.name_en}: proportions are {aspect:.1f}:1, which makes "
                        "furnishing awkward."
                    ),
                )
            )

        need = required_glazing(room.kind, r.area)
        if need > 0:
            if room.daylight_area < need - 0.05:
                sev = "error" if (room.kind in HABITABLE and room.zone != Zone.CIRCULATION) else "warning"
                issues.append(
                    Issue(
                        severity=sev,
                        code="DAYLIGHT",
                        room_id=room.spec_id,
                        message_ar=(
                            f"{room.name_ar}: مساحة الشبابيك {room.daylight_area:.2f} م² "
                            f"أقل من المطلوب {need:.2f} م²."
                        ),
                        message_en=(
                            f"{room.name_en}: glazing {room.daylight_area:.2f} m² is "
                            f"below the required {need:.2f} m²."
                        ),
                    )
                )
            if not room.has_window:
                issues.append(
                    Issue(
                        severity="error",
                        code="NO_WINDOW",
                        room_id=room.spec_id,
                        message_ar=f"{room.name_ar}: فراغ داخلي بدون تهوية طبيعية.",
                        message_en=f"{room.name_en}: internal space with no natural ventilation.",
                    )
                )

    # الأبواب
    doors = [o for o in layout.openings if o.kind in ("door", "entry")]
    served = {o.room_id for o in doors}
    for room in layout.rooms:
        if room.kind == RoomKind.SHAFT:
            continue        # المنور مقفول من كل الجهات وبيتخدم بشباك
        if room.spec_id not in served and room.kind != RoomKind.RECEPTION:
            issues.append(
                Issue(
                    severity="error",
                    code="NO_DOOR",
                    room_id=room.spec_id,
                    message_ar=f"{room.name_ar}: مفيش باب يوصّل للفراغ.",
                    message_en=f"{room.name_en}: no door serves this space.",
                )
            )
    for d in doors:
        if d.width < DOOR_MIN_CLEAR - 0.01:
            issues.append(
                Issue(
                    severity="warning",
                    code="DOOR_WIDTH",
                    room_id=d.room_id,
                    message_ar=f"عرض باب {d.width:.2f} م أقل من {DOOR_MIN_CLEAR:.2f} م.",
                    message_en=f"Door clear width {d.width:.2f} m is below {DOOR_MIN_CLEAR:.2f} m.",
                )
            )

    if not any(o.kind == "entry" for o in layout.openings):
        issues.append(
            Issue(
                severity="error",
                code="NO_ENTRY",
                message_ar="مفيش مدخل رئيسي للوحدة.",
                message_en="The unit has no main entrance.",
            )
        )

    return issues


# مخالفات قاتلة: فراغ من غير مدخل أصلًا مش مخطط، فبنستبعده تمامًا
FATAL_CODES = {"NO_DOOR", "NO_ENTRY"}


def issue_penalty(issues: list[Issue]) -> float:
    total = 0.0
    for i in issues:
        if i.code in FATAL_CODES:
            total += 500.0
        else:
            total += {"error": 10.0, "warning": 1.5, "info": 0.0}[i.severity]
    return total
