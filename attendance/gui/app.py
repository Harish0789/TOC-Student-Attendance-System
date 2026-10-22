"""
Module 4 - Graphical User Interface (Tkinter)
=============================================

Tabs
  1. Register Students  - DFA checks the registration number live, with
                          "did you mean" error recovery
  2. Mark Attendance    - timer-controlled session; every mark is an FSM event
  3. DFA Visualizer     - draws M, animates a run on an input tape, edits patterns
  4. FSM Visualizer     - attendance state diagram + transition function table
  5. Reports            - 75 % rule analytics, Excel export, reject / audit log
"""

from __future__ import annotations

import argparse
import ctypes
import math
import os
import sys
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..analytics import THRESHOLD, summarize
from ..dfa import DEAD, DEFAULT_PATTERNS, PatternError, RegNoDFA, describe
from ..exporter import export_report
from ..fsm import (EVENTS, EXCUSE, GRANT_OD, NOT_MARKED, RESET, STATES, TRANSITIONS,
                   InvalidTransition)
from ..session import (CLOSED, LATE_PHASE, ON_TIME, AttendanceSession, SessionClosed,
                       UnknownStudent)
from ..storage import AttendanceStore, DuplicateStudent, InvalidName, InvalidRegNo
from .diagrams import DFADiagram, FSMDiagram
from .theme import C, FONT, MONO, STATE_STYLE, setup_styles
from .widgets import Badge, Card, entry, info_bar, label, make_tree, set_entry_state

PHASE_STYLE = {
    ON_TIME: ("ON-TIME WINDOW", "#dcfce7", "#166534"),
    LATE_PHASE: ("LATE WINDOW", "#fef3c7", "#92400e"),
    CLOSED: ("SESSION CLOSED", "#fee2e2", "#991b1b"),
    None: ("NO SESSION", "#f1f5f9", "#475569"),
}
PROJECT_DIR = Path(__file__).resolve().parents[2]


def fmt_min(value: float) -> str:
    return f"{value:g}"


class App:
    def __init__(self, root: tk.Tk, data_dir, clock=time.time):
        self.root = root
        self.clock = clock
        self.k = max(1.0, root.winfo_fpixels("1i") / 96.0)
        setup_styles(root)
        root.title("Student Attendance System — DFA + FSM (Theory of Computation)")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(int(1120 * self.k), int(sw * 0.95)), min(int(740 * self.k), int(sh * 0.9))
        root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        root.minsize(int(960 * self.k), int(620 * self.k))

        self.store = AttendanceStore(data_dir)
        self.settings = self.store.load_settings()
        try:
            self.dfa = RegNoDFA(self.settings["patterns"])
        except (PatternError, TypeError):
            self.dfa = RegNoDFA(DEFAULT_PATTERNS)
            self.settings["patterns"] = list(DEFAULT_PATTERNS)
        self.store.dfa = self.dfa

        self.session: AttendanceSession | None = None
        self.viz_trace = None
        self.viz_pos = 0
        self._dfa_job = None
        self._recovered_from = None

        self._build_header()
        self.status = tk.Label(root, anchor="w", bg="#e2e8f0", fg=C["muted"], font=(FONT, 9),
                               padx=12, pady=3)
        self.status.pack(fill="x", side="bottom")
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True)
        self.tab_reg = self._tab("  Register Students  ")
        self.tab_att = self._tab("  Mark Attendance  ")
        self.tab_dfa = self._tab("  DFA Visualizer  ")
        self.tab_fsm = self._tab("  FSM Visualizer  ")
        self.tab_rep = self._tab("  Reports & Logs  ")
        self._build_register_tab(self.tab_reg)
        self._build_attendance_tab(self.tab_att)
        self._build_dfa_tab(self.tab_dfa)
        self._build_fsm_tab(self.tab_fsm)
        self._build_reports_tab(self.tab_rep)

        self._refresh_dfa_views()
        self._refresh_all()
        self._startup_checks()
        root.bind("<Destroy>", self._on_destroy, add="+")
        self._tick()

    # ==================================================================
    # Layout helpers
    # ==================================================================
    def _tab(self, text):
        frame = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(frame, text=text)
        return frame

    def _build_header(self):
        bar = tk.Frame(self.root, bg=C["navy"])
        bar.pack(fill="x")
        left = tk.Frame(bar, bg=C["navy"])
        left.pack(side="left", padx=18, pady=9)
        tk.Label(left, text="Student Attendance System", bg=C["navy"], fg="#ffffff",
                 font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(left, text="Theory of Computation project  ·  DFA-validated registration  ·  "
                            "FSM-based attendance tracking",
                 bg=C["navy"], fg="#c7d2fe", font=(FONT, 10)).pack(anchor="w")
        right = tk.Frame(bar, bg=C["navy"])
        right.pack(side="right", padx=18)
        self.header_clock = tk.Label(right, bg=C["navy"], fg="#ffffff", font=(FONT, 12, "bold"))
        self.header_clock.pack(anchor="e")
        self.header_dfa = tk.Label(right, bg=C["navy"], fg="#c7d2fe", font=(MONO, 9))
        self.header_dfa.pack(anchor="e")

    # ==================================================================
    # Tab 1 - Register students
    # ==================================================================
    def _build_register_tab(self, tab):
        tab.columnconfigure(0, weight=5, uniform="reg")
        tab.columnconfigure(1, weight=6, uniform="reg")
        tab.rowconfigure(0, weight=1)

        form = Card(tab, "Add New Student",
                    "The registration number is checked by the DFA while you type.")
        form.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=14)
        b = form.body
        label(b, "Registration No.", bold=True).pack(anchor="w", pady=(4, 3))
        self.reg_entry = entry(b, width=24, mono=True, size=14)
        self.reg_entry.pack(fill="x", ipady=4)
        self.reg_live = label(b, "", size=9, color=C["muted"], anchor="w", justify="left")
        self.reg_live.pack(fill="x", pady=(5, 0))
        self.reg_path = label(b, "", size=9, mono=True, color=C["muted"], anchor="w",
                              justify="left")
        self.reg_path.pack(fill="x")
        self.reg_mini = DFADiagram(b, self.dfa, compact=True, height=int(78 * self.k))
        self.reg_mini.pack(fill="x", pady=(4, 0))
        label(b, "Student Name", bold=True).pack(anchor="w", pady=(10, 3))
        self.name_entry = entry(b, width=30, size=12)
        self.name_entry.pack(fill="x", ipady=4)
        btns = tk.Frame(b, bg=C["card"])
        btns.pack(fill="x", pady=12)
        ttk.Button(btns, text="Add Student", style="Primary.TButton",
                   command=self._add_student).pack(side="left")
        ttk.Button(btns, text="Clear", style="Ghost.TButton",
                   command=self._clear_register).pack(side="left", padx=8)
        holder, self.reg_bar = info_bar(b)
        holder.pack(fill="x")
        self.reg_hint = label(b, "", size=9, color=C["muted"], anchor="w", justify="left")
        self.reg_hint.pack(side="bottom", fill="x", pady=(8, 0))
        for w in (self.reg_live, self.reg_path, self.reg_hint):
            w.bind("<Configure>", lambda e, w=w: w.configure(wraplength=max(200, e.width - 4)))

        self.reg_entry.bind("<KeyRelease>",
                            lambda e: self._live_check(self.reg_entry, self.reg_live, self.reg_path))
        self.reg_entry.bind("<Return>", lambda e: self.name_entry.focus_set())
        self.name_entry.bind("<Return>", lambda e: self._add_student())

        lst = Card(tab, "Registered Students")
        lst.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=14)
        label(lst.head_right, "Search ", color=C["muted"]).pack(side="left")
        self.search_entry = entry(lst.head_right, width=16, size=10)
        self.search_entry.pack(side="left", ipady=2)
        self.search_entry.bind("<KeyRelease>", lambda e: self._refresh_students())
        frame, self.student_tree = make_tree(lst.body, [
            ("regno", "Reg No", 110, "w"), ("name", "Name", 200, "w"),
            ("added", "Date Added", 140, "w")], height=12)
        frame.pack(fill="both", expand=True)
        bottom = tk.Frame(lst.body, bg=C["card"])
        bottom.pack(fill="x", pady=(10, 0))
        self.student_count = label(bottom, "", color=C["muted"])
        self.student_count.pack(side="left")
        ttk.Button(bottom, text="Delete Selected", style="Danger.TButton",
                   command=self._delete_student).pack(side="right")
        self._live_check(self.reg_entry, self.reg_live, self.reg_path)

    def _live_check(self, widget, live_label, path_label=None):
        text = widget.get().strip()
        mini = self.reg_mini if widget is self.reg_entry else None
        if not text:
            set_entry_state(widget, None)
            live_label.configure(text="DFA waiting in start state q0", fg=C["muted"])
            if path_label is not None:
                path_label.configure(text="")
            if mini is not None:
                mini.clear_run()
            return None
        tr = self.dfa.trace(text)
        if mini is not None:
            mini.show_run(tr, len(tr.steps), tr.accepted or tr.final_state == DEAD)
        if tr.accepted:
            kind, color = "ok", C["success"]
            msg = f"✔ Accepted — the run ends in final state {tr.final_state} ∈ F"
        elif tr.final_state == DEAD:
            kind, color = "error", C["danger"]
            pos = tr.error_position
            msg = (f"✖ Dead state at position {pos + 1} ('{text[pos]}') — state "
                   f"{tr.steps[-1].source} expects {describe(self.dfa.expected(tr.steps[-1].source))}")
        else:
            kind, color = "live", C["warning"]
            need = self.dfa.distance_to_accept(tr.final_state)
            msg = (f"… Live state {tr.final_state}: next expected "
                   f"{describe(self.dfa.expected(tr.final_state))} ({need} more symbol(s))")
        set_entry_state(widget, kind)
        live_label.configure(text=msg, fg=color)
        if path_label is not None:
            path_label.configure(text="Run: " + tr.path_text())
        return tr

    def _add_student(self):
        raw = self.reg_entry.get()
        self._live_check(self.reg_entry, self.reg_live, self.reg_path)
        try:
            student = self.store.add_student(raw, self.name_entry.get())
        except InvalidRegNo as e:
            self._recovered_from = None
            self._show_regno_error(self.reg_bar, raw, e.trace, e.suggestion, self._apply_reg_fix)
            self._live_check(self.reg_entry, self.reg_live, self.reg_path)
            set_entry_state(self.reg_entry, "error")
            offset = len(raw) - len(raw.lstrip())
            if e.trace.error_position is not None:
                p = e.trace.error_position + offset
                self.reg_entry.focus_set()
                self.reg_entry.selection_range(p, p + 1)
                self.reg_entry.icursor(p + 1)
            self._refresh_reports()
            return
        except DuplicateStudent as e:
            self.reg_bar.show(
                "warning", "Duplicate registration blocked",
                f"{e.regno} is already registered as {e.name} (added {e.added}). "
                f"No second record was created — the existing record is highlighted in the list.",
                actions=[("Clear form", self._clear_register)])
            self._select_student(e.regno)
            self._refresh_reports()
            return
        except InvalidName as e:
            self.reg_bar.show("error", "Invalid student name", str(e))
            set_entry_state(self.name_entry, "error")
            self.name_entry.focus_set()
            return
        set_entry_state(self.name_entry, None)
        if self._recovered_from:
            title = "Recovered input accepted and registered"
            msg = (f"'{self._recovered_from}' was corrected to {student.regno}. The DFA accepted it "
                   f"and {student.name} was saved to students.csv.")
        else:
            title = "Student registered"
            msg = f"{student.regno} · {student.name} was accepted by the DFA and saved to students.csv."
        trace = self.dfa.trace(student.regno)
        self.reg_bar.show("success", title, msg, details="Run: " + trace.path_text())
        self._recovered_from = None
        if self.session is not None and not self.session.closed:
            self.session.add_student(student.regno, student.name)
            self.store.write_snapshot(self.session)
        self.reg_entry.delete(0, "end")
        self.name_entry.delete(0, "end")
        self._live_check(self.reg_entry, self.reg_live, self.reg_path)
        self._refresh_all()
        self._select_student(student.regno)
        self.reg_entry.focus_set()

    def _show_regno_error(self, bar, raw, trace, suggestion, apply_fix):
        details = "Run: " + trace.path_text()
        actions = []
        msg = trace.reason
        if suggestion:
            msg += f"\n\nDid you mean {suggestion.corrected}?"
            details += "\nRecovery: " + "; ".join(suggestion.fixes)
            actions.append((f"Use {suggestion.corrected}", lambda: apply_fix(suggestion)))
        actions.append(("Open in DFA visualizer", lambda: self._open_in_visualizer(raw.strip())))
        bar.show("error", "Invalid registration number — rejected by the DFA", msg,
                 details=details, actions=actions)

    def _apply_reg_fix(self, suggestion):
        self._recovered_from = suggestion.original
        self.reg_entry.delete(0, "end")
        self.reg_entry.insert(0, suggestion.corrected)
        self._live_check(self.reg_entry, self.reg_live, self.reg_path)
        self.reg_bar.show("info", "Suggestion applied — check the name and press Add Student",
                          f"'{suggestion.original}' → {suggestion.corrected}",
                          details="Fixes: " + "; ".join(suggestion.fixes),
                          actions=[("Add Student", self._add_student)])
        self.name_entry.focus_set()

    def _clear_register(self):
        self.reg_entry.delete(0, "end")
        self.name_entry.delete(0, "end")
        set_entry_state(self.name_entry, None)
        self._live_check(self.reg_entry, self.reg_live, self.reg_path)
        self.reg_bar.hide()
        self._recovered_from = None

    def _select_student(self, regno):
        if regno in self.student_tree.get_children():
            self.student_tree.selection_set(regno)
            self.student_tree.see(regno)

    def _delete_student(self):
        sel = self.student_tree.selection()
        if not sel:
            self.reg_bar.show("info", "Nothing selected", "Select a student in the list first.")
            return
        if self.session is not None and not self.session.closed:
            self.reg_bar.show("error", "Session running",
                              "Students cannot be deleted while an attendance session is running. "
                              "End the session first.")
            return
        if not messagebox.askyesno("Delete student",
                                   f"Delete {len(sel)} student(s)? Saved attendance rows are kept."):
            return
        for regno in sel:
            self.store.delete_student(regno)
        self.reg_bar.show("success", "Deleted", f"Removed {', '.join(sel)} from students.csv.")
        self._refresh_all()

    # ==================================================================
    # Tab 2 - Mark attendance
    # ==================================================================
    def _build_attendance_tab(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        top = Card(tab, "Attendance Session (Timer & Control)",
                   "On-time window → MARK_ON_TIME,  later → MARK_LATE,  window ends → TIMEOUT for "
                   "every unmarked student.")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        b = top.body
        b.columnconfigure(0, weight=1)
        ctl = tk.Frame(b, bg=C["card"])
        ctl.grid(row=0, column=0, sticky="w")
        spin = dict(width=6, font=(FONT, 11), relief="flat", highlightthickness=1,
                    highlightbackground=C["border"], increment=0.5, from_=0.5, to=180)
        label(ctl, "Session length (min)").grid(row=0, column=0, sticky="w")
        self.duration_var = tk.StringVar()
        tk.Spinbox(ctl, textvariable=self.duration_var, **spin).grid(row=0, column=1, padx=(6, 18))
        label(ctl, "On-time window (min)").grid(row=0, column=2, sticky="w")
        self.on_time_var = tk.StringVar()
        tk.Spinbox(ctl, textvariable=self.on_time_var, **spin).grid(row=0, column=3, padx=(6, 18))
        # set after creation: a Tk Spinbox resets its variable to from_ when it is created
        self.duration_var.set(fmt_min(float(self.settings["duration_min"])))
        self.on_time_var.set(fmt_min(float(self.settings["on_time_min"])))
        btns = tk.Frame(ctl, bg=C["card"])
        btns.grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self.start_btn = ttk.Button(btns, text="▶  Start Session", style="Success.TButton",
                                    command=self._start_session)
        self.start_btn.pack(side="left")
        self.end_btn = ttk.Button(btns, text="■  End Session", style="Danger.TButton",
                                  command=self._end_session)
        self.end_btn.pack(side="left", padx=8)

        timer = tk.Frame(b, bg=C["card"])
        timer.grid(row=0, column=1, sticky="e")
        self.countdown = label(timer, "--:--", size=24, bold=True, color=C["navy"])
        self.countdown.pack(side="left", padx=(0, 12))
        tcol = tk.Frame(timer, bg=C["card"])
        tcol.pack(side="left")
        self.phase_badge = Badge(tcol, "NO SESSION", "#f1f5f9", "#475569")
        self.phase_badge.pack(anchor="w")
        self.session_label = label(tcol, "No session started", size=9, color=C["muted"])
        self.session_label.pack(anchor="w", pady=(3, 0))
        self.progress = ttk.Progressbar(b, maximum=100)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        holder, self.att_bar = info_bar(tab)
        holder.grid(row=1, column=0, sticky="ew", padx=16)

        table = Card(tab, "Mark Attendance  ·  Today's Session")
        table.grid(row=2, column=0, sticky="nsew", padx=16, pady=(6, 12))
        self.stat_frame = table.head_right
        m = tk.Frame(table.body, bg=C["card"])
        m.pack(fill="x", pady=(0, 8))
        label(m, "Reg No", bold=True).grid(row=0, column=0, sticky="w")
        self.mark_entry = entry(m, width=18, mono=True, size=14)
        self.mark_entry.grid(row=0, column=1, padx=8, ipady=3)
        ttk.Button(m, text="Mark Attendance", style="Primary.TButton",
                   command=self._mark).grid(row=0, column=2)
        sep = tk.Frame(m, bg=C["border"], width=1)
        sep.grid(row=0, column=3, sticky="ns", padx=16)
        label(m, "Selected student(s):", color=C["muted"]).grid(row=0, column=4, sticky="w")
        ttk.Button(m, text="Excuse", style="Violet.TButton",
                   command=lambda: self._admin(EXCUSE)).grid(row=0, column=5, padx=(8, 0))
        ttk.Button(m, text="Grant OD", style="Teal.TButton",
                   command=lambda: self._admin(GRANT_OD)).grid(row=0, column=6, padx=(8, 0))
        ttk.Button(m, text="Undo (RESET)", style="Ghost.TButton",
                   command=lambda: self._admin(RESET)).grid(row=0, column=7, padx=(8, 0))
        self.mark_live = label(m, "", size=9, color=C["muted"], anchor="w")
        self.mark_live.grid(row=1, column=0, columnspan=8, sticky="w", pady=(5, 0))
        self.mark_entry.bind("<Return>", lambda e: self._mark())
        self.mark_entry.bind("<KeyRelease>",
                             lambda e: self._live_check(self.mark_entry, self.mark_live))

        frame, self.att_tree = make_tree(table.body, [
            ("regno", "Reg No", 110, "w"), ("name", "Name", 190, "w"),
            ("state", "FSM State", 120, "w"), ("marked", "Marked At", 90, "center"),
            ("last", "Last Transition", 330, "w")], height=6)
        frame.pack(fill="both", expand=True)
        for state, (bg, fg, _) in STATE_STYLE.items():
            self.att_tree.tag_configure(state, background=bg, foreground=fg)
        self.att_tree.bind("<<TreeviewSelect>>", self._on_att_select)
        self._live_check(self.mark_entry, self.mark_live)

    def _read_minutes(self, var, default):
        try:
            value = float(var.get())
            if value <= 0:
                raise ValueError
            return value
        except ValueError:
            var.set(fmt_min(default))
            raise

    def _start_session(self):
        if self.session is not None and not self.session.closed:
            self.att_bar.show("info", "A session is already running",
                              f"{self.session.session_id} is still open. End it before starting a new one.")
            return
        if not self.store.students:
            self.att_bar.show("error", "No students registered",
                              "Register at least one student before starting a session.",
                              actions=[("Go to Register tab", lambda: self.nb.select(self.tab_reg))])
            return
        try:
            duration = self._read_minutes(self.duration_var, 3.0)
            on_time = self._read_minutes(self.on_time_var, 1.0)
            roster = {r: s.name for r, s in self.store.students.items()}
            session = AttendanceSession(roster, duration * 60, on_time * 60, clock=self.clock)
        except ValueError as e:
            self.att_bar.show("error", "Invalid timer settings",
                              (str(e) or "Enter the times in minutes, e.g. 3 and 1.")
                              + " The fields were reset to valid values.")
            return
        self.session = session
        self.settings.update(duration_min=duration, on_time_min=on_time)
        self.store.save_settings(self.settings)
        self.store.write_snapshot(session)
        self.att_bar.show("info", f"Session {session.session_id} started",
                          f"{fmt_min(duration)} minute window — the first {fmt_min(on_time)} minute(s) "
                          f"count as on time. All {len(roster)} students start in the FSM start "
                          f"state NOT_MARKED.")
        self._refresh_attendance()
        self._update_timer()
        self.mark_entry.focus_set()

    def _end_session(self, auto=False, restored=False):
        s = self.session
        if s is None or s.closed:
            self.att_bar.show("info", "No running session", "Start a session first.")
            return
        records = s.close()
        for regno, rec in records:
            self.store.log_transition(s.session_id, regno, rec)
        self.store.save_session(s)
        self.store.clear_snapshot()
        if restored:
            title = "Session restored and closed — its time had already run out"
        elif auto:
            title = "Time limit reached — session closed automatically"
        else:
            title = "Session ended by faculty"
        msg = (f"{len(records)} unmarked student(s) received the TIMEOUT event "
               f"(NOT_MARKED → ABSENT). Final states of all {len(s.machines)} students were saved "
               f"to attendance.csv.")
        details = "\n".join(f"{r}  {s.roster.get(r, ''):<22} NOT_MARKED --TIMEOUT--> ABSENT"
                            for r, _ in records) or None
        self.att_bar.show("warning" if records else "success", title, msg, details=details)
        self._refresh_all()
        self._update_timer()

    def _mark(self):
        raw = self.mark_entry.get().strip()
        s = self.session
        self._live_check(self.mark_entry, self.mark_live)
        if not raw:
            self.att_bar.show("info", "Enter a registration number",
                              "Type or scan the student's registration number and press Enter.")
            return
        if s is None or s.closed:
            self.store.log_reject("SESSION", raw, "mark attempted with no active session")
            self.att_bar.show("error", "No active attendance session",
                              f"{raw} cannot be marked because no session is running. Attendance "
                              f"is only accepted inside a timed session window.",
                              actions=[("Start session now", self._start_and_mark)])
            self._refresh_reports()
            return
        trace = self.dfa.trace(raw)
        if not trace.accepted:
            suggestion = self.dfa.suggest(raw)
            self.store.log_reject("MARK", raw, trace.reason)
            self._show_regno_error(self.att_bar, raw, trace, suggestion, self._apply_mark_fix)
            self._live_check(self.mark_entry, self.mark_live)
            self._refresh_reports()
            return
        if raw not in self.store.students:
            self.store.log_reject("MARK", raw, "registration number not registered")
            self.att_bar.show("error", "Student not registered",
                              f"{raw} is a valid registration number (accepted by the DFA) but it "
                              f"is not in students.csv, so it cannot be marked.",
                              actions=[("Register this student", lambda: self._register_from_mark(raw))])
            self._refresh_reports()
            return
        if raw not in s.machines:
            s.add_student(raw, self.store.students[raw].name)
        try:
            rec = s.mark(raw)
        except InvalidTransition as e:
            self.store.log_reject("FSM", raw, str(e))
            fsm = s.machines[raw]
            history = "\n".join(str(h) for h in fsm.history)
            self.att_bar.show("warning", "Duplicate marking blocked by the FSM",
                              f"{raw} ({s.roster.get(raw)}) is already {fsm.state}"
                              f"{' since ' + s.marked_at[raw] if raw in s.marked_at else ''}. "
                              f"{e} The attempt was logged in reject_log.csv.",
                              details="History of this student:\n" + history)
            self._select_att(raw)
            self._refresh_reports()
            return
        except SessionClosed as e:
            self.att_bar.show("error", "Session closed", str(e))
            return
        self.store.log_transition(s.session_id, raw, rec)
        self.store.write_snapshot(s)
        on_time = rec.target != "LATE"
        self.att_bar.show("success" if on_time else "warning",
                          f"{raw} marked {rec.target}" + (" (on time)" if on_time else " (after the cut-off)"),
                          f"{s.roster.get(raw)}:  {rec.source} --{rec.event}--> {rec.target}  at {rec.time}")
        self.mark_entry.delete(0, "end")
        self._live_check(self.mark_entry, self.mark_live)
        self._refresh_attendance()
        self._select_att(raw)

    def _start_and_mark(self):
        self._start_session()
        if self.session is not None and not self.session.closed and self.mark_entry.get().strip():
            self._mark()

    def _apply_mark_fix(self, suggestion):
        self.mark_entry.delete(0, "end")
        self.mark_entry.insert(0, suggestion.corrected)
        self._live_check(self.mark_entry, self.mark_live)
        self._mark()

    def _register_from_mark(self, regno):
        self.nb.select(self.tab_reg)
        self.reg_entry.delete(0, "end")
        self.reg_entry.insert(0, regno)
        self._live_check(self.reg_entry, self.reg_live, self.reg_path)
        self.reg_bar.show("info", "Register the student, then mark again",
                          f"{regno} was copied from the attendance screen. Enter the name and press "
                          f"Add Student — the student also joins the running session.")
        self.name_entry.focus_set()

    def _selected_regnos(self):
        sel = list(self.att_tree.selection())
        if not sel:
            raw = self.mark_entry.get().strip()
            if raw and self.session is not None and raw in self.session.machines:
                sel = [raw]
        return sel

    def _admin(self, event):
        s = self.session
        if s is None:
            self.att_bar.show("info", "No session", "Start a session first.")
            return
        regnos = self._selected_regnos()
        if not regnos:
            self.att_bar.show("info", "No student selected",
                              "Select one or more students in the table (or type a registration "
                              "number) and try again.")
            return
        done, failed = [], []
        for regno in regnos:
            try:
                if event == EXCUSE:
                    rec = s.excuse(regno)
                elif event == GRANT_OD:
                    rec = s.grant_od(regno)
                else:
                    rec = s.reset(regno)
                self.store.log_transition(s.session_id, regno, rec)
                done.append(f"{regno}  {rec.source} --{rec.event}--> {rec.target}")
            except InvalidTransition as e:
                self.store.log_reject("FSM", regno, str(e))
                failed.append(f"{regno}  {e}")
            except (SessionClosed, UnknownStudent) as e:
                failed.append(f"{regno}  {e}")
        if s.closed:
            self.store.save_session(s)
        else:
            self.store.write_snapshot(s)
        kind = "success" if not failed else ("warning" if done else "error")
        title = {EXCUSE: "Excuse", GRANT_OD: "On-duty", RESET: "Undo (RESET)"}[event]
        title += f": {len(done)} applied" + (f", {len(failed)} rejected by the FSM" if failed else "")
        self.att_bar.show(kind, title, "Every change is an FSM event and is written to audit_log.csv.",
                          details="\n".join(done + failed))
        self._refresh_attendance()
        self._refresh_reports()

    def _select_att(self, regno):
        if regno in self.att_tree.get_children():
            self.att_tree.selection_set(regno)
            self.att_tree.see(regno)

    def _on_att_select(self, _event=None):
        sel = self.att_tree.selection()
        if sel and self.session is not None:
            regno = sel[0]
            self.fsm_student_var.set(f"{regno}  ·  {self.session.roster.get(regno, '')}")
            self._on_fsm_student()

    def _update_timer(self):
        s = self.session
        if s is None:
            text, phase, value = "--:--", None, 0
            info = "No session started"
        else:
            phase = s.phase()
            rem = 0 if s.closed else s.remaining()
            mm, ss = divmod(int(math.ceil(rem)), 60)
            text = f"{mm:02d}:{ss:02d}"
            value = 100 if s.closed else min(100, 100 * s.elapsed() / s.duration)
            info = (f"{s.session_id}  ·  on time for the first {fmt_min(s.on_time / 60)} of "
                    f"{fmt_min(s.duration / 60)} min")
        caption, bg, fg = PHASE_STYLE[phase]
        self.countdown.configure(text=text, fg=fg if phase in (LATE_PHASE, CLOSED) else C["navy"])
        self.phase_badge.configure(text=caption, bg=bg, fg=fg)
        self.session_label.configure(text=info)
        self.progress.configure(value=value)
        running = s is not None and not s.closed
        self.start_btn.state(["disabled"] if running else ["!disabled"])
        self.end_btn.state(["!disabled"] if running else ["disabled"])

    def _tick(self):
        now = datetime.fromtimestamp(self.clock())
        self.header_clock.configure(text=now.strftime("%a %d %b %Y   %H:%M:%S"))
        s = self.session
        if s is not None and not s.closed and s.expired:
            self._end_session(auto=True)
        self._update_timer()
        self._tick_job = self.root.after(250, self._tick)

    def _on_destroy(self, event):
        if event.widget is self.root and getattr(self, "_tick_job", None):
            self.root.after_cancel(self._tick_job)
            self._cancel_dfa_job()

    # ==================================================================
    # Tab 3 - DFA visualizer
    # ==================================================================
    def _build_dfa_tab(self, tab):
        tab.columnconfigure(0, weight=1)
        # the diagram keeps a usable height; the panels below give way first
        tab.rowconfigure(2, weight=4, minsize=int(230 * self.k))
        tab.rowconfigure(3, weight=1, minsize=int(140 * self.k))
        top = Card(tab, "Registration-number language L(M)")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        b = top.body
        row = tk.Frame(b, bg=C["card"])
        row.pack(fill="x")
        label(row, "Accepted ID patterns", bold=True).pack(side="left")
        self.pattern_entry = entry(row, width=40, mono=True, size=12)
        self.pattern_entry.pack(side="left", padx=8, ipady=2)
        self.pattern_entry.bind("<Return>", lambda e: self._rebuild_dfa())
        ttk.Button(row, text="Rebuild DFA", style="Primary.TButton",
                   command=self._rebuild_dfa).pack(side="left")
        ttk.Button(row, text="Default", style="Ghost.TButton",
                   command=self._default_patterns).pack(side="left", padx=8)
        label(b, "#  digit 0-9    ·    @  letter A-Z    ·    other symbols are literals    ·    "
                 "commas separate patterns (union → subset construction → minimisation)",
              size=9, color=C["muted"], anchor="w", justify="left").pack(fill="x", pady=(6, 0))
        self.dfa_info = label(b, "", size=9, bold=True, color=C["navy"], anchor="w")
        self.dfa_info.pack(fill="x")
        holder, self.dfa_bar = info_bar(tab)
        holder.grid(row=1, column=0, sticky="ew", padx=16)

        canvas_card = Card(tab)
        canvas_card.grid(row=2, column=0, sticky="nsew", padx=16, pady=6)
        ctl = tk.Frame(canvas_card.body, bg=C["card"])
        ctl.pack(fill="x", pady=(2, 6))
        self.dfa_canvas = DFADiagram(canvas_card.body, self.dfa, height=int(250 * self.k))
        self.dfa_canvas.pack(fill="both", expand=True)
        label(ctl, "Test string", bold=True).pack(side="left")
        self.viz_entry = entry(ctl, width=18, mono=True, size=13)
        self.viz_entry.pack(side="left", padx=8, ipady=2)
        self.viz_entry.insert(0, "24BIT0154")
        self.viz_entry.bind("<Return>", lambda e: self._dfa_run())
        ttk.Button(ctl, text="▶ Run", style="Primary.TButton",
                   command=self._dfa_run).pack(side="left")
        ttk.Button(ctl, text="Step", style="Ghost.TButton",
                   command=self._dfa_step_button).pack(side="left", padx=6)
        ttk.Button(ctl, text="Reset", style="Ghost.TButton",
                   command=self._dfa_reset).pack(side="left")
        self.viz_result = label(ctl, "", bold=True, anchor="w")
        self.viz_result.pack(side="left", padx=12, fill="x", expand=True)

        bottom = tk.Frame(tab, bg=C["bg"])
        bottom.grid(row=3, column=0, sticky="nsew", padx=16, pady=(6, 12))
        bottom.rowconfigure(0, weight=1)
        for i, w in enumerate((3, 3, 4)):
            bottom.columnconfigure(i, weight=w, uniform="dfa")
        d1 = Card(bottom, "Formal definition  M = (Q, Σ, δ, q0, F)")
        d1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.formal_label = label(d1.body, "", size=9, mono=True, anchor="nw", justify="left")
        self.formal_label.pack(fill="both", expand=True)
        d2 = Card(bottom, "Run trace")
        d2.grid(row=0, column=1, sticky="nsew", padx=6)
        self.trace_list = tk.Listbox(d2.body, height=5, font=(MONO, 9), relief="flat",
                                     highlightthickness=1, highlightbackground=C["border"],
                                     activestyle="none")
        self.trace_list.pack(fill="both", expand=True)
        d3 = Card(bottom, "Transition table δ")
        d3.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        frame, self.delta_tree = make_tree(d3.body, [
            ("state", "State", 55, "w"), ("kind", "Type", 70, "w"),
            ("moves", "Transitions", 260, "w")], height=5, style="Compact.Treeview")
        frame.pack(fill="both", expand=True)

    def _refresh_dfa_views(self):
        d = self.dfa
        self.pattern_entry.delete(0, "end")
        self.pattern_entry.insert(0, ", ".join(d.patterns))
        set_entry_state(self.pattern_entry, None)
        self.dfa_info.configure(
            text=f"Subset construction: {d.states_before_minimization} states  →  after Moore "
                 f"minimisation: {len(d.states)} states (+ dead state qd)   ·   "
                 f"final states F = {{{', '.join(sorted(d.accept))}}}")
        self.formal_label.configure(text=d.formal_definition())
        self.delta_tree.delete(*self.delta_tree.get_children())
        for q, kind, moves in d.transition_rows():
            self.delta_tree.insert("", "end", values=(q, kind, moves))
        self.dfa_canvas.set_dfa(d)
        self.reg_mini.set_dfa(d)
        self.trace_list.delete(0, "end")
        self.viz_trace, self.viz_pos = None, 0
        self.viz_result.configure(text="")
        self.header_dfa.configure(text=f"L(M) = {' ∪ '.join(d.patterns)}   ·   "
                                       f"{len(d.states)} states + qd")
        self.reg_hint.configure(text=f"Accepted pattern(s): {', '.join(d.patterns)}   "
                                     f"(# = digit, @ = letter).  Examples: 24BIT0154, 24BDE0123")

    def _rebuild_dfa(self):
        text = self.pattern_entry.get()
        old = self.dfa
        try:
            new = RegNoDFA([p for p in text.split(",")])
        except PatternError as e:
            set_entry_state(self.pattern_entry, "error")
            self.dfa_bar.show("error", "Pattern rejected — the previous DFA is still active", str(e),
                              details=f"Still using: {', '.join(old.patterns)}  "
                                      f"({len(old.states)} states + qd)",
                              actions=[("Restore previous patterns", self._refresh_dfa_views)])
            return
        self.dfa = new
        self.store.dfa = new
        self.settings["patterns"] = list(new.patterns)
        self.store.save_settings(self.settings)
        self._refresh_dfa_views()
        mismatched = [r for r in self.store.students if not new.accepts(r)]
        msg = (f"Subset construction produced {new.states_before_minimization} states; Moore's "
               f"algorithm minimised them to {len(new.states)} (+ dead state qd).")
        if mismatched:
            self.dfa_bar.show("warning", "DFA rebuilt — some registered students do not match",
                              msg + f" {len(mismatched)} already-registered student(s) are outside "
                                    f"the new language; they stay registered.",
                              details=", ".join(mismatched[:12]))
        else:
            self.dfa_bar.show("success", "DFA rebuilt", msg)
        self._live_check(self.reg_entry, self.reg_live, self.reg_path)

    def _default_patterns(self):
        self.pattern_entry.delete(0, "end")
        self.pattern_entry.insert(0, ", ".join(DEFAULT_PATTERNS))
        self._rebuild_dfa()

    def _open_in_visualizer(self, text):
        self.nb.select(self.tab_dfa)
        self.viz_entry.delete(0, "end")
        self.viz_entry.insert(0, text)
        self._dfa_run()

    def _cancel_dfa_job(self):
        if self._dfa_job is not None:
            self.root.after_cancel(self._dfa_job)
            self._dfa_job = None

    def _dfa_load(self):
        self._cancel_dfa_job()
        text = self.viz_entry.get().strip()
        self.viz_trace = self.dfa.trace(text)
        self.viz_pos = 0
        self.trace_list.delete(0, "end")
        self.trace_list.insert("end", f"input: {text or 'ε (empty)'}")
        self.trace_list.insert("end", "start in q0")
        done = not self.viz_trace.steps
        self.dfa_canvas.show_run(self.viz_trace, 0, done)
        if done:
            self._dfa_finish()
        else:
            self.viz_result.configure(text="Running…", fg=C["warning"])

    def _dfa_run(self, animate=True):
        self._dfa_load()
        if animate:
            self._dfa_job = self.root.after(400, self._dfa_auto)
        else:
            while not self._dfa_step():
                pass

    def _dfa_auto(self):
        self._dfa_job = None
        if not self._dfa_step():
            self._dfa_job = self.root.after(420, self._dfa_auto)

    def _dfa_step_button(self):
        self._cancel_dfa_job()
        if self.viz_trace is None or self.viz_trace.text != self.viz_entry.get().strip():
            self._dfa_load()
            return
        self._dfa_step()

    def _dfa_step(self) -> bool:
        tr = self.viz_trace
        if tr is None or self.viz_pos >= len(tr.steps):
            return True
        st = tr.steps[self.viz_pos]
        self.viz_pos += 1
        self.trace_list.insert("end", f"{self.viz_pos:>2}. {st}")
        self.trace_list.see("end")
        done = self.viz_pos >= len(tr.steps)
        self.dfa_canvas.show_run(tr, self.viz_pos, done)
        if done:
            self._dfa_finish()
        else:
            self.viz_result.configure(text=f"Running…  in state {st.target}", fg=C["warning"])
        return done

    def _dfa_finish(self):
        tr = self.viz_trace
        if tr.accepted:
            self.trace_list.insert("end", f"ACCEPT  ({tr.final_state} ∈ F)")
            self.viz_result.configure(text=f"ACCEPTED ✔  {tr.final_state} ∈ F", fg=C["success"])
        else:
            self.trace_list.insert("end", "REJECT")
            if tr.final_state == DEAD:
                why = f"dead state at position {tr.error_position + 1} ('{tr.text[tr.error_position]}')"
            elif not tr.steps:
                why = "empty input, q0 is not final"
            else:
                why = f"ended in non-final state {tr.final_state}"
            self.viz_result.configure(text=f"REJECTED ✖  {why}", fg=C["danger"])
        self.trace_list.see("end")

    def _dfa_reset(self):
        self._cancel_dfa_job()
        self.viz_trace, self.viz_pos = None, 0
        self.trace_list.delete(0, "end")
        self.viz_result.configure(text="")
        self.dfa_canvas.clear_run()

    # ==================================================================
    # Tab 4 - FSM visualizer
    # ==================================================================
    def _build_fsm_tab(self, tab):
        tab.columnconfigure(0, weight=13, uniform="fsm")
        tab.columnconfigure(1, weight=7, uniform="fsm")
        tab.rowconfigure(0, weight=1)
        diag = Card(tab, "Attendance FSM — state diagram")
        diag.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=(12, 6))
        self.fsm_canvas = FSMDiagram(diag.body, height=int(300 * self.k))
        self.fsm_canvas.pack(fill="both", expand=True)
        label(diag.body, "Highlighted = selected student's current state (blue arrow = last move).   "
                         "RESET (admin undo, only while the session runs): PRESENT / LATE / "
                         "EXCUSED / ON_DUTY → NOT_MARKED", size=8, color=C["muted"], anchor="w",
              justify="left").pack(fill="x", pady=(4, 0))

        table = Card(tab, "Transition function δ : S × E → S   ( — = undefined, event rejected )")
        table.grid(row=1, column=0, sticky="ew", padx=(16, 8), pady=(6, 12))
        cols = [("state", "State \\ Event", 96, "w")] + [(e, e, 88, "center") for e in EVENTS]
        frame, self.fsm_table = make_tree(table.body, cols, height=6, style="Compact.Treeview")
        frame.pack(fill="x")
        for s in STATES:
            self.fsm_table.insert("", "end", iid=s, values=[s] + [TRANSITIONS.get((s, e), "—")
                                                                  for e in EVENTS])

        side = Card(tab, "Student state")
        side.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(8, 16), pady=12)
        sb = side.body
        label(sb, "Choose a student of the current session", color=C["muted"], size=9).pack(anchor="w")
        self.fsm_student_var = tk.StringVar()
        self.fsm_combo = ttk.Combobox(sb, textvariable=self.fsm_student_var, state="readonly")
        self.fsm_combo.pack(fill="x", pady=(4, 10))
        self.fsm_combo.bind("<<ComboboxSelected>>", self._on_fsm_student)
        self.fsm_state_badge = Badge(sb, "NOT_MARKED", *STATE_STYLE[NOT_MARKED][:2])
        self.fsm_state_badge.pack(anchor="w")
        self.fsm_allowed = label(sb, "", size=9, color=C["muted"], anchor="w", justify="left")
        self.fsm_allowed.pack(fill="x", pady=(6, 10))
        self.fsm_allowed.bind("<Configure>", lambda e: self.fsm_allowed.configure(
            wraplength=max(150, e.width - 4)))
        label(sb, "Transition history", bold=True).pack(anchor="w")
        self.fsm_history = tk.Listbox(sb, font=(MONO, 9), relief="flat", height=8,
                                      highlightthickness=1, highlightbackground=C["border"],
                                      activestyle="none")
        self.fsm_history.pack(fill="both", expand=True, pady=(4, 0))

    def _on_fsm_student(self, _event=None):
        value = self.fsm_student_var.get()
        regno = value.split()[0] if value else None
        s = self.session
        fsm = s.machines.get(regno) if (s is not None and regno) else None
        self.fsm_history.delete(0, "end")
        if fsm is None:
            self.fsm_canvas.set_state(NOT_MARKED, None)
            self.fsm_state_badge.configure(text="NOT_MARKED", bg=STATE_STYLE[NOT_MARKED][0],
                                           fg=STATE_STYLE[NOT_MARKED][1])
            self.fsm_allowed.configure(text="Start a session to see live FSM states.")
            return
        last = fsm.history[-1] if fsm.history else None
        self.fsm_canvas.set_state(fsm.state, last)
        bg, fg, _ = STATE_STYLE[fsm.state]
        self.fsm_state_badge.configure(text=fsm.state, bg=bg, fg=fg)
        allowed = fsm.allowed_events()
        self.fsm_allowed.configure(text="Allowed events now: " + (", ".join(allowed) or "none"))
        self.fsm_history.insert("end", f"start     {NOT_MARKED}")
        for h in fsm.history:
            self.fsm_history.insert("end", f"{h.time}  {h.event} → {h.target}")
        self.fsm_table.selection_set(fsm.state)

    # ==================================================================
    # Tab 5 - Reports
    # ==================================================================
    def _build_reports_tab(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=3)
        tab.rowconfigure(2, weight=2)
        card = Card(tab, "Attendance summary (75 % rule)",
                    "Attended = Present + Late + On duty.  Excused classes are not counted.  "
                    "'Classes needed' = classes in a row to get back to 75 %.")
        card.grid(row=0, column=0, sticky="nsew", padx=16, pady=(12, 6))
        for text, style, cmd in (("Open Data Folder", "Ghost.TButton", self._open_data_folder),
                                 ("Export to Excel", "Success.TButton", self._export),
                                 ("Refresh", "Ghost.TButton", self._refresh_reports)):
            ttk.Button(card.head_right, text=text, style=style, command=cmd).pack(side="right",
                                                                               padx=(6, 0))
        cols = [("regno", "Reg No", 100, "w"), ("name", "Name", 170, "w"),
                ("held", "Held", 55, "center"), ("present", "Present", 65, "center"),
                ("late", "Late", 55, "center"), ("absent", "Absent", 65, "center"),
                ("excused", "Excused", 70, "center"), ("od", "OD", 50, "center"),
                ("pct", "Attendance %", 105, "center"), ("status", "Status", 110, "center"),
                ("need", "Classes needed", 115, "center")]
        frame, self.sum_tree = make_tree(card.body, cols, height=7)
        frame.pack(fill="both", expand=True)
        self.sum_tree.tag_configure("low", background="#fee2e2", foreground="#991b1b")
        self.sum_tree.tag_configure("ok", background="#ffffff")
        self.sum_tree.tag_configure("none", foreground=C["muted"])

        holder, self.rep_bar = info_bar(tab)
        holder.grid(row=1, column=0, sticky="ew", padx=16)

        log = Card(tab, "Rejected inputs & blocked actions  (reject_log.csv)")
        log.grid(row=2, column=0, sticky="nsew", padx=16, pady=(6, 12))
        frame, self.reject_tree = make_tree(log.body, [
            ("time", "Time", 150, "w"), ("source", "Source", 85, "w"),
            ("input", "Input", 120, "w"), ("reason", "Reason", 600, "w")], height=5)
        frame.pack(fill="both", expand=True)

    def _export(self, path=None):
        if path is None:
            path = filedialog.asksaveasfilename(
                title="Export attendance report", defaultextension=".xlsx",
                initialdir=str(self.store.dir),
                initialfile=f"attendance_report_{datetime.now():%Y%m%d}.xlsx",
                filetypes=[("Excel workbook", "*.xlsx")])
            if not path:
                return
        summaries = summarize(self.store.students, self.store.attendance_rows())
        try:
            result = export_report(path, self.store.students, self.store.attendance_rows(),
                                   summaries)
        except OSError as e:
            self.rep_bar.show("error", "Export failed",
                              f"{e}. If the file is open in Excel, close it and export again.")
            return
        self.rep_bar.show("success" if result.used_excel else "warning",
                          "Report exported" if result.used_excel else "Exported as CSV (fallback)",
                          result.message, details="\n".join(str(f) for f in result.files))

    def _open_data_folder(self):
        try:
            os.startfile(self.store.dir)  # Windows
        except AttributeError:
            self.rep_bar.show("info", "Data folder", str(self.store.dir))

    # ==================================================================
    # Refresh
    # ==================================================================
    def _refresh_students(self):
        q = self.search_entry.get().strip().lower()
        self.student_tree.delete(*self.student_tree.get_children())
        shown = 0
        for s in self.store.students.values():
            if q and q not in s.regno.lower() and q not in s.name.lower():
                continue
            self.student_tree.insert("", "end", iid=s.regno, values=(s.regno, s.name, s.added))
            shown += 1
        total = len(self.store.students)
        self.student_count.configure(
            text=f"{total} student(s) registered" + (f" · {shown} shown" if q else ""))

    def _refresh_attendance(self):
        s = self.session
        selected = self.att_tree.selection()
        self.att_tree.delete(*self.att_tree.get_children())
        for child in self.stat_frame.winfo_children():
            child.destroy()
        if s is None:
            label(self.stat_frame, "Start a session to see live FSM states", color=C["muted"],
                  size=9).pack(side="right")
            self.fsm_combo.configure(values=[])
            return
        for row in s.rows():
            self.att_tree.insert("", "end", iid=row["regno"], tags=(row["state"],), values=(
                row["regno"], row["name"], row["state"], row["marked_at"], row["last"]))
        for regno in selected:
            if regno in self.att_tree.get_children():
                self.att_tree.selection_add(regno)
        counts = s.counts()
        for state in reversed(STATES):
            bg, fg, text = STATE_STYLE[state]
            Badge(self.stat_frame, f"{text}  {counts[state]}", bg, fg).pack(side="right", padx=(6, 0))
        values = [f"{r}  ·  {n}" for r, n in s.roster.items()]
        self.fsm_combo.configure(values=values)
        if not self.fsm_student_var.get() and values:
            self.fsm_student_var.set(values[0])
        self._on_fsm_student()

    def _refresh_reports(self):
        self.sum_tree.delete(*self.sum_tree.get_children())
        for s in summarize(self.store.students, self.store.attendance_rows()):
            pct = s.percentage
            tag = "none" if pct is None else ("ok" if pct >= THRESHOLD else "low")
            self.sum_tree.insert("", "end", tags=(tag,), values=(
                s.regno, s.name, s.held, s.present, s.late, s.absent, s.excused, s.on_duty,
                "—" if pct is None else f"{pct:.1f} %", s.status,
                s.classes_needed if pct is not None and pct < THRESHOLD else "—"))
        self.reject_tree.delete(*self.reject_tree.get_children())
        for row in self.store.reject_rows()[:200]:
            self.reject_tree.insert("", "end", values=(row.get("Timestamp", ""), row.get("Source", ""),
                                                       row.get("Input", ""), row.get("Reason", "")))

    def _refresh_all(self):
        self._refresh_students()
        self._refresh_attendance()
        self._refresh_reports()
        self.status.configure(
            text=f"Data folder: {self.store.dir}     ·     {len(self.store.students)} students     ·     "
                 f"{len(self.store.session_ids())} saved session(s)     ·     DFA: "
                 f"{len(self.dfa.states)} states + dead state")

    # ==================================================================
    # Startup recovery
    # ==================================================================
    def _startup_checks(self):
        snapshot = self.store.read_snapshot()
        if self.store.issues:
            lines = []
            for i in self.store.issues:
                extra = (f" — {i.good_rows} good row(s) kept, {i.bad_rows} moved"
                         if i.bad_rows else "")
                lines.append(f"• {i.file}: {i.note}{extra}\n    backup → {i.backup}")
            self.reg_bar.show("warning", "Recovered from damaged data files",
                              "Problems were found while loading the data files and were repaired "
                              "automatically. Nothing was deleted: the damaged content was copied "
                              "to the backup file(s) below.", details="\n".join(lines))
        if snapshot:
            try:
                session = AttendanceSession.from_dict(snapshot, clock=self.clock)
            except (KeyError, ValueError, TypeError) as e:
                self.att_bar.show("warning", "Saved session could not be restored",
                                  f"The crash-recovery snapshot is damaged ({e}). It was ignored.")
                self.store.clear_snapshot()
                return
            self._offer_restore(session)

    def _offer_restore(self, s):
        marked = sum(1 for m in s.machines.values() if m.is_marked)
        started = datetime.fromtimestamp(s.started_at).strftime("%d %b %Y %H:%M:%S")
        self.nb.select(self.tab_att)
        states = "\n".join(f"{r}  {s.roster.get(r, ''):<22} {m.state}"
                           for r, m in list(s.machines.items())[:8])
        self.att_bar.show(
            "warning", "Interrupted session found",
            f"Session {s.session_id} (started {started}) was never closed — the app was closed or "
            f"crashed while attendance was running. {marked} of {len(s.machines)} students had "
            f"already been marked. Restore it to continue without losing those marks.",
            details="Saved FSM states (active_session.json):\n" + states,
            actions=[("Restore session", lambda: self._restore_session(s)),
                     ("Discard", self._discard_snapshot)])

    def _restore_session(self, s):
        self.session = s
        marked = sum(1 for m in s.machines.values() if m.is_marked)
        if s.expired:
            self._end_session(auto=True, restored=True)
            return
        self.store.write_snapshot(s)
        mm, ss = divmod(int(s.remaining()), 60)
        self.att_bar.show("success", "Session restored — no marks were lost",
                          f"{marked} mark(s) recovered from active_session.json. The timer "
                          f"continues with {mm:02d}:{ss:02d} left ({PHASE_STYLE[s.phase()][0].lower()}).")
        self._refresh_all()
        self._update_timer()

    def _discard_snapshot(self):
        self.store.clear_snapshot()
        self.att_bar.show("info", "Snapshot discarded", "The interrupted session was not restored.")


def enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def run(argv=None):
    parser = argparse.ArgumentParser(description="Student Attendance System (TOC project)")
    parser.add_argument("--data-dir", default=str(PROJECT_DIR / "data"),
                        help="folder for the CSV files (default: ./data)")
    args = parser.parse_args(argv)
    enable_dpi_awareness()
    root = tk.Tk()
    App(root, args.data_dir)
    root.mainloop()
