"""The `print` tool — ed/vim's `:p`, the read-only keyhole (v0.16).

Grammar (leading `:` optional):

  p                          current line, cursor unchanged
  :80 p   :/def load/ p      jump there (cursor MOVES), print that line
  :10,25 p                   explicit range; cursor to the last printed line
  p above|below|around COUNT window around the cursor line
  :/def load/ p around middle  address + window combined

COUNT is `tiny` (8), `middle` (25), `long` (50) or a plain integer.
above/below include the cursor line plus COUNT lines on that side;
around is COUNT lines on EACH side. Addresses are the same ex addresses
substitute uses (numbers, $, ., /pattern/, +N/-N offsets). A two-address
range takes no window word. Span capped at SPAN_CAP lines — print pages
by re-addressing, never the whole file.

Never mutates: no dirty flag, no undo entry, no staleness check.
"""

import re

from .buffer import Buffer
from .substitute import SubstituteError, _resolve_range, _split_range

CATEGORIES = {"tiny": 8, "middle": 25, "long": 50}
SPAN_CAP = 101  # = around long: 50 + cursor line + 50


class PrintError(Exception):
    """Loud, specific failure. The buffer and cursor are untouched."""


_PRINT = re.compile(r"^p(?:\s+(above|below|around)\s+(\w+))?$")

_USAGE = (
    "(supported: p | :N p | :/pat/ p | :N,M p | "
    "p above|below|around COUNT — COUNT is tiny/middle/long or a number; "
    "an address may combine with a window word, a two-address range may not)"
)


def execute(buf: Buffer, command: str) -> tuple[str, int, int]:
    """Resolve one print command; returns (header, first, last) 0-based
    inclusive. Moves the cursor only when an address is given."""
    cmd = command.strip()
    if cmd.startswith(":"):
        cmd = cmd[1:].strip()
    if not cmd:
        raise PrintError("empty command " + _USAGE)

    try:
        addrs, rest = _split_range(cmd)
    except SubstituteError as e:
        raise PrintError(str(e)) from None
    m = _PRINT.match(rest)
    if not m:
        raise PrintError(f"cannot parse {command!r} {_USAGE}")
    direction, count_word = m.groups()

    count = 0
    if direction is not None:
        if count_word in CATEGORIES:
            count = CATEGORIES[count_word]
        elif count_word.isdigit() and int(count_word) > 0:
            count = int(count_word)
        else:
            raise PrintError(
                f"bad count {count_word!r} — use tiny/middle/long or a "
                "positive number"
            )

    if addrs == ["%"] or len(addrs) == 2:
        if direction is not None:
            raise PrintError(
                "a two-address range takes no window word — "
                "use either :N,M p or :ADDR p around COUNT"
            )
        try:
            lo, hi = _resolve_range(buf, addrs)
        except SubstituteError as e:
            raise PrintError(str(e)) from None
        _check_span(lo, hi)
        buf.cursor.line = hi  # vim: cursor to the last printed line
        buf.cursor.col = 0
        return _header(buf, lo, hi), lo, hi

    if addrs:
        try:
            (line, _) = _resolve_range(buf, addrs)
        except SubstituteError as e:
            raise PrintError(str(e)) from None
        buf.cursor.line = line
        buf.cursor.col = 0

    cur = buf.cursor.line
    lo, hi = cur, cur
    if direction in ("above", "around"):
        lo = cur - count
    if direction in ("below", "around"):
        hi = cur + count
    lo, hi = max(lo, 0), min(hi, len(buf.lines) - 1)
    _check_span(lo, hi)
    return _header(buf, lo, hi), lo, hi


def _check_span(lo: int, hi: int) -> None:
    span = hi - lo + 1
    if span > SPAN_CAP:
        raise PrintError(
            f"range spans {span} lines (max {SPAN_CAP}) — print in pages: "
            "re-address from a line number in the previous print's gutter"
        )


def _header(buf: Buffer, lo: int, hi: int) -> str:
    n = len(buf.lines)
    if lo == hi:
        return f"line {lo + 1} of {n}"
    return f"lines {lo + 1}–{hi + 1} of {n}"
