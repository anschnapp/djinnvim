"""One-op time budget, shared by both front ends (added 2026-08-01).

A catastrophic regex - `(a+)+$` against a long line - spins inside CPython's
regex engine, which never checks for signals *and never releases the GIL*.
Both halves matter. No signal handler runs, so SIGTERM does not land and the
daemon cannot serve `shutdown`; and no other Python thread is ever
scheduled, so a watchdog *thread* cannot fire either - measured, not
assumed: `Thread.join(2.0)` against such a pattern does not return at all.
The session wedges until an external `kill -9`.

That rules out every in-process timeout. The only executor that can still be
stopped is a separate *process*, so the guard runs the op twice:

1. In a forked child, purely as a **termination oracle** - the child's
   result is thrown away, we only ask whether it finished inside the
   budget. If it did not, the child is SIGKILLed and the caller gets a loud
   OpTimeout.
2. In the parent, for real, but only once the oracle proved this pattern
   terminates on this content.

The double run is what buys correctness without touching session internals:
`fork` gives the child a copy-on-write snapshot of the whole live Session
for free, so there is nothing to serialize and no state to merge back. The
cost is running each op twice, which for every non-pathological pattern is
microseconds against a round trip already measured in tens of milliseconds.

The win over killing the process on overrun is that buffers survive: one bad
pattern returns `error: ...` and changes nothing, which is exactly the
contract every other djinnvim failure already keeps.

Only pure in-memory, pattern-taking ops are guarded (PATTERN_OPS). `open`
and `write` take no user regex and `write` touches disk, which a throwaway
child must never do twice.
"""

import os
import signal
import time

BUDGET_DEFAULT = 10.0

# Ops that take a user-supplied regex and only touch memory: the ones that
# can run away, and the ones a discarded child can safely repeat.
PATTERN_OPS = frozenset({"motion", "edit", "substitute", "print", "matches"})


class OpTimeout(Exception):
    pass


def budget() -> float:
    """Seconds one op may take; DJINNVIM_OP_BUDGET_SECONDS overrides, and
    <= 0 disables the guard entirely (the op then runs inline, unguarded)."""
    raw = os.environ.get("DJINNVIM_OP_BUDGET_SECONDS")
    if raw is None:
        return BUDGET_DEFAULT
    try:
        return float(raw)
    except ValueError:
        return BUDGET_DEFAULT


def _terminates(fn, args, kwargs, limit: float) -> bool:
    """Does `fn` finish within `limit` seconds? Answered by a forked child
    whose output is discarded - we want the timing fact, not the value."""
    pid = os.fork()
    if pid == 0:  # child: compute, then leave without touching parent state
        try:
            fn(*args, **kwargs)
        except BaseException:
            pass  # a real error is the parent's to raise, identically
        finally:
            os._exit(0)  # never atexit/flush: the parent owns those buffers
    deadline = time.monotonic() + limit
    delay = 0.001
    while True:
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done:
            return True
        if time.monotonic() >= deadline:
            os.kill(pid, signal.SIGKILL)  # the only signal a wedged child honors
            os.waitpid(pid, 0)
            return False
        time.sleep(delay)
        delay = min(delay * 2, 0.05)  # tight at first, cheap when waiting long


def run_guarded(op: str, fn, *args, **kwargs):
    """Run one session op under the time budget. Raises OpTimeout if the op
    cannot be shown to terminate; anything `fn` raises propagates unchanged.
    """
    limit = budget()
    if limit <= 0 or op not in PATTERN_OPS or not hasattr(os, "fork"):
        return fn(*args, **kwargs)
    if not _terminates(fn, args, kwargs, limit):
        raise OpTimeout(
            f"{op} did not finish within {limit:g}s and was stopped - a "
            "runaway pattern (nested quantifiers like `(a+)+`) is the usual "
            "cause. Nothing changed; simplify the pattern and try again"
        )
    return fn(*args, **kwargs)
