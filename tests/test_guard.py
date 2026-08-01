"""The op time budget (guard.py).

The bug these pin: `re` neither checks signals nor releases the GIL while
backtracking, so a catastrophic pattern wedged the daemon until an external
`kill -9`, and no in-process timeout could have caught it. The first test
is that measurement, kept as a test so the day CPython changes it, we find
out here rather than by reasoning about it.
"""

import os
import re
import subprocess
import sys
import time

import pytest

from djinnvim import guard

# Small enough to be instant if the engine were sane, ruinous with
# backtracking: 2**40-ish steps before it can conclude "no match".
EVIL = r"(a+)+$b"
SUBJECT = "a" * 40


# Must run in its own interpreter: the runaway match starves every thread
# in the process it runs in, so doing this inline would wedge the suite -
# which is precisely the property being asserted.
_GIL_PROBE = f"""
import re, threading, time
t = threading.Thread(target=lambda: re.search({EVIL!r}, {SUBJECT!r}), daemon=True)
t.start()
start = time.monotonic()
t.join(0.5)
print(time.monotonic() - start)
"""


def test_regex_never_releases_the_gil():
    """The premise of the whole design: a watchdog *thread* cannot work,
    because the runaway match starves every other Python thread - even the
    one waiting on `join(0.5)`. If this ever fails, CPython changed and an
    in-process timeout became viable."""
    try:
        p = subprocess.run(
            [sys.executable, "-c", _GIL_PROBE],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return  # never even honored join(0.5): the starvation we design for
    waited = float(p.stdout.strip())
    pytest.fail(f"join(0.5) returned in {waited:.2f}s - the GIL was released")


def test_runaway_op_raises_optimeout_instead_of_hanging(monkeypatch):
    monkeypatch.setenv("DJINNVIM_OP_BUDGET_SECONDS", "1")
    started = time.monotonic()
    with pytest.raises(guard.OpTimeout) as e:
        guard.run_guarded("matches", re.search, EVIL, SUBJECT)
    elapsed = time.monotonic() - started
    assert elapsed < 10, f"took {elapsed:.1f}s"
    assert "runaway pattern" in str(e.value)


def test_normal_op_returns_its_value():
    assert guard.run_guarded("matches", lambda a, b: a + b, 2, 3) == 5


def test_op_exceptions_propagate_unchanged():
    def boom():
        raise ValueError("kaboom")

    with pytest.raises(ValueError, match="kaboom"):
        guard.run_guarded("matches", boom)


def test_side_effect_runs_exactly_once():
    """The oracle child repeats the op, so anything guarded must be pure.
    A guarded op therefore must not double its effects in the parent."""
    calls = []
    guard.run_guarded("matches", lambda: calls.append(1))
    assert len(calls) == 1, "the forked oracle must not leak effects back"


def test_write_is_never_forked():
    """`write` touches disk: a throwaway child must never repeat it, so it
    is excluded from PATTERN_OPS and runs inline."""
    assert "write" not in guard.PATTERN_OPS
    assert "open" not in guard.PATTERN_OPS
    calls = []
    guard.run_guarded("write", lambda: calls.append(1))
    assert len(calls) == 1


def test_budget_env_override(monkeypatch):
    monkeypatch.setenv("DJINNVIM_OP_BUDGET_SECONDS", "0.5")
    assert guard.budget() == 0.5
    monkeypatch.setenv("DJINNVIM_OP_BUDGET_SECONDS", "nonsense")
    assert guard.budget() == guard.BUDGET_DEFAULT
    monkeypatch.delenv("DJINNVIM_OP_BUDGET_SECONDS")
    assert guard.budget() == guard.BUDGET_DEFAULT


def test_budget_zero_disables_the_guard(monkeypatch):
    """Escape hatch: <= 0 runs inline, no fork, no oracle."""
    monkeypatch.setenv("DJINNVIM_OP_BUDGET_SECONDS", "0")
    calls = []
    guard.run_guarded("matches", lambda: calls.append(1))
    assert len(calls) == 1


@pytest.mark.skipif(not os.path.isdir("/proc"), reason="needs /proc")
def test_timeout_kills_the_child(monkeypatch):
    """No runaway process may survive the error: the wedge must not simply
    move from the daemon into an orphan burning a core forever."""
    monkeypatch.setenv("DJINNVIM_OP_BUDGET_SECONDS", "1")
    before = _child_pids()
    with pytest.raises(guard.OpTimeout):
        guard.run_guarded("matches", re.search, EVIL, SUBJECT)
    time.sleep(0.3)
    assert not (_child_pids() - before), "the oracle child outlived its timeout"


def _child_pids() -> set[int]:
    """Live children of this process, read straight from /proc.

    Deliberately spawns nothing: an earlier version shelled out to `pgrep`
    and kept finding *its own* helper, reporting a leak that did not exist.
    """
    me = os.getpid()
    kids = set()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            status = open(f"/proc/{entry}/status").read()
        except OSError:
            continue  # exited between listdir and open
        for line in status.splitlines():
            if line.startswith("PPid:"):
                if int(line.split()[1]) == me:
                    kids.add(int(entry))
                break
    return kids
