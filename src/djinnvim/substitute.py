"""Ex-style commands — substitution plus registers (yank / cut / put).

Supported forms (leading `:` optional):

  :%s/old/new/g              whole file
  :s/old/new/                cursor line only
  :10,40s/foo/bar/           line range (1-based, inclusive)
  :/def parse/,/^$/s/x/y/g   pattern range: start = first line matching the
                             first pattern at/after the cursor (wrapping),
                             end = first line matching the second pattern
                             after the start line
  :g/DEBUG/d                 delete every matching line

Any address takes a vim-style offset: `/^def /-1` (line before the next
def), `$-1`, `10+2`. Both range addresses are INCLUSIVE, so `-1` on the
end address is the idiom for "up to but not including" — e.g. cut a whole
function without grabbing the next def line:
`:/def helper/,/^def /-1d fn`.

Ex-range register fallback (the normal-mode surface in edit.py — yy,
"name yap, "name dd, p/P — is primary; these ranges cover pattern-bounded
blocks that text objects can't select, e.g. a Python function with internal
blank lines; paste back with p/P in edit):

  :RANGE y NAME              yank range into register NAME
  :RANGE d NAME              cut: delete range into register NAME
  :RANGE d                   plain delete — never touches a register, so a
                             cleanup mid-move can't clobber the block carried
  :y                         bare yank: cursor line into the unnamed register

Flags: g (all occurrences per line), i (ignore case).
Replacement uses Python re syntax (\\1 for groups, not vim's \\r); a
backslash before punctuation is that literal char, vim-style (\\( -> ().

Output is a count plus a compact diff of changed lines — never the file.
Failures raise SubstituteError loudly; the buffer and cursor are untouched.
"""

import re

from .buffer import Buffer
from .registers import Register, display, preview

DIFF_CAP = 60   # beyond this many changed lines, elide the middle
DIFF_EDGE = 5   # lines shown at each end when capped


class SubstituteError(Exception):
    """Loud, specific failure. The buffer and cursor are untouched."""


_PATTERN = r"((?:\\.|[^/])*)"
_GLOBAL_DELETE = re.compile(rf"^g/{_PATTERN}/d$")
_SUBST = re.compile(rf"^s/{_PATTERN}/{_PATTERN}/([gi]*)$")
_ADDR = re.compile(rf"^(?:\d+|\$|\.|/{_PATTERN}/)(?:[+-]\d+)?")
_OFFSET = re.compile(r"([+-]\d+)$")
_REGISTER_OP = re.compile(r"^(y|d)(?:\s+(\w+))?$")


def execute(
    buf: Buffer, command: str, registers: dict[str, Register] | None = None
) -> str:
    """Apply one ex command; return the report (count + compact diff)."""
    pre_lines = list(buf.lines)
    pre_cursor = (buf.cursor.line, buf.cursor.col)
    report = _run(buf, command, registers)
    if buf.lines != pre_lines:  # yanks don't mutate and push nothing
        buf.push_undo(pre_lines, pre_cursor, command.strip())
    return report


def _run(
    buf: Buffer, command: str, registers: dict[str, Register] | None
) -> str:
    cmd = command.strip()
    if cmd.startswith(":"):
        cmd = cmd[1:]
    if not cmd:
        raise SubstituteError("empty command")

    m = _GLOBAL_DELETE.match(cmd)
    if m:
        return _global_delete(buf, m.group(1))

    range_part, s_part = _split_range(cmd)
    m = _SUBST.match(s_part)
    if m:
        old, new, flags = m.groups()
        start, end = _resolve_range(buf, range_part)
        return _substitute(buf, old, new, flags, start, end)

    m = _REGISTER_OP.match(s_part)
    if m:
        op, name = m.groups()
        if registers is None:
            registers = {}
        start, end = _resolve_range(buf, range_part)
        if op == "y":
            return _yank(buf, start, end, name, registers)
        return _range_delete(buf, start, end, name, registers)

    raise SubstituteError(
        f"cannot parse {command!r} "
        "(supported: :%s/old/new/g  :N,Ms/old/new/  :/pat/,/pat/s/old/new/  "
        ":g/pat/d  :N,My NAME  :N,Md NAME  :N,Md — paste with p/P in edit; "
        "addresses take +N/-N offsets, e.g. :/def a/,/^def /-1d fn)"
    )


def _split_range(cmd: str) -> tuple[list[str], str]:
    """Split '10,40s/a/b/' into (['10', '40'], 's/a/b/'). ['%'] for a % range."""
    if cmd.startswith("%"):
        return ["%"], cmd[1:]
    addrs = []
    rest = cmd
    m = _ADDR.match(rest)
    if m:
        addrs.append(m.group(0))
        rest = rest[m.end():]
        if rest.startswith(","):
            m = _ADDR.match(rest[1:])
            if not m:
                raise SubstituteError(f"bad range address after ',' in {cmd!r}")
            addrs.append(m.group(0))
            rest = rest[1 + m.end():]
    return addrs, rest.lstrip()


def _resolve_range(buf: Buffer, addrs: list[str]) -> tuple[int, int]:
    """Resolve a range to 0-based inclusive (start, end) line indices."""
    if addrs == ["%"]:
        return 0, len(buf.lines) - 1
    if not addrs:
        return buf.cursor.line, buf.cursor.line
    start = _resolve_addr(buf, addrs[0], search_from=buf.cursor.line)
    if len(addrs) == 1:
        return start, start
    end = _resolve_addr(buf, addrs[1], search_from=start + 1)
    if end < start:
        raise SubstituteError(
            f"backwards range: line {start + 1} to line {end + 1}"
        )
    return start, end


def _resolve_addr(buf: Buffer, addr: str, search_from: int) -> int:
    full = addr
    offset = 0
    m = _OFFSET.search(addr)
    if m:
        offset = int(m.group(1))
        addr = addr[: m.start()]
    if addr == "$":
        i = len(buf.lines) - 1
    elif addr == ".":
        i = buf.cursor.line
    elif addr.startswith("/"):
        pattern = addr[1:-1]
        rx = _compile(pattern, "")
        n = len(buf.lines)
        for off in range(n):
            i = (search_from + off) % n
            if rx.search(buf.lines[i]):
                break
        else:
            raise SubstituteError(f"no line matches address /{pattern}/")
    else:
        n = int(addr)
        if not 1 <= n <= len(buf.lines):
            raise SubstituteError(
                f"line {n} out of range (file has {len(buf.lines)} lines)"
            )
        i = n - 1
    i += offset
    if not 0 <= i < len(buf.lines):
        raise SubstituteError(
            f"address {full} resolves to line {i + 1} "
            f"(file has {len(buf.lines)} lines)"
        )
    return i


def _unescape_replacement(new: str) -> str:
    """Vim/sed treat a backslash before punctuation in the REPLACEMENT as that
    literal char (`load\(x\)` -> `load(x)`); Python's re keeps the backslash,
    silently corrupting the file. Unescape punctuation; leave group refs
    (\\1, \\g<..>), letter escapes (\\n, \\t) and \\\\ for re to handle."""
    out = []
    i = 0
    while i < len(new):
        ch = new[i]
        if ch == "\\" and i + 1 < len(new):
            nxt = new[i + 1]
            if not nxt.isalnum() and nxt != "\\":
                out.append(nxt)  # \( -> (
            else:
                out.append(ch)
                out.append(nxt)  # \1, \g, \n, \\ pass through to re
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _compile(pattern: str, flags: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.IGNORECASE if "i" in flags else 0)
    except re.error as e:
        raise SubstituteError(f"bad regex {pattern!r}: {e}") from None


def _substitute(
    buf: Buffer, old: str, new: str, flags: str, start: int, end: int
) -> str:
    rx = _compile(old, flags)
    count = 0 if "g" in flags else 1
    new = _unescape_replacement(new)

    total = 0
    changed: list[tuple[int, str, str]] = []  # (old line no 0-based, old, new)
    new_lines: list[str] = list(buf.lines[:start])
    for i in range(start, end + 1):
        line = buf.lines[i]
        try:
            replaced, n = rx.subn(new, line, count=count)
        except re.error as e:
            raise SubstituteError(f"bad replacement {new!r}: {e}") from None
        if n:
            total += n
            changed.append((i, line, replaced))
            new_lines.extend(replaced.split("\n"))
        else:
            new_lines.append(line)
    if total == 0:
        where = (
            "in file" if (start, end) == (0, len(buf.lines) - 1)
            else f"in lines {start + 1}–{end + 1}"
        )
        raise SubstituteError(f"pattern matched 0 times {where}: {old}")
    new_lines.extend(buf.lines[end + 1:])

    buf.lines = new_lines
    buf.cursor.line = min(changed[-1][0], len(buf.lines) - 1)
    buf.cursor.col = 0
    buf.dirty = True

    head = f"{total} substitution(s) on {len(changed)} line(s)"
    return head + "\n" + _diff(changed)


def _global_delete(buf: Buffer, pattern: str) -> str:
    rx = _compile(pattern, "")
    doomed = [(i, line, None) for i, line in enumerate(buf.lines) if rx.search(line)]
    if not doomed:
        raise SubstituteError(f"pattern matched 0 lines: {pattern}")

    buf.lines = [line for i, line in enumerate(buf.lines) if not rx.search(line)]
    if not buf.lines:
        buf.lines = [""]
    buf.cursor.line = min(doomed[0][0], len(buf.lines) - 1)
    buf.cursor.col = 0
    buf.dirty = True

    head = f"deleted {len(doomed)} line(s)"
    return head + "\n" + _diff(doomed)


def _yank(
    buf: Buffer, start: int, end: int, name: str | None,
    registers: dict[str, Register],
) -> str:
    lines = list(buf.lines[start:end + 1])
    registers[name or ""] = Register(lines, linewise=True)
    head = f"yanked {len(lines)} line(s) ({start + 1}–{end + 1}) into {display(name)}"
    return head + "\n" + preview(lines)


def _range_delete(
    buf: Buffer, start: int, end: int, name: str | None,
    registers: dict[str, Register],
) -> str:
    lines = list(buf.lines[start:end + 1])
    if name is not None:
        registers[name] = Register(lines, linewise=True)
    buf.lines = buf.lines[:start] + buf.lines[end + 1:]
    if not buf.lines:
        buf.lines = [""]
    buf.cursor.line = min(start, len(buf.lines) - 1)
    buf.cursor.col = 0
    buf.dirty = True

    span = f"{len(lines)} line(s) ({start + 1}–{end + 1})"
    if name is not None:
        head = f"cut {span} into {display(name)}"
    else:
        head = f"deleted {span} — not saved to a register"
    return head + "\n" + preview(lines)


def _diff(changed: list[tuple[int, str, str | None]]) -> str:
    """Compact diff of changed lines only. Line numbers are pre-edit, 1-based.
    Capped: beyond DIFF_CAP changed lines, show the first/last DIFF_EDGE."""
    if len(changed) > DIFF_CAP:
        shown = changed[:DIFF_EDGE] + changed[-DIFF_EDGE:]
        elided = len(changed) - 2 * DIFF_EDGE
    else:
        shown, elided = changed, 0

    width = len(str(shown[-1][0] + 1))
    out = []
    for k, (i, old, new) in enumerate(shown):
        if elided and k == DIFF_EDGE:
            out.append(f"... {elided} more changed line(s) — use matches to inspect ...")
        out.append(f"- {i + 1:>{width}}  {old}")
        if new is not None:
            out.append(f"+ {i + 1:>{width}}  {new}")
    return "\n".join(out)
