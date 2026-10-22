import json

import pytest

from attendance.analytics import summarize
from attendance.exporter import export_report
from attendance.fsm import ABSENT, EXCUSED, LATE, ON_DUTY, PRESENT
from attendance.session import AttendanceSession
from attendance.storage import (AttendanceStore, DuplicateStudent, InvalidName, InvalidRegNo,
                                STUDENT_FIELDS)


@pytest.fixture
def store(tmp_path):
    return AttendanceStore(tmp_path)


def test_files_are_created_with_headers(store):
    for name in ("students.csv", "attendance.csv", "audit_log.csv", "reject_log.csv"):
        assert (store.dir / name).exists()
    assert store.students_csv.read_text().startswith(",".join(STUDENT_FIELDS))
    assert store.issues == []


def test_add_student_and_reload(store, tmp_path):
    store.add_student("24BIT0154", "B. Harish")
    again = AttendanceStore(tmp_path)
    assert again.students["24BIT0154"].name == "B. Harish"


def test_invalid_regno_is_rejected_with_suggestion_and_logged(store):
    with pytest.raises(InvalidRegNo) as err:
        store.add_student("24bit 03S7", "R. Priya")
    assert err.value.suggestion.corrected == "24BIT0357"
    assert store.reject_rows()[0]["Input"] == "24bit 03S7"
    assert store.students == {}


def test_duplicate_is_blocked(store):
    store.add_student("24BIT0154", "B. Harish")
    with pytest.raises(DuplicateStudent):
        store.add_student("24BIT0154", "Someone Else")
    assert len(store.students) == 1


@pytest.mark.parametrize("name", ["", "   ", "Harish123", "A", "x" * 60])
def test_invalid_names(store, name):
    with pytest.raises(InvalidName):
        store.add_student("24BIT0154", name)


def test_corrupted_rows_are_quarantined(tmp_path):
    (tmp_path / "students.csv").write_text(
        "RegNo,Name,DateAdded\n"
        "24BIT0154,B. Harish,2026-10-22 10:00\n"
        "this line is broken\n"
        "24BIT0323,B. Abhishek,2026-10-22 10:01,EXTRA\n"
        "24BIT0154,Duplicate Harish,2026-10-22 10:02\n"
        "24BIT0101,R. Priya,2026-10-22 10:03\n", encoding="utf-8")
    store = AttendanceStore(tmp_path)
    assert list(store.students) == ["24BIT0154", "24BIT0101"]
    issue = store.issues[0]
    assert (issue.good_rows, issue.bad_rows) == (2, 3)
    assert (tmp_path / issue.backup).exists()
    # the repaired file loads cleanly the next time
    assert AttendanceStore(tmp_path).issues == []


def test_wrong_header_is_backed_up(tmp_path):
    (tmp_path / "attendance.csv").write_text("garbage,header\n1,2\n", encoding="utf-8")
    store = AttendanceStore(tmp_path)
    assert store.issues and "header" in store.issues[0].note
    assert store.attendance_rows() == []


def test_snapshot_and_corrupt_snapshot(store, tmp_path):
    s = AttendanceSession({"24BIT0154": "B. Harish"})
    s.mark("24BIT0154")
    store.write_snapshot(s)
    assert store.read_snapshot()["states"]["24BIT0154"] == PRESENT
    store.snapshot_json.write_text("{ not json", encoding="utf-8")
    assert store.read_snapshot() is None
    assert not store.snapshot_json.exists()
    assert any("snapshot" in i.note for i in store.issues)


def _session_with(store, states, session_id="S1"):
    """Save one closed session where each student ends in the given state."""
    roster = {r: store.students[r].name for r in states}
    s = AttendanceSession(roster, session_id=session_id)
    for r, st in states.items():
        if st == PRESENT:
            s.mark(r)
        elif st == LATE:
            s.machines[r].fire("MARK_LATE")
        elif st == EXCUSED:
            s.excuse(r)
        elif st == ON_DUTY:
            s.grant_od(r)
    s.close()
    store.save_session(s)
    return s


def test_save_session_and_75_percent_rule(store):
    store.add_student("24BIT0154", "B. Harish")
    store.add_student("24BIT0323", "B. Abhishek")
    plan = [(PRESENT, ABSENT), (LATE, ABSENT), (PRESENT, PRESENT), (ON_DUTY, EXCUSED)]
    for i, (a, b) in enumerate(plan):
        _session_with(store, {"24BIT0154": a, "24BIT0323": b}, session_id=f"S{i}")
    assert len(store.session_ids()) == 4
    summary = {x.regno: x for x in summarize(store.students, store.attendance_rows())}
    h, a = summary["24BIT0154"], summary["24BIT0323"]
    assert (h.held, h.attended, h.percentage) == (4, 4, 100.0)
    assert (a.held, a.excused, a.attended) == (4, 1, 1)
    assert round(a.percentage, 1) == 33.3 and a.status == "Below 75%"
    assert a.classes_needed == 5  # (1+5)/(3+5) = 75 %


def test_export_excel_and_csv_fallback(store, tmp_path):
    store.add_student("24BIT0154", "B. Harish")
    _session_with(store, {"24BIT0154": PRESENT})
    summary = summarize(store.students, store.attendance_rows())
    pytest.importorskip("openpyxl")
    res = export_report(tmp_path / "report.xlsx", store.students, store.attendance_rows(), summary)
    assert res.used_excel and (tmp_path / "report.xlsx").exists()
    res = export_report(tmp_path / "report.xlsx", store.students, store.attendance_rows(), summary,
                        prefer_excel=False)
    assert not res.used_excel and len(res.files) == 3


def test_settings_round_trip(store):
    s = store.load_settings()
    s["patterns"] = ["24BIT####"]
    store.save_settings(s)
    assert store.load_settings()["patterns"] == ["24BIT####"]
    store.settings_json.write_text("broken", encoding="utf-8")
    assert store.load_settings()["duration_min"] == 3.0
    json.dumps(store.load_settings())
