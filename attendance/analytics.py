"""
Module 6 - Attendance Analytics (75 % rule)
===========================================

For every student, over all saved sessions:

    attended = PRESENT + LATE + ON_DUTY
    counted  = sessions held - EXCUSED          (an excused class is not held against you)
    percent  = 100 * attended / counted

VIT requires 75 %. If a student is below it, the number of classes they must
attend in a row to get back to 75 % is the smallest x with

    (attended + x) / (counted + x) >= 0.75   =>   x = 3*counted - 4*attended
"""

from __future__ import annotations

from dataclasses import dataclass

from .fsm import ABSENT, EXCUSED, LATE, ON_DUTY, PRESENT

THRESHOLD = 75.0


@dataclass
class StudentSummary:
    regno: str
    name: str
    held: int = 0
    present: int = 0
    late: int = 0
    absent: int = 0
    excused: int = 0
    on_duty: int = 0

    @property
    def attended(self) -> int:
        return self.present + self.late + self.on_duty

    @property
    def counted(self) -> int:
        return self.held - self.excused

    @property
    def percentage(self) -> float | None:
        return None if self.counted <= 0 else 100.0 * self.attended / self.counted

    @property
    def classes_needed(self) -> int:
        return max(0, 3 * self.counted - 4 * self.attended)

    @property
    def status(self) -> str:
        pct = self.percentage
        if pct is None:
            return "No classes yet"
        return "OK" if pct >= THRESHOLD else "Below 75%"


def summarize(students: dict, attendance_rows: list[dict]) -> list[StudentSummary]:
    """students: {regno: Student}; attendance_rows: dicts from attendance.csv."""
    summary = {regno: StudentSummary(regno, s.name) for regno, s in students.items()}
    field = {PRESENT: "present", LATE: "late", ABSENT: "absent",
             EXCUSED: "excused", ON_DUTY: "on_duty"}
    for row in attendance_rows:
        item = summary.get(row.get("RegNo", ""))
        status = row.get("Status", "")
        if item is None or status not in field:
            continue
        item.held += 1
        setattr(item, field[status], getattr(item, field[status]) + 1)
    return list(summary.values())
