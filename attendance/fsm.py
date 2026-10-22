"""
Module 3 - Attendance Management using a Finite State Machine
=============================================================

Every student in a session owns one FSM. The machine is always in exactly
one state and only moves when an event arrives:

    States  S = {NOT_MARKED, PRESENT, LATE, ABSENT, EXCUSED, ON_DUTY}
    Start     = NOT_MARKED
    Events  E = {MARK_ON_TIME, MARK_LATE, TIMEOUT, EXCUSE, GRANT_OD, RESET}
    delta : S x E -> S   (partial function, see TRANSITIONS)

Design notes
------------
* NOT_MARKED is a separate start state, so "not marked yet" and "absent"
  are different states and the time-out has a real effect.
* An ON_DUTY state (VIT "OD") reached through GRANT_OD.
* RESET lets the faculty undo a wrong mark while the session is running.
* Strict machine: an undefined (state, event) pair raises InvalidTransition
  instead of being silently ignored. This is what blocks double marking.
* Every transition is recorded (history / audit trail).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

NOT_MARKED = "NOT_MARKED"
PRESENT = "PRESENT"
LATE = "LATE"
ABSENT = "ABSENT"
EXCUSED = "EXCUSED"
ON_DUTY = "ON_DUTY"
STATES = (NOT_MARKED, PRESENT, LATE, ABSENT, EXCUSED, ON_DUTY)
START_STATE = NOT_MARKED

MARK_ON_TIME = "MARK_ON_TIME"
MARK_LATE = "MARK_LATE"
TIMEOUT = "TIMEOUT"
EXCUSE = "EXCUSE"
GRANT_OD = "GRANT_OD"
RESET = "RESET"
EVENTS = (MARK_ON_TIME, MARK_LATE, TIMEOUT, EXCUSE, GRANT_OD, RESET)

# States that count as "attended" for the 75 % rule.
ATTENDED = frozenset({PRESENT, LATE, ON_DUTY})

TRANSITIONS = {
    (NOT_MARKED, MARK_ON_TIME): PRESENT,
    (NOT_MARKED, MARK_LATE): LATE,
    (NOT_MARKED, TIMEOUT): ABSENT,
    (NOT_MARKED, EXCUSE): EXCUSED,
    (NOT_MARKED, GRANT_OD): ON_DUTY,
    (LATE, EXCUSE): EXCUSED,
    (LATE, GRANT_OD): ON_DUTY,
    (ABSENT, EXCUSE): EXCUSED,
    (ABSENT, GRANT_OD): ON_DUTY,
    # admin undo (the session layer only allows it while the session runs)
    (PRESENT, RESET): NOT_MARKED,
    (LATE, RESET): NOT_MARKED,
    (EXCUSED, RESET): NOT_MARKED,
    (ON_DUTY, RESET): NOT_MARKED,
}


def allowed_events(state: str) -> list[str]:
    return [e for e in EVENTS if (state, e) in TRANSITIONS]


class InvalidTransition(Exception):
    """delta(state, event) is undefined, so the event is rejected."""

    def __init__(self, state: str, event: str):
        self.state = state
        self.event = event
        self.allowed = allowed_events(state)
        allowed = ", ".join(self.allowed) if self.allowed else "none"
        super().__init__(f"δ({state}, {event}) is not defined, so the event is rejected "
                         f"and the state stays {state}. Allowed events from {state}: {allowed}.")


@dataclass(frozen=True)
class TransitionRecord:
    time: str
    source: str
    event: str
    target: str

    def __str__(self) -> str:
        return f"{self.time}  {self.source} --{self.event}--> {self.target}"


class AttendanceFSM:
    def __init__(self, state: str = START_STATE):
        if state not in STATES:
            raise ValueError(f"Unknown state {state!r}")
        self.state = state
        self.history: list[TransitionRecord] = []

    def can_fire(self, event: str) -> bool:
        return (self.state, event) in TRANSITIONS

    def allowed_events(self) -> list[str]:
        return allowed_events(self.state)

    def fire(self, event: str, when: datetime | None = None) -> TransitionRecord:
        if event not in EVENTS:
            raise ValueError(f"Unknown event {event!r}")
        key = (self.state, event)
        if key not in TRANSITIONS:
            raise InvalidTransition(self.state, event)
        stamp = (when or datetime.now()).strftime("%H:%M:%S")
        record = TransitionRecord(stamp, self.state, event, TRANSITIONS[key])
        self.state = record.target
        self.history.append(record)
        return record

    @property
    def is_marked(self) -> bool:
        return self.state != NOT_MARKED
