import pytest

from attendance.dfa import DEAD, PatternError, RegNoDFA


@pytest.fixture
def dfa():
    return RegNoDFA()  # default pattern ##@@@####


@pytest.mark.parametrize("text", ["24BIT0154", "24BIT0323", "24BDE0123", "24BYB0143", "23BCE9999"])
def test_accepts_valid_vit_numbers(dfa, text):
    assert dfa.accepts(text)
    assert dfa.trace(text).final_state == "q9"


@pytest.mark.parametrize("text", ["", "444", "24BIT99", "ABCDEFG", "24BIT01540", "24bit0154",
                                  "24BIT 0154", "2BIT01544"])
def test_rejects_invalid_numbers(dfa, text):
    assert not dfa.accepts(text)


def test_single_batch_pattern():
    """A literal pattern such as 24BIT#### accepts only that batch."""
    old = RegNoDFA(["24BIT####"])
    assert old.validate("24BIT0154")
    assert old.validate("24BIT0323")
    assert not old.validate("24BDE0123")
    assert not old.validate("24BIT99")


def test_trace_reports_position_state_and_expected_symbol(dfa):
    tr = dfa.trace("24B1T0154")
    assert not tr.accepted
    assert tr.final_state == DEAD
    assert tr.error_position == 3
    assert "position 4" in tr.reason and "q3" in tr.reason and "letter" in tr.reason
    assert tr.path == ["q0", "q1", "q2", "q3", DEAD]


def test_trace_for_too_short_input(dfa):
    tr = dfa.trace("24BIT99")
    assert tr.final_state == "q7"
    assert "2 more symbol(s)" in tr.reason


def test_trace_for_too_long_input(dfa):
    tr = dfa.trace("24BIT01540")
    assert tr.error_position == 9
    assert "already complete" in tr.reason


@pytest.mark.parametrize("raw, fixed", [
    ("24bit0154", "24BIT0154"),        # lowercase
    ("24-BIT-0154", "24BIT0154"),      # separators
    ("24bit 03S7", "24BIT0357"),       # space + lowercase + S->5
    ("24B1T0154", "24BIT0154"),        # 1->I in a letter position
    ("24BIT0O54", "24BIT0054"),        # O->0 in a digit position
])
def test_suggestion_recovers_common_typos(dfa, raw, fixed):
    s = dfa.suggest(raw)
    assert s is not None and s.corrected == fixed
    assert dfa.accepts(s.corrected)


@pytest.mark.parametrize("raw", ["444", "24BIT99", "hello", "24BIT0154"])
def test_no_suggestion_when_no_safe_fix(dfa, raw):
    assert dfa.suggest(raw) is None


def test_multi_pattern_union_is_minimised():
    m = RegNoDFA(["24BIT####", "24BDE####", "23BIT####"])
    for ok in ("24BIT0154", "24BDE0123", "23BIT0001"):
        assert m.accepts(ok)
    for bad in ("23BDE0123", "24BYB0143", "24BIT015"):
        assert not m.accepts(bad)
    assert len(m.states) < m.states_before_minimization


def test_minimisation_keeps_language(dfa):
    raw = RegNoDFA(["24BIT####", "24BDE####"], minimize=False)
    small = RegNoDFA(["24BIT####", "24BDE####"])
    for text in ("24BIT0154", "24BDE0123", "24BIX0154", "24BIT01", "", "24BDE01234"):
        assert raw.accepts(text) == small.accepts(text)


def test_single_pattern_is_already_minimal(dfa):
    assert len(dfa.states) == 10
    assert dfa.accept == frozenset({"q9"})


@pytest.mark.parametrize("bad", ["", "   ", "24BIT##?#", "24-BIT"])
def test_bad_patterns_raise(bad):
    with pytest.raises(PatternError):
        RegNoDFA([bad])


def test_transition_table_and_definition(dfa):
    rows = dfa.transition_rows()
    assert rows[0] == ("q0", "start", "0-9 → q1")
    assert rows[-1][0] == DEAD
    assert "F  = {q9}" in dfa.formal_definition()
