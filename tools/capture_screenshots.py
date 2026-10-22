"""
Drive the real GUI through the demo scenarios and save screenshots to
docs/screenshots. Used to produce the report figures (Windows only).

    python tools/capture_screenshots.py

The app runs on a throw-away data folder, and a shifted clock is used so the
on-time window and the time-out can be shown without waiting 3 minutes.
"""

import shutil
import sys
import tempfile
import time
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from attendance.fsm import EXCUSE, GRANT_OD, MARK_LATE, MARK_ON_TIME  # noqa: E402
from attendance.gui.app import App, enable_dpi_awareness  # noqa: E402
from attendance.session import AttendanceSession  # noqa: E402
from attendance.storage import AttendanceStore  # noqa: E402
from shot import capture  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
STUDENTS = [("24BIT0154", "B. Harish"), ("24BIT0323", "B. Abhishek"),
            ("24BIT0101", "R. Priya"), ("24BIT0219", "S. Karthik"), ("24BDE0123", "V. Rahul")]
# P = present, L = late, A = absent, E = excused, O = on duty (4 earlier classes)
HISTORY = {"24BIT0154": "PPLP", "24BIT0323": "PLPO", "24BIT0101": "PAPP",
           "24BIT0219": "AAPE", "24BDE0123": "LPAA"}


class Clock:
    def __init__(self):
        self.offset = 0.0

    def __call__(self):
        return time.time() + self.offset


def seed(data_dir: Path):
    store = AttendanceStore(data_dir)
    for regno, name in STUDENTS:
        store.add_student(regno, name)
    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    for i, days_back in enumerate((7, 6, 3, 2)):
        start = (today - timedelta(days=days_back)).timestamp()
        t = {"now": start + 20}
        s = AttendanceSession({r: n for r, n in STUDENTS}, 180, 60, clock=lambda: t["now"],
                              session_id=datetime.fromtimestamp(start).strftime("S%Y%m%d-%H%M%S"),
                              started_at=start)
        for regno, plan in HISTORY.items():
            code = plan[i]
            if code == "P":
                s.machines[regno].fire(MARK_ON_TIME)
                s.marked_at[regno] = "09:00:20"
            elif code == "L":
                s.machines[regno].fire(MARK_LATE)
                s.marked_at[regno] = "09:01:40"
            elif code == "O":
                s.machines[regno].fire(GRANT_OD)
        t["now"] = start + 200
        s.close()
        for regno, plan in HISTORY.items():
            if plan[i] == "E":
                s.excuse(regno)
        store.save_session(s)


class Demo:
    def __init__(self, data_dir, clock=None):
        self.root = tk.Tk()
        self.clock = clock or Clock()
        self.app = App(self.root, data_dir, clock=self.clock)
        self.settle()

    def settle(self, seconds=0.35):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.03)

    def shot(self, name):
        self.settle()
        capture(self.root, OUT / f"{name}.png")
        print("saved", name)

    def type(self, widget, text):
        widget.delete(0, "end")
        widget.insert(0, text)
        a = self.app
        if widget is a.reg_entry:  # same update the <KeyRelease> binding does
            a._live_check(widget, a.reg_live, a.reg_path)
        elif widget is a.mark_entry:
            a._live_check(widget, a.mark_live)
        self.settle(0.1)

    def close(self):
        self.root.destroy()


def file_viewer(path: Path, title: str, name: str):
    """Show a text file in a plain window (used to picture the corrupted CSV)."""
    root = tk.Tk()
    root.title(title)
    lines = path.read_text(encoding="utf-8").splitlines()
    text = tk.Text(root, font=("Consolas", 12), width=62, height=len(lines) + 1, padx=10, pady=8)
    text.insert("1.0", path.read_text(encoding="utf-8"))
    for i, line in enumerate(lines, start=1):
        if line.count(",") != 2 or "Duplicate" in line:
            text.tag_add("bad", f"{i}.0", f"{i}.end")
    text.tag_configure("bad", background="#fee2e2", foreground="#991b1b")
    text.pack()
    root.update()
    time.sleep(0.3)
    root.update()
    capture(root, OUT / f"{name}.png")
    print("saved", name)
    root.destroy()


def main():
    enable_dpi_awareness()
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="attendance-demo-"))
    data = work / "data"
    seed(data)

    d = Demo(data)
    a = d.app
    # ---- Register tab --------------------------------------------------
    d.type(a.reg_entry, "24BIT01")
    d.shot("01_register_live_dfa")
    d.type(a.reg_entry, "24bit 03S7")
    d.type(a.name_entry, "M. Ananya")
    a._add_student()
    d.shot("02_error_invalid_regno")
    a._apply_reg_fix(a.store.dfa.suggest("24bit 03S7"))
    a._add_student()
    d.shot("03_recovered_regno")
    d.type(a.reg_entry, "24BIT0154")
    d.type(a.name_entry, "B. Harish")
    a._add_student()
    d.shot("04_error_duplicate_blocked")
    d.type(a.reg_entry, "24BIT0420")
    d.type(a.name_entry, "Rahul99")
    a._add_student()
    d.shot("05_error_invalid_name")
    a._clear_register()

    # ---- Attendance tab --------------------------------------------------
    a.nb.select(a.tab_att)
    d.type(a.mark_entry, "24BIT0154")
    a._mark()
    d.shot("06_error_no_session")
    a._start_and_mark()
    d.shot("07_recovered_session_started")
    d.type(a.mark_entry, "24BIT0999")
    a._mark()
    d.shot("08_error_unregistered")
    d.type(a.mark_entry, "24BIT0154")
    a._mark()
    d.shot("09_error_double_marking")
    d.type(a.mark_entry, "24bit0323")
    a._mark()
    d.shot("10_error_mark_typo")
    a._apply_mark_fix(a.dfa.suggest("24bit0323"))
    d.shot("11_recovered_mark_typo")
    d.clock.offset += 75  # into the late window
    d.settle(0.4)
    d.type(a.mark_entry, "24BIT0101")
    a._mark()
    d.shot("12_late_mark")
    a.att_tree.selection_set("24BIT0219")
    a._admin(GRANT_OD)
    d.shot("13_grant_od")
    d.clock.offset += 120  # past the end of the window -> automatic TIMEOUT
    d.settle(0.6)
    d.shot("14_timeout_auto_absent")
    a.att_tree.selection_set("24BIT0357")
    a._admin(EXCUSE)
    d.shot("15_excuse_after_timeout")

    # ---- FSM visualizer ----------------------------------------------------
    a.nb.select(a.tab_fsm)
    a.fsm_student_var.set("24BIT0357  ·  M. Ananya")
    a._on_fsm_student()
    d.shot("16_fsm_visualizer")
    capture(d.root, OUT / "fig_fsm_diagram.png", widget=a.fsm_canvas)

    # ---- DFA visualizer ----------------------------------------------------
    a.nb.select(a.tab_dfa)
    d.type(a.viz_entry, "24BIT0154")
    a._dfa_run(animate=False)
    d.shot("17_dfa_accept")
    capture(d.root, OUT / "fig_dfa_diagram.png", widget=a.dfa_canvas)
    d.type(a.viz_entry, "24B1T0154")
    a._dfa_load()
    for _ in range(3):
        a._dfa_step()
    d.shot("18_dfa_step_mid_run")
    a._dfa_run(animate=False)
    d.shot("19_dfa_reject_dead_state")
    d.type(a.pattern_entry, "24BIT##?#")
    a._rebuild_dfa()
    d.shot("20_error_bad_pattern")
    d.type(a.pattern_entry, "24BIT####, 24BDE####, 23BIT####")
    a._rebuild_dfa()
    d.type(a.viz_entry, "24BDE0123")
    a._dfa_run(animate=False)
    a.dfa_bar.hide()  # the same numbers are shown in the pattern card
    d.shot("21_dfa_multi_pattern")
    a._default_patterns()
    a.dfa_bar.hide()

    # ---- Reports -------------------------------------------------------------
    a.nb.select(a.tab_rep)
    a._refresh_reports()
    a._export(str(data / "attendance_report.xlsx"))
    d.shot("22_reports_export")
    d.close()

    # ---- Corrupted CSV recovery -------------------------------------------------
    bad = work / "corrupt"
    shutil.copytree(data, bad)
    with open(bad / "students.csv", "a", encoding="utf-8") as f:
        f.write("this line is broken\n24BIT0500,K. Teja,2026-10-22 10:00,EXTRA\n"
                "24BIT0154,Duplicate Harish,2026-10-22 10:05\n")
    file_viewer(bad / "students.csv", "students.csv  (damaged)", "23_error_corrupted_csv")
    d = Demo(bad)
    d.shot("24_recovered_corrupted_csv")
    d.close()

    # ---- Crash during a session -------------------------------------------------
    crash = work / "crash"
    shutil.copytree(data, crash, ignore=shutil.ignore_patterns("*.xlsx"))
    clock = Clock()
    d = Demo(crash, clock)
    a = d.app
    a.nb.select(a.tab_att)
    a._start_session()
    for regno in ("24BIT0154", "24BIT0323"):
        d.type(a.mark_entry, regno)
        a._mark()
    d.root.destroy()  # simulated crash: the session is never ended
    clock.offset += 20
    d = Demo(crash, clock)
    d.shot("25_error_interrupted_session")
    a = d.app
    a._restore_session(AttendanceSession.from_dict(a.store.read_snapshot(), clock=clock))
    d.shot("26_recovered_session_restored")
    d.close()
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
