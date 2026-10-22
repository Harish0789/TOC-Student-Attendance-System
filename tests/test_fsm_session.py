import pytest

from attendance.fsm import (ABSENT, EXCUSE, EXCUSED, GRANT_OD, LATE, MARK_LATE, MARK_ON_TIME,
                            NOT_MARKED, ON_DUTY, PRESENT, RESET, TIMEOUT, AttendanceFSM,
                            InvalidTransition)
from attendance.session import (CLOSED, LATE_PHASE, ON_TIME, AttendanceSession, SessionClosed,
                                UnknownStudent)


class FakeClock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


# ---------------- FSM ----------------
def test_fsm_starts_not_marked():
    assert AttendanceFSM().state == NOT_MARKED


@pytest.mark.parametrize("events, final", [
    ([MARK_ON_TIME], PRESENT),
    ([MARK_LATE], LATE),
    ([TIMEOUT], ABSENT),
    ([MARK_LATE, EXCUSE], EXCUSED),
    ([TIMEOUT, GRANT_OD], ON_DUTY),
    ([MARK_ON_TIME, RESET, MARK_LATE], LATE),
])
def test_valid_event_sequences(events, final):
    fsm = AttendanceFSM()
    for e in events:
        fsm.fire(e)
    assert fsm.state == final
    assert len(fsm.history) == len(events)


def test_double_marking_is_rejected_and_state_kept():
    fsm = AttendanceFSM()
    fsm.fire(MARK_ON_TIME)
    with pytest.raises(InvalidTransition) as err:
        fsm.fire(MARK_ON_TIME)
    assert fsm.state == PRESENT
    assert err.value.allowed == [RESET]
    assert len(fsm.history) == 1


def test_unknown_event_and_state():
    with pytest.raises(ValueError):
        AttendanceFSM().fire("DANCE")
    with pytest.raises(ValueError):
        AttendanceFSM("HOLIDAY")


# ---------------- Timer & control ----------------
@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def session(clock):
    roster = {"24BIT0154": "B. Harish", "24BIT0323": "B. Abhishek", "24BIT0101": "R. Priya"}
    return AttendanceSession(roster, duration_sec=180, on_time_sec=60, clock=clock)


def test_phases_follow_the_clock(session, clock):
    assert session.phase() == ON_TIME
    clock.advance(61)
    assert session.phase() == LATE_PHASE
    clock.advance(120)
    assert session.phase() == CLOSED and session.expired


def test_mark_on_time_then_late(session, clock):
    assert session.mark("24BIT0154").target == PRESENT
    clock.advance(90)
    assert session.mark("24BIT0323").target == LATE


def test_timeout_marks_unmarked_absent(session, clock):
    session.mark("24BIT0154")
    clock.advance(200)
    records = session.close()
    assert [r for r, _ in records] == ["24BIT0323", "24BIT0101"]
    assert session.machines["24BIT0323"].state == ABSENT
    assert session.machines["24BIT0154"].state == PRESENT
    assert session.close() == []  # closing twice does nothing


def test_marking_after_close_is_refused(session, clock):
    clock.advance(500)
    with pytest.raises(SessionClosed):
        session.mark("24BIT0154")


def test_unknown_student(session):
    with pytest.raises(UnknownStudent):
        session.mark("24BIT9999")


def test_reset_only_while_running(session, clock):
    session.mark("24BIT0154")
    session.reset("24BIT0154")
    assert session.machines["24BIT0154"].state == NOT_MARKED
    session.mark("24BIT0154")
    clock.advance(500)
    session.close()
    with pytest.raises(SessionClosed):
        session.reset("24BIT0154")


def test_excuse_and_od_allowed_after_close(session, clock):
    clock.advance(500)
    session.close()
    assert session.excuse("24BIT0323").target == EXCUSED
    assert session.grant_od("24BIT0101").target == ON_DUTY


def test_snapshot_round_trip(session, clock):
    session.mark("24BIT0154")
    clock.advance(70)
    session.mark("24BIT0323")
    restored = AttendanceSession.from_dict(session.to_dict(), clock=clock)
    assert restored.session_id == session.session_id
    assert restored.machines["24BIT0154"].state == PRESENT
    assert restored.machines["24BIT0323"].state == LATE
    assert restored.machines["24BIT0101"].state == NOT_MARKED
    assert restored.machines["24BIT0323"].history[-1].event == MARK_LATE
    assert restored.phase() == LATE_PHASE


def test_invalid_timer_settings():
    with pytest.raises(ValueError):
        AttendanceSession({}, duration_sec=60, on_time_sec=120)
    with pytest.raises(ValueError):
        AttendanceSession({}, duration_sec=0, on_time_sec=0)
