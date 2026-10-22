"""
Module 2 - Student Database & Data Storage (CSV)
================================================

Files kept in the data folder:

    students.csv        RegNo, Name, DateAdded
    attendance.csv      SessionID, Date, RegNo, Name, Status, MarkedAt
    audit_log.csv       every FSM transition (who, from, event, to, when)
    reject_log.csv      every rejected input (DFA rejects, invalid transitions ...)
    active_session.json snapshot of a running session (crash recovery)
    settings.json       ID patterns and timer settings

Error recovery
--------------
* Missing files are recreated with the right header.
* Malformed rows are moved to a "quarantine" CSV and the good rows are kept,
  so one bad line never stops the app from starting.
* A file with a wrong header or unreadable bytes is backed up and recreated.
* Whole-file rewrites go through a temp file + os.replace (atomic), so a crash
  in the middle of a save cannot leave a half-written CSV behind.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .dfa import DEFAULT_PATTERNS, RegNoDFA, Suggestion, Trace
from .fsm import STATES

STUDENT_FIELDS = ["RegNo", "Name", "DateAdded"]
ATTENDANCE_FIELDS = ["SessionID", "Date", "RegNo", "Name", "Status", "MarkedAt"]
AUDIT_FIELDS = ["Timestamp", "SessionID", "RegNo", "From", "Event", "To"]
REJECT_FIELDS = ["Timestamp", "Source", "Input", "Reason"]

NAME_RE = re.compile(r"[A-Za-z][A-Za-z .']{1,49}")
DEFAULT_SETTINGS = {"patterns": list(DEFAULT_PATTERNS), "duration_min": 3.0, "on_time_min": 1.0}


class StoreError(Exception):
    pass


class InvalidRegNo(StoreError):
    def __init__(self, trace: Trace, suggestion: Suggestion | None):
        self.trace = trace
        self.suggestion = suggestion
        super().__init__(trace.reason)


class InvalidName(StoreError):
    pass


class DuplicateStudent(StoreError):
    def __init__(self, regno: str, name: str, added: str):
        self.regno, self.name, self.added = regno, name, added
        super().__init__(f"{regno} is already registered as {name} (added {added}).")


class StudentNotFound(StoreError):
    pass


@dataclass
class Student:
    regno: str
    name: str
    added: str


@dataclass
class LoadIssue:
    file: str
    good_rows: int
    bad_rows: int
    backup: str
    note: str


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _replace_with_retry(src: str, dst: Path) -> None:
    # OneDrive / antivirus can hold a file for a moment on Windows.
    for attempt in range(5):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1)


def atomic_write_csv(path: Path, header: list[str], rows) -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    _replace_with_retry(tmp, path)


def atomic_write_json(path: Path, data) -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    _replace_with_retry(tmp, path)


class AttendanceStore:
    def __init__(self, data_dir, dfa: RegNoDFA | None = None):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.dfa = dfa or RegNoDFA()
        self.students_csv = self.dir / "students.csv"
        self.attendance_csv = self.dir / "attendance.csv"
        self.audit_csv = self.dir / "audit_log.csv"
        self.reject_csv = self.dir / "reject_log.csv"
        self.snapshot_json = self.dir / "active_session.json"
        self.settings_json = self.dir / "settings.json"
        self.issues: list[LoadIssue] = []
        self.students: dict[str, Student] = {}

        seen: set[str] = set()

        def student_ok(row):
            regno, name = row[0].strip(), row[1].strip()
            if not re.fullmatch(r"[A-Z0-9]{4,20}", regno) or not name or regno in seen:
                return False
            seen.add(regno)
            return True

        for row in self._load(self.students_csv, STUDENT_FIELDS, student_ok):
            self.students[row[0].strip()] = Student(row[0].strip(), row[1].strip(), row[2].strip())
        self._load(self.attendance_csv, ATTENDANCE_FIELDS,
                   lambda r: bool(r[0].strip()) and bool(r[2].strip()) and r[4] in STATES)
        self._load(self.audit_csv, AUDIT_FIELDS, lambda r: True)
        self._load(self.reject_csv, REJECT_FIELDS, lambda r: True)

    # --- robust loading -------------------------------------------------
    def _backup_name(self, path: Path, tag: str) -> Path:
        return self.dir / f"{path.stem}.{tag}-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}"

    def _load(self, path: Path, fields: list[str], row_ok) -> list[list[str]]:
        if not path.exists():
            atomic_write_csv(path, fields, [])
            return []
        try:
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
        except (UnicodeDecodeError, csv.Error):
            rows = None
        if rows is not None and not rows:  # empty file: just add the header
            atomic_write_csv(path, fields, [])
            return []
        if rows is None or [c.strip() for c in rows[0]] != fields:
            backup = self._backup_name(path, "corrupt")
            shutil.copyfile(path, backup)
            atomic_write_csv(path, fields, [])
            self.issues.append(LoadIssue(path.name, 0, 0, backup.name,
                                         "header missing or file unreadable; the file was backed "
                                         "up and recreated"))
            return []
        good, bad = [], []
        for row in rows[1:]:
            if not row or all(not c.strip() for c in row):
                continue  # ignore blank lines
            if len(row) == len(fields) and row_ok(row):
                good.append(row)
            else:
                bad.append(row)
        if bad:
            backup = self._backup_name(path, "quarantine")
            with open(backup, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([f"# rows removed from {path.name} on {now_stamp()}"])
                writer.writerows(bad)
            atomic_write_csv(path, fields, good)
            self.issues.append(LoadIssue(path.name, len(good), len(bad), backup.name,
                                         "malformed rows were moved to quarantine"))
        return good

    @staticmethod
    def _append(path: Path, row: list) -> None:
        with open(path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)

    @staticmethod
    def _dict_rows(path: Path) -> list[dict]:
        try:
            with open(path, newline="", encoding="utf-8") as f:
                return list(csv.DictReader(f))
        except FileNotFoundError:
            return []

    # --- students ---------------------------------------------------------
    def add_student(self, regno_raw: str, name_raw: str) -> Student:
        regno = regno_raw.strip()
        trace = self.dfa.trace(regno)
        if not trace.accepted:
            self.log_reject("REGISTER", regno, trace.reason)
            raise InvalidRegNo(trace, self.dfa.suggest(regno))
        if regno in self.students:
            s = self.students[regno]
            self.log_reject("REGISTER", regno, "duplicate registration blocked")
            raise DuplicateStudent(s.regno, s.name, s.added)
        name = " ".join(name_raw.split())
        if not name:
            raise InvalidName("Student name is required.")
        if not NAME_RE.fullmatch(name):
            bad = next((c for c in name if not (c.isalpha() or c in " .'")), None)
            detail = f" (found '{bad}')" if bad else ""
            raise InvalidName("Name must be 2-50 characters and may contain only letters, "
                              f"spaces, dots and apostrophes{detail}.")
        student = Student(regno, name, datetime.now().strftime("%Y-%m-%d %H:%M"))
        self.students[regno] = student
        self._append(self.students_csv, [student.regno, student.name, student.added])
        return student

    def delete_student(self, regno: str) -> Student:
        if regno not in self.students:
            raise StudentNotFound(f"{regno} is not registered.")
        student = self.students.pop(regno)
        atomic_write_csv(self.students_csv, STUDENT_FIELDS,
                         [[s.regno, s.name, s.added] for s in self.students.values()])
        return student

    # --- attendance -------------------------------------------------------
    def save_session(self, session) -> None:
        """Write the final state of every student (replaces earlier rows of the session)."""
        rows = [[r[f] for f in ATTENDANCE_FIELDS] for r in self.attendance_rows()
                if r["SessionID"] != session.session_id]
        date = datetime.fromtimestamp(session.started_at).strftime("%Y-%m-%d")
        for regno, fsm in session.machines.items():
            rows.append([session.session_id, date, regno, session.roster.get(regno, ""),
                         fsm.state, session.marked_at.get(regno, "")])
        atomic_write_csv(self.attendance_csv, ATTENDANCE_FIELDS, rows)

    def attendance_rows(self) -> list[dict]:
        return self._dict_rows(self.attendance_csv)

    def session_ids(self) -> list[str]:
        return sorted({r["SessionID"] for r in self.attendance_rows()})

    # --- logs ---------------------------------------------------------------
    def log_transition(self, session_id: str, regno: str, record) -> None:
        self._append(self.audit_csv, [now_stamp(), session_id, regno,
                                      record.source, record.event, record.target])

    def log_reject(self, source: str, text: str, reason: str) -> None:
        self._append(self.reject_csv, [now_stamp(), source, text, reason])

    def reject_rows(self) -> list[dict]:
        return list(reversed(self._dict_rows(self.reject_csv)))

    def audit_rows(self) -> list[dict]:
        return list(reversed(self._dict_rows(self.audit_csv)))

    # --- crash-recovery snapshot ------------------------------------------------
    def write_snapshot(self, session) -> None:
        atomic_write_json(self.snapshot_json, session.to_dict())

    def read_snapshot(self) -> dict | None:
        if not self.snapshot_json.exists():
            return None
        try:
            data = json.loads(self.snapshot_json.read_text(encoding="utf-8"))
            for key in ("session_id", "started_at", "duration", "on_time", "roster", "states"):
                data[key]
            return data
        except (ValueError, KeyError, TypeError):
            backup = self._backup_name(self.snapshot_json, "corrupt")
            shutil.move(self.snapshot_json, backup)
            self.issues.append(LoadIssue(self.snapshot_json.name, 0, 1, backup.name,
                                         "unreadable session snapshot was set aside"))
            return None

    def clear_snapshot(self) -> None:
        try:
            self.snapshot_json.unlink()
        except FileNotFoundError:
            pass

    # --- settings -----------------------------------------------------------------
    def load_settings(self) -> dict:
        settings = dict(DEFAULT_SETTINGS)
        try:
            data = json.loads(self.settings_json.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                settings.update({k: data[k] for k in DEFAULT_SETTINGS if k in data})
        except (FileNotFoundError, ValueError):
            pass
        return settings

    def save_settings(self, settings: dict) -> None:
        atomic_write_json(self.settings_json, settings)
