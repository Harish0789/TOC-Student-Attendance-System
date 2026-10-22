"""
Module 1 - Registration Number Validation using a DFA
=====================================================

A registration number is accepted only if it belongs to the regular
language L of valid IDs. L is recognised by a deterministic finite
automaton

        M = (Q, Sigma, delta, q0, F)

Pattern compiler
----------------
The DFA is not hard-coded. It is *compiled* from one or more patterns,
so a new ID format needs no code change:

    '#'  any digit  0-9
    '@'  any letter A-Z
    anything else is a literal symbol, e.g. 2 4 B I T

    "##@@@####"  ->  any VIT number such as 24BIT0154 or 24BDE0123
    "24BIT####"  ->  only the 2024 B.Tech IT batch

Several patterns describe the union L1 U L2 U ... . Each pattern is a
chain of NFA states; the union NFA is turned into a DFA with the subset
construction (Rabin & Scott, 1959) and then minimised with Moore's
partition-refinement algorithm.

Error recovery
--------------
When the DFA rejects an input we report *where* and *why* (state, symbol,
expected symbol class) and try a phrase-level correction guided by the
DFA: remove separators, fix lowercase, and swap look-alike symbols such as
'O' -> '0' or 'S' -> '5' only when the DFA says the swap is legal.
"""

from __future__ import annotations

import string
from collections import deque
from dataclasses import dataclass, field

DIGITS = frozenset(string.digits)
LETTERS = frozenset(string.ascii_uppercase)
ALPHABET = tuple(sorted(DIGITS) + sorted(LETTERS))  # Sigma (36 symbols)
DEAD = "qd"  # dead / trap state: every missing transition goes here
DEFAULT_PATTERNS = ("##@@@####",)

SEPARATORS = set(" \t-_/.")
LOOKS_LIKE_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1",
                    "Z": "2", "S": "5", "G": "6", "T": "7", "B": "8"}
LOOKS_LIKE_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S",
                     "6": "G", "7": "T", "8": "B"}


class PatternError(ValueError):
    """Raised when an ID pattern cannot be compiled into a DFA."""


# ----------------------------------------------------------------------
# Helpers for readable symbol sets
# ----------------------------------------------------------------------
def compress(symbols) -> str:
    """'0123456789' -> '0-9'  and  'ABCDEFGHJ' -> 'A-H,J'."""
    order = [c for c in ALPHABET if c in symbols]
    parts, i = [], 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and ord(order[j + 1]) == ord(order[j]) + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{order[i]}-{order[j]}")
        else:
            parts.extend(order[i:j + 1])
        i = j + 1
    return ",".join(parts)


def edge_label(symbols) -> str:
    s = frozenset(symbols)
    if s == DIGITS:
        return "0-9"
    if s == LETTERS:
        return "A-Z"
    return compress(s)


def describe(symbols) -> str:
    """Human description of what a state expects next."""
    s = frozenset(symbols)
    if not s:
        return "nothing more (the number is complete)"
    if s == DIGITS:
        return "a digit (0-9)"
    if s == LETTERS:
        return "a letter (A-Z)"
    if s == DIGITS | LETTERS:
        return "a digit or a letter"
    if len(s) == 1:
        return f"'{next(iter(s))}'"
    return "one of " + compress(s)


def parse_pattern(pattern: str) -> list[frozenset]:
    """Turn '24BIT####' into a list with one allowed-symbol set per position."""
    pattern = pattern.strip().upper()
    if not pattern:
        raise PatternError("A pattern cannot be empty.")
    chain = []
    for pos, ch in enumerate(pattern, start=1):
        if ch == "#":
            chain.append(DIGITS)
        elif ch == "@":
            chain.append(LETTERS)
        elif ch in DIGITS or ch in LETTERS:
            chain.append(frozenset(ch))
        else:
            raise PatternError(
                f"Unsupported character '{ch}' at position {pos} of pattern "
                f"'{pattern}'. Use # for a digit, @ for a letter, or A-Z / 0-9 literals.")
    return chain


# ----------------------------------------------------------------------
# Results returned to the GUI
# ----------------------------------------------------------------------
@dataclass
class Step:
    position: int  # 0-based index of the symbol in the input
    symbol: str
    source: str
    target: str

    def __str__(self) -> str:
        return f"δ({self.source}, '{self.symbol}') = {self.target}"


@dataclass
class Trace:
    text: str
    steps: list = field(default_factory=list)
    accepted: bool = False
    final_state: str = "q0"
    error_position: int | None = None  # 0-based index of the offending symbol
    reason: str = ""

    @property
    def path(self) -> list[str]:
        if not self.steps:
            return ["q0"]
        return [self.steps[0].source] + [s.target for s in self.steps]

    def path_text(self) -> str:
        if not self.steps:
            return "q0"
        out = self.steps[0].source
        for s in self.steps:
            out += f" -{s.symbol}-> {s.target}"
        return out


@dataclass
class Suggestion:
    original: str
    corrected: str
    fixes: list = field(default_factory=list)


# ----------------------------------------------------------------------
# The DFA
# ----------------------------------------------------------------------
class RegNoDFA:
    """Table-driven DFA compiled from one or more ID patterns."""

    def __init__(self, patterns=DEFAULT_PATTERNS, minimize: bool = True):
        if isinstance(patterns, str):
            patterns = [p for p in patterns.split(",")]
        cleaned = []
        for p in patterns:
            p = p.strip().upper()
            if p and p not in cleaned:
                cleaned.append(p)
        if not cleaned:
            raise PatternError("Enter at least one pattern, for example ##@@@####.")
        chains = [parse_pattern(p) for p in cleaned]
        self.patterns = tuple(cleaned)

        states, delta, accept = _subset_construction(chains)
        self.states_before_minimization = len(states)
        if minimize:
            states, delta, accept = _minimize(states, delta, accept)
        self.states: list[str] = states  # live states, q0 first (dead state not listed)
        self.delta: dict[str, dict[str, str]] = delta
        self.accept: frozenset = accept
        self.start = "q0"

    # --- basic DFA operations -----------------------------------------
    def next_state(self, state: str, symbol: str) -> str:
        if state == DEAD:
            return DEAD
        return self.delta[state].get(symbol, DEAD)

    def expected(self, state: str) -> frozenset:
        if state == DEAD:
            return frozenset()
        return frozenset(self.delta[state])

    def distance_to_accept(self, state: str) -> int | None:
        """Fewest symbols still needed to reach a final state (BFS)."""
        if state == DEAD:
            return None
        seen, queue = {state}, deque([(state, 0)])
        while queue:
            q, d = queue.popleft()
            if q in self.accept:
                return d
            for t in set(self.delta[q].values()):
                if t not in seen:
                    seen.add(t)
                    queue.append((t, d + 1))
        return None

    def trace(self, text: str) -> Trace:
        """Run the DFA and record every transition (used by GUI and errors)."""
        tr = Trace(text=text)
        state = self.start
        if text == "":
            tr.final_state = state
            tr.reason = ("Input is empty. The DFA is still in the start state q0, "
                         "which is not a final state.")
            return tr
        for i, ch in enumerate(text):
            nxt = self.next_state(state, ch)
            tr.steps.append(Step(i, ch, state, nxt))
            if nxt == DEAD:
                tr.final_state = DEAD
                tr.error_position = i
                exp = self.expected(state)
                if not exp:
                    tr.reason = (f"Rejected at position {i + 1}: the number is already complete "
                                 f"in final state {state}, so the extra symbol '{ch}' leads to "
                                 f"the dead state {DEAD}.")
                else:
                    hint = ""
                    if ch.islower():
                        hint = " Lowercase letters are not in Σ."
                    elif ch in SEPARATORS:
                        hint = " Spaces and separators are not in Σ."
                    tr.reason = (f"Rejected at position {i + 1}: symbol '{ch}' is not allowed in "
                                 f"state {state} (expected {describe(exp)}), so the DFA moves "
                                 f"to the dead state {DEAD}.{hint}")
                return tr
            state = nxt
        tr.final_state = state
        if state in self.accept:
            tr.accepted = True
            tr.reason = f"Accepted: the run ends in final state {state} ∈ F."
        else:
            need = self.distance_to_accept(state)
            tr.reason = (f"Rejected: the input ended in state {state}, which is not a final "
                         f"state. {need} more symbol(s) needed; next expected "
                         f"{describe(self.expected(state))}.")
        return tr

    def accepts(self, text: str) -> bool:
        return self.trace(text).accepted

    validate = accepts  # alias, e.g. validate("24BIT0154") -> True

    # --- error recovery ------------------------------------------------
    def suggest(self, text: str) -> Suggestion | None:
        """Phrase-level recovery: return a corrected ID if a safe fix exists."""
        fixes = []
        cleaned = "".join(ch for ch in text if ch not in SEPARATORS)
        if cleaned != text:
            fixes.append("removed spaces / separators")
        upper = cleaned.upper()
        if upper != cleaned:
            fixes.append("converted lowercase letters to uppercase")
        state, out = self.start, []
        for i, ch in enumerate(upper):
            nxt = self.next_state(state, ch)
            if nxt == DEAD:
                for cand in (LOOKS_LIKE_DIGIT.get(ch), LOOKS_LIKE_LETTER.get(ch)):
                    if cand and self.next_state(state, cand) != DEAD:
                        fixes.append(f"position {i + 1}: '{ch}' → '{cand}' "
                                     f"(state {state} expects {describe(self.expected(state))})")
                        ch, nxt = cand, self.next_state(state, cand)
                        break
                else:
                    return None  # no safe correction exists
            out.append(ch)
            state = nxt
        corrected = "".join(out)
        if state in self.accept and corrected != text:
            return Suggestion(text, corrected, fixes)
        return None

    # --- views used by the visualizer and the report --------------------
    def edges(self) -> list[tuple[str, str, str]]:
        """(source, label, target) with symbols grouped per target state."""
        result = []
        for q in self.states:
            groups: dict[str, set] = {}
            for sym, t in self.delta[q].items():
                groups.setdefault(t, set()).add(sym)
            for t, syms in groups.items():
                result.append((q, edge_label(syms), t))
        return result

    def levels(self) -> dict[str, int]:
        """BFS depth of each state (patterns are fixed length, so M is acyclic)."""
        depth, queue = {self.start: 0}, deque([self.start])
        while queue:
            q = queue.popleft()
            for t in self.delta[q].values():
                if t not in depth:
                    depth[t] = depth[q] + 1
                    queue.append(t)
        return depth

    def transition_rows(self) -> list[tuple[str, str, str]]:
        rows = []
        for q in self.states:
            kind = []
            if q == self.start:
                kind.append("start")
            if q in self.accept:
                kind.append("final")
            moves = [f"{lbl} → {t}" for s, lbl, t in self.edges() if s == q]
            rows.append((q, ", ".join(kind) or "-", "; ".join(moves) or "(none: all → qd)"))
        rows.append((DEAD, "dead", "every symbol → qd"))
        return rows

    def formal_definition(self) -> str:
        if len(self.states) > 5:
            names = f"{self.states[0]}, {self.states[1]}, …, {self.states[-1]}"
        else:
            names = ", ".join(self.states)
        return (f"Q  = {{{names}, {DEAD}}}  ({len(self.states) + 1} states)\n"
                f"Σ  = {{0-9, A-Z}}  (36 symbols)\n"
                f"q0 = {self.start}\n"
                f"F  = {{{', '.join(sorted(self.accept, key=_state_key))}}}\n"
                f"δ  = transition table (missing entries → {DEAD})\n"
                f"L(M) = {' ∪ '.join(self.patterns)}")


def _state_key(name: str) -> int:
    return int(name[1:]) if name[1:].isdigit() else 10 ** 6


def _subset_construction(chains):
    """NFA state = (pattern index, position). DFA state = set of NFA states."""
    start = frozenset((i, 0) for i in range(len(chains)))
    names = {start: "q0"}
    order, queue = [start], deque([start])
    delta, accept = {}, set()
    while queue:
        subset = queue.popleft()
        name = names[subset]
        if any(pos == len(chains[i]) for i, pos in subset):
            accept.add(name)
        row = {}
        for sym in ALPHABET:
            target = frozenset((i, pos + 1) for i, pos in subset
                               if pos < len(chains[i]) and sym in chains[i][pos])
            if not target:
                continue  # empty set = dead state, left implicit
            if target not in names:
                names[target] = f"q{len(names)}"
                order.append(target)
                queue.append(target)
            row[sym] = names[target]
        delta[name] = row
    return [names[s] for s in order], delta, frozenset(accept)


def _minimize(states, delta, accept):
    """Moore's algorithm: split blocks until no symbol can tell states apart."""
    everything = list(states) + [DEAD]

    def step(q, a):
        return DEAD if q == DEAD else delta[q].get(a, DEAD)

    block = {q: (1 if q in accept else 0) for q in everything}
    while True:
        signatures: dict[tuple, int] = {}
        new_block = {}
        for q in everything:
            sig = (block[q],) + tuple(block[step(q, a)] for a in ALPHABET)
            new_block[q] = signatures.setdefault(sig, len(signatures))
        stable = len(signatures) == len(set(block.values()))
        block = new_block
        if stable:
            break

    dead_block = block[DEAD]
    representative = {}
    for q in everything:
        representative.setdefault(block[q], q)
    start_block = block["q0"]
    names = {start_block: "q0"}
    order, queue = [start_block], deque([start_block])
    new_delta, new_accept = {}, set()
    while queue:
        b = queue.popleft()
        q, name = representative[b], names[b]
        if q in accept:
            new_accept.add(name)
        row = {}
        for a in ALPHABET:
            t = block[step(q, a)]
            if t == dead_block:
                continue
            if t not in names:
                names[t] = f"q{len(names)}"
                order.append(t)
                queue.append(t)
            row[a] = names[t]
        new_delta[name] = row
    return [names[b] for b in order], new_delta, frozenset(new_accept)
