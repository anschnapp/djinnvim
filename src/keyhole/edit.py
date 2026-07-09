"""Edit command parsing and execution — v0 subset.

Anchored form (preferred): `at /pattern/ <command>` — search, then apply.
Optional ordinal: `at 2nd /pattern/ <command>` (2nd match after cursor).

Commands: ciw caw  ci( ci{ ci[ ci" ci'  (+ di/da variants)  diw
          dd  cc  o O  A I  D C  x r
Deferred: cs/ds/ysiw (surround), `.` repeat, cit/dit, dap, J, >> <<

Every edit returns (summary, affected_first, affected_last) so the server
can render the post-edit viewport. Failures raise EditError loudly and
never modify the buffer or move the cursor.
"""

import re

from . import motion
from .buffer import Buffer


class EditError(Exception):
    """Loud, specific failure (e.g. 'no enclosing ( on line 80')."""


_ANCHOR = re.compile(r"^at\s+(?:(\d+)(?:st|nd|rd|th)\s+)?/((?:\\.|[^/])*)/\s*")
_OBJECT_CMD = re.compile(r"^([cd])([ia])([wW(){}\[\]\"'`])(?:\s(.*))?$", re.DOTALL)
_INSERT_CMD = re.compile(r"^(cc|C|o|O|A|I)(?:\s(.*))?$", re.DOTALL)

_BRACKETS = {"(": "()", ")": "()", "{": "{}", "}": "{}", "[": "[]", "]": "[]"}


def execute(buf: Buffer, command: str) -> tuple[str, int, int]:
    """Apply one edit command; return (summary, first_line, last_line) 0-based."""
    # Trailing spaces are preserved: TEXT like `I # ` keeps its trailing space.
    command = command.lstrip().rstrip("\n")
    saved = (buf.cursor.line, buf.cursor.col)

    m = _ANCHOR.match(command)
    if m:
        ordinal = int(m.group(1) or 1)
        pattern = m.group(2)
        rest = command[m.end():]
        if not rest:
            raise EditError("anchored form needs a command: at /pattern/ <cmd>")
        try:
            hits = motion.find_matches(buf, pattern)
        except motion.MotionError as e:
            raise EditError(str(e)) from None
        if not hits:
            raise EditError(f"no match: {pattern}")
        if ordinal > len(hits):
            raise EditError(f"asked for match {ordinal} but only {len(hits)} match(es)")
        # Nth match strictly after the cursor, wrapping like search.
        after = [i for i, h in enumerate(hits) if h > saved]
        start = after[0] if after else 0
        buf.cursor.line, buf.cursor.col = hits[(start + ordinal - 1) % len(hits)]
        command = rest

    try:
        result = _apply(buf, command)
    except EditError:
        buf.cursor.line, buf.cursor.col = saved
        raise
    buf.dirty = True
    return result


def _apply(buf: Buffer, cmd: str) -> tuple[str, int, int]:
    i = buf.cursor.line
    line = buf.lines[i]
    col = buf.cursor.col
    bare = cmd.strip()

    if bare == "dd":
        del buf.lines[i]
        if not buf.lines:
            buf.lines = [""]
        buf.cursor.line = min(i, len(buf.lines) - 1)
        buf.cursor.col = 0
        return f"deleted line {i + 1}", buf.cursor.line, buf.cursor.line

    if bare == "x":
        if col >= len(line):
            raise EditError(f"no character under cursor (line {i + 1}, col {col + 1})")
        buf.lines[i] = line[:col] + line[col + 1:]
        buf.cursor.col = min(col, max(len(buf.lines[i]) - 1, 0))
        return f"deleted char on line {i + 1}", i, i

    if (len(cmd) == 2 and cmd[0] == "r") or (len(bare) == 2 and bare[0] == "r"):
        char = cmd[1] if len(cmd) == 2 else bare[1]
        if col >= len(line):
            raise EditError(f"no character under cursor (line {i + 1}, col {col + 1})")
        buf.lines[i] = line[:col] + char + line[col + 1:]
        return f"replaced char on line {i + 1}", i, i

    if bare == "D":
        buf.lines[i] = line[:col]
        buf.cursor.col = max(len(buf.lines[i]) - 1, 0)
        return f"deleted to end of line {i + 1}", i, i

    m = _INSERT_CMD.match(cmd)
    if m:
        op, text = m.group(1), m.group(2)
        if not text:
            if op in ("C", "A", "I"):
                raise EditError(f"{op} needs TEXT: `{op} <text>`")
            text = ""  # bare o/O/cc: insert/leave an empty line
        parts = text.split("\n")

        if op == "cc":
            buf.lines[i:i + 1] = parts
            buf.cursor.line, buf.cursor.col = i, 0
            last = i + len(parts) - 1
            what = f"line {i + 1}" if len(parts) == 1 else f"lines {i + 1}–{last + 1}"
            return f"replaced line {i + 1} with {what}", i, last

        if op == "C":
            return _splice(buf, i, col, len(line), text)

        if op == "o":
            buf.lines[i + 1:i + 1] = parts
            buf.cursor.line, buf.cursor.col = i + len(parts), 0
            return (
                f"inserted {len(parts)} line(s) below line {i + 1}",
                i + 1,
                i + len(parts),
            )

        if op == "O":
            buf.lines[i:i] = parts
            buf.cursor.line, buf.cursor.col = i + len(parts) - 1, 0
            return f"inserted {len(parts)} line(s) above line {i + 1}", i, i + len(parts) - 1

        if op == "A":
            return _splice(buf, i, len(line), len(line), text)

        if op == "I":
            indent = len(line) - len(line.lstrip())
            return _splice(buf, i, indent, indent, text)

    m = _OBJECT_CMD.match(cmd)
    if m:
        op, scope, obj, text = m.groups()
        if op == "c" and not text:
            raise EditError(
                f"c{scope}{obj} needs TEXT: `c{scope}{obj} <text>` "
                f"(use d{scope}{obj} to delete)"
            )
        if op == "d" and text and text.strip():
            raise EditError(f"d{scope}{obj} takes no TEXT (use c{scope}{obj} to change)")
        start, end = find_object(line, col, obj, around=scope == "a")
        return _splice(buf, i, start, end, text or "")

    raise EditError(
        f"unknown edit command: {cmd!r} "
        "(v0 supports ciw/caw ci(/{{/[/\"/' di/da-variants dd cc D C x r o O A I)"
    )


def _splice(buf: Buffer, i: int, start: int, end: int, text: str) -> tuple[str, int, int]:
    """Replace cols [start, end) of line i with text (may be multi-line)."""
    line = buf.lines[i]
    buf.lines[i:i + 1] = (line[:start] + text + line[end:]).split("\n")
    buf.cursor.line, buf.cursor.col = i, start
    last = i + text.count("\n")
    verb = "deleted from" if text == "" and end > start else "changed"
    if last == i:
        return f"{verb} line {i + 1}", i, i
    return f"changed lines {i + 1}–{last + 1}", i, last


def find_object(line: str, col: int, obj: str, around: bool) -> tuple[int, int]:
    """Resolve a text object on a single line to a (start, end) column span,
    end-exclusive.

    v0 objects: w  ( ) { } [ ] " ' `   — brackets resolved by enclosing-pair
    scan from the cursor, quotes by pairing quote chars left to right.
    Raises EditError if unresolvable.
    """
    if obj in ("w", "W"):
        return _word_span(line, col, around)
    if obj in _BRACKETS:
        oc, cc_ = _BRACKETS[obj]
        a, b = _bracket_span(line, col, oc, cc_)
        return (a, b + 1) if around else (a + 1, b)
    if obj in "\"'`":
        a, b = _quote_span(line, col, obj)
        return (a, b + 1) if around else (a + 1, b)
    raise EditError(f"unsupported text object: {obj!r}")


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _word_span(line: str, col: int, around: bool) -> tuple[int, int]:
    if col >= len(line) or not _is_word(line[col]):
        raise EditError(f"no word under cursor at column {col + 1}")
    start, end = col, col + 1
    while start > 0 and _is_word(line[start - 1]):
        start -= 1
    while end < len(line) and _is_word(line[end]):
        end += 1
    if around:
        trail = end
        while trail < len(line) and line[trail] == " ":
            trail += 1
        if trail > end:
            end = trail
        else:
            while start > 0 and line[start - 1] == " ":
                start -= 1
    return start, end


def _bracket_span(line: str, col: int, oc: str, cc_: str) -> tuple[int, int]:
    """Innermost pair enclosing the cursor (cursor on a delimiter counts as inside)."""
    n = len(line)
    if col < n and line[col] == oc:
        start = col
    else:
        depth = 0
        start = -1
        for i in range(min(col, n - 1), -1, -1):
            ch = line[i]
            if ch == cc_ and i != col:
                depth += 1
            elif ch == oc:
                if depth == 0:
                    start = i
                    break
                depth -= 1
        if start < 0:
            raise EditError(f"no enclosing {oc} on line")
    depth = 0
    for j in range(start, n):
        if line[j] == oc:
            depth += 1
        elif line[j] == cc_:
            depth -= 1
            if depth == 0:
                return start, j
    raise EditError(f"unmatched {oc} on line")


def _quote_span(line: str, col: int, q: str) -> tuple[int, int]:
    """Pair enclosing the cursor if any, else the next pair after it."""
    positions = []
    i = 0
    while i < len(line):
        if line[i] == "\\":
            i += 2
            continue
        if line[i] == q:
            positions.append(i)
        i += 1
    pairs = list(zip(positions[0::2], positions[1::2]))
    for a, b in pairs:
        if a <= col <= b:
            return a, b
    for a, b in pairs:
        if a > col:
            return a, b
    raise EditError(f"no {q}...{q} pair on line")
