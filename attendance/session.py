"""
Module 5 - Timer & Control
==========================

An attendance session is a fixed time window, split into two phases:

    0 ............ on_time ................ duration
    |  ON_TIME phase   |    LATE phase        |  CLOSED
    MARK -> MARK_ON_TIME  MARK -> MARK_LATE     TIMEOUT for everyone unmarked

The timer decides *which event* a "mark" produces; the FSM decides the
resulting state. When the window ends, every student still in NOT_MARKED
receives the TIMEOUT event and becomes ABSENT.

The clock is injectable so the timer can be tested without waiting, and the
whole session can be saved to / restored from a dict (crash recovery).
"""

from __future__ import annotations

import time
from datetime import datetime

from .fsm import (EXCUSE, GRANT_OD, MARK_LATE, MARK_ON_TIME, NOT_MARKED, RESET, STATES,
                  TIMEOUT, AttendanceFSM, TransitionRecord)

ON_TIME = "ON_TIME"
LATE_PHASE = "LATE"
CLOSED = "CLOSED"


class SessionError(Exception):
    pass


class SessionClosed(SessionError):
    pass


class UnknownStudent(SessionError):
    pass


class AttendanceSession:
    def __init__(self, roster: dict[str, str], duration_sec: float = 180,
                 on_time_sec: float = 60, clock=time.time,
                 session_id: str | None = None, started_at: float | None = None):
        if duration_sec <= 0:
            raise ValueError("Session length must be greater than zero.")
        if not 0 < on_time_sec <= duration_sec:
            raise ValueError("The on-time window must be greater than zero and not "
                             "longer than the session.")
        self.clock = clock
        self.started_at = clock() if started_at is None else started_at
        self.session_id = session_id or datetime.fromtimestamp(self.started_at).strftime(
            "S%Y%m%d-%H%M%S")
        self.duration = float(duration_sec)
        self.on_time = float(on_time_sec)
        self.roster = dict(roster)
        self.machines = {reg: AttendanceFSM() for reg in self.roster}
        self.marked_at: dict[str, str] = {}
        self.closed = False
        self.ended_at: float | None = None

    # --- timer ----------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.fromtimestamp(self.clock())

    def elapsed(self) -> float:
        end = self.ended_at if self.closed and self.ended_at else self.clock()
        return max(0.0, end - self.started_at)

    def remaining(self) -> float:
        return 0.0 if self.closed else max(0.0, self.duration - self.elapsed())

    def phase(self) -> str:
        if self.closed or self.elapsed() >= self.duration:
            return CLOSED
        return ON_TIME if self.elapsed() < self.on_time else LATE_PHASE

    @property
    def expired(self) -> bool:
        return not self.closed and self.elapsed() >= self.duration

    # --- events -----------------------------------------------------------
    def machine(self, regno: str) -> AttendanceFSM:
        if regno not in self.machines:
            raise UnknownStudent(f"{regno} is not part of session {self.session_id}.")
        return self.machines[regno]

    def add_student(self, regno: str, name: str) -> None:
        if regno not in self.machines:
            self.roster[regno] = name
            self.machines[regno] = AttendanceFSM()

    def mark(self, regno: str) -> TransitionRecord:
        """Student marks attendance; the current phase picks the event."""
        if self.phase() == CLOSED:
            raise SessionClosed("The attendance window has closed. Start a new session to mark again.")
        fsm = self.machine(regno)
        event = MARK_ON_TIME if self.phase() == ON_TIME else MARK_LATE
        record = fsm.fire(event, self._now())
        self.marked_at[regno] = record.time
        return record

    def excuse(self, regno: str) -> TransitionRecord:
        return self.machine(regno).fire(EXCUSE, self._now())

    def grant_od(self, regno: str) -> TransitionRecord:
        return self.machine(regno).fire(GRANT_OD, self._now())

    def reset(self, regno: str) -> TransitionRecord:
        if self.phase() == CLOSED:
            raise SessionClosed("RESET (undo) is only allowed while the session is running.")
        record = self.machine(regno).fire(RESET, self._now())
        self.marked_at.pop(regno, None)
        return record

    def close(self) -> list[tuple[str, TransitionRecord]]:
        """End the window: TIMEOUT moves every NOT_MARKED student to ABSENT."""
        if self.closed:
            return []
        now = self._now()
        if self.expired:  # use the exact end of the window, not the moment we noticed
            now = datetime.fromtimestamp(self.started_at + self.duration)
        records = []
        for regno, fsm in self.machines.items():
            if fsm.state == NOT_MARKED:
                records.append((regno, fsm.fire(TIMEOUT, now)))
        self.ended_at = min(self.clock(), self.started_at + self.duration)
        self.closed = True
        return records

    # --- views ------------------------------------------------------------
    def counts(self) -> dict[str, int]:
        result = {s: 0 for s in STATES}
        for fsm in self.machines.values():
            result[fsm.state] += 1
        return result

    def rows(self) -> list[dict]:
        out = []
        for regno, fsm in self.machines.items():
            last = fsm.history[-1] if fsm.history else None
            out.append({
                "regno": regno,
                "name": self.roster.get(regno, ""),
                "state": fsm.state,
                "marked_at": self.marked_at.get(regno, ""),
                "last": f"{last.source} --{last.event}--> {last.target}" if last else "",
            })
        return out

    # --- crash recovery -----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "version": 1,
            "session_id": self.session_id,
            "started_at": self.started_at,
            "duration": self.duration,
            "on_time": self.on_time,
            "roster": self.roster,
            "states": {r: m.state for r, m in self.machines.items()},
            "marked_at": self.marked_at,
            "history": {r: [[h.time, h.source, h.event, h.target] for h in m.history]
                        for r, m in self.machines.items()},
        }

    @classmethod
    def from_dict(cls, data: dict, clock=time.time) -> "AttendanceSession":
        session = cls(data["roster"], data["duration"], data["on_time"], clock,
                      data["session_id"], data["started_at"])
        for regno, state in data["states"].items():
            if regno in session.machines:
                if state not in STATES:
                    raise ValueError(f"Unknown state {state!r} in saved session")
                session.machines[regno].state = state
                session.machines[regno].history = [
                    TransitionRecord(*h) for h in data.get("history", {}).get(regno, [])]
        session.marked_at = dict(data.get("marked_at", {}))
        return session
