"""Motion parsing and execution — v0.1 subset.

Supported: /pattern  ?pattern  n  N  :N  gg  G  f{char}  F{char}
Deferred (see design.md v0 scope): w b e 0 $ { } %

Every motion either moves the cursor and returns a status line
(e.g. "match 3 of 14") or raises MotionError without touching state.
"""

import re

from .buffer import Buffer


class MotionError(Exception):
    """Loud, specific failure. The buffer and cursor are untouched."""


def execute(buf: Buffer, command: str) -> tuple[str, bool]:
    """Apply one motion command.

    Returns (status_line, show_column) — show_column is True when the motion
    established a meaningful column (searches), so the viewport should render
    the `^` marker.
    """
    command = command.strip()
    if not command:
        raise MotionError("empty motion command")

    if command[0] in "/?":
        pattern = command[1:]
        if not pattern:
            raise MotionError("empty search pattern")
        status = _search(buf, pattern, backward=command[0] == "?")
        buf.last_search = pattern
        return status, True

    if command in ("n", "N"):
        if buf.last_search is None:
            raise MotionError("no previous search (use /pattern first)")
        status = _search(buf, buf.last_search, backward=command == "N")
        return status, True

    if command.startswith(":"):
        try:
            n = int(command[1:])
        except ValueError:
            raise MotionError(f"unknown motion: {command!r}") from None
        if not 1 <= n <= len(buf.lines):
            raise MotionError(
                f"line {n} out of range (file has {len(buf.lines)} lines)"
            )
        buf.cursor.line, buf.cursor.col = n - 1, 0
        return f"line {n}", False

    if command == "gg":
        buf.cursor.line, buf.cursor.col = 0, 0
        return "line 1", False

    if command == "G":
        buf.cursor.line, buf.cursor.col = len(buf.lines) - 1, 0
        return f"line {len(buf.lines)} (last)", False

    if command in ("f", "F"):
        raise MotionError(f"{command} needs a target character: {command}<char>")

    if len(command) == 2 and command[0] in "fF":
        target = command[1]
        line = buf.lines[buf.cursor.line]
        if command[0] == "f":
            idx = line.find(target, buf.cursor.col + 1)
            where = "after cursor"
        else:
            idx = line.rfind(target, 0, buf.cursor.col)
            where = "before cursor"
        if idx < 0:
            raise MotionError(
                f"no {target!r} {where} on line {buf.cursor.line + 1}"
            )
        buf.cursor.col = idx
        return f"column {idx + 1}", True

    raise MotionError(
        f"unknown motion: {command!r} "
        "(supported: /pattern ?pattern n N :N gg G f<char> F<char>)"
    )


def find_matches(buf: Buffer, pattern: str) -> list[tuple[int, int]]:
    """All (line, col) match positions of pattern, in file order."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise MotionError(f"bad regex {pattern!r}: {e}") from None
    return [
        (i, m.start())
        for i, line in enumerate(buf.lines)
        for m in rx.finditer(line)
    ]


def _search(buf: Buffer, pattern: str, backward: bool = False) -> str:
    """Move cursor to next match after/before it (wrapping). Returns 'match i of n'."""
    hits = find_matches(buf, pattern)
    if not hits:
        raise MotionError(f"no match: {pattern}")

    pos = (buf.cursor.line, buf.cursor.col)
    wrapped = False
    if backward:
        idx = len(hits) - 1
        candidates = [i for i, h in enumerate(hits) if h < pos]
        if candidates:
            idx = candidates[-1]
        else:
            wrapped = True
    else:
        idx = 0
        candidates = [i for i, h in enumerate(hits) if h > pos]
        if candidates:
            idx = candidates[0]
        else:
            wrapped = True

    buf.cursor.line, buf.cursor.col = hits[idx]
    status = f"match {idx + 1} of {len(hits)}"
    if wrapped:
        status += " (wrapped)"
    return status
