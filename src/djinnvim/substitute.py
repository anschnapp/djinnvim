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

Registers (visible state: every yank/cut echoes name + content; the model
never reproduces the text — put pastes the authoritative copy):

  :RANGE y NAME              yank range into register NAME
  :RANGE d NAME              cut: delete range into register NAME
  :RANGE d                   plain delete — never touches a register, so a
                             cleanup mid-move can't clobber the block carried
  :y                         bare yank: cursor line into the unnamed register
  :put NAME  /  :put         insert register contents below the cursor line
                             (no range; position with motion first)

Flags: g (all occurrences per line), i (ignore case).
Replacement uses Python re syntax (\\1 for groups, not vim's \\r).

Output is a count plus a compact diff of changed lines — never the file.
Failures raise SubstituteError loudly; the buffer and cursor are untouched.
"""

import re

from .buffer import Buffer
from .viewport import render

DIFF_CAP = 60   # beyond this many changed lines, elide the middle
DIFF_EDGE = 5   # lines shown at each end when capped
PREVIEW_EDGE = 3      # register previews: lines shown at each end when elided
PREVIEW_LINE_CAP = 120  # register previews: max chars per line


class SubstituteError(Exception):
    """Loud, specific failure. The buffer and cursor are untouched."""


_PATTERN = r"((?:\\.|[^/])*)"
_GLOBAL_DELETE = re.compile(rf"^g/{_PATTERN}/d$")
_SUBST = re.compile(rf"^s/{_PATTERN}/{_PATTERN}/([gi]*)$")
_ADDR = re.compile(rf"^(\d+|\$|\.|/{_PATTERN}/)")
_REGISTER_OP = re.compile(r"^(y|d|put)(?:\s+(\w+))?$")


def execute(
    buf: Buffer, command: str, registers: dict[str, list[str]] | None = None
) -> str:
    """Apply one ex command; return the report (count + compact diff)."""
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
        if op == "put":
            if range_part:
                raise SubstituteError(
                    "put takes no range — position the cursor with motion first"
                )
            return _put(buf, name, registers)
        start, end = _resolve_range(buf, range_part)
        if op == "y":
            return _yank(buf, start, end, name, registers)
        return _range_delete(buf, start, end, name, registers)

    raise SubstituteError(
        f"cannot parse {command!r} "
        "(supported: :%s/old/new/g  :N,Ms/old/new/  :/pat/,/pat/s/old/new/  "
        ":g/pat/d  :N,My NAME  :N,Md NAME  :N,Md  :put NAME)"
    )


def _split_range(cmd: str) -> tuple[str, str]:
    """Split '10,40s/a/b/' into ('10,40', 's/a/b/'). Range may be empty or %."""
    if cmd.startswith("%"):
        return "%", cmd[1:]
    addrs = []
    rest = cmd
    m = _ADDR.match(rest)
    if m:
        addrs.append(m.group(1))
        rest = rest[m.end():]
        if rest.startswith(","):
            m = _ADDR.match(rest[1:])
            if not m:
                raise SubstituteError(f"bad range address after ',' in {cmd!r}")
            addrs.append(m.group(1))
            rest = rest[1 + m.end():]
    return ",".join(addrs), rest


def _resolve_range(buf: Buffer, range_part: str) -> tuple[int, int]:
    """Resolve a range to 0-based inclusive (start, end) line indices."""
    if range_part == "%":
        return 0, len(buf.lines) - 1
    if not range_part:
        return buf.cursor.line, buf.cursor.line
    addrs = range_part.split(",", 1)
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
    if addr == "$":
        return len(buf.lines) - 1
    if addr == ".":
        return buf.cursor.line
    if addr.startswith("/"):
        pattern = addr[1:-1]
        rx = _compile(pattern, "")
        n = len(buf.lines)
        for off in range(n):
            i = (search_from + off) % n
            if rx.search(buf.lines[i]):
                return i
        raise SubstituteError(f"no line matches address /{pattern}/")
    n = int(addr)
    if not 1 <= n <= len(buf.lines):
        raise SubstituteError(
            f"line {n} out of range (file has {len(buf.lines)} lines)"
        )
    return n - 1


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
    new = new.replace(r"\/", "/")

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


def _display(name: str | None) -> str:
    return f'register "{name}"' if name else "the unnamed register"


def _yank(
    buf: Buffer, start: int, end: int, name: str | None,
    registers: dict[str, list[str]],
) -> str:
    lines = list(buf.lines[start:end + 1])
    registers[name or ""] = lines
    head = f"yanked {len(lines)} line(s) ({start + 1}–{end + 1}) into {_display(name)}"
    return head + "\n" + _preview(lines)


def _range_delete(
    buf: Buffer, start: int, end: int, name: str | None,
    registers: dict[str, list[str]],
) -> str:
    lines = list(buf.lines[start:end + 1])
    if name is not None:
        registers[name] = lines
    buf.lines = buf.lines[:start] + buf.lines[end + 1:]
    if not buf.lines:
        buf.lines = [""]
    buf.cursor.line = min(start, len(buf.lines) - 1)
    buf.cursor.col = 0
    buf.dirty = True

    span = f"{len(lines)} line(s) ({start + 1}–{end + 1})"
    if name is not None:
        head = f"cut {span} into {_display(name)}"
    else:
        head = f"deleted {span} — not saved to a register"
    return head + "\n" + _preview(lines)


def _put(buf: Buffer, name: str | None, registers: dict[str, list[str]]) -> str:
    key = name or ""
    if key not in registers:
        raise SubstituteError(_missing_register(name, registers))
    lines = registers[key]
    at = buf.cursor.line
    buf.lines[at + 1:at + 1] = list(lines)
    first, last = at + 1, at + len(lines)
    buf.cursor.line = last
    buf.cursor.col = 0
    buf.dirty = True

    head = f"put {len(lines)} line(s) from {_display(name)} below line {at + 1}"
    return head + "\n" + render(buf, first=first, last=last)


def _missing_register(name: str | None, registers: dict[str, list[str]]) -> str:
    what = (
        f'no register "{name}"' if name
        else "unnamed register is empty (nothing yanked yet)"
    )
    if not registers:
        return (
            what + " — no registers set; yank with :N,My NAME "
            "or cut with :N,Md NAME"
        )
    out = [what + " — available registers:"]
    for key, lines in registers.items():
        label = f'"{key}"' if key else "(unnamed)"
        tail = "" if len(lines) == 1 else f" ... ({len(lines)} lines)"
        out.append(f"  {label}: {_clip(lines[0])}{tail}")
    return "\n".join(out)


def _clip(line: str) -> str:
    return line if len(line) <= PREVIEW_LINE_CAP else line[:PREVIEW_LINE_CAP] + "…"


def _preview(lines: list[str]) -> str:
    """Stripped register-content echo: short blocks in full, long ones
    first/last PREVIEW_EDGE with an elision marker."""
    if len(lines) <= 2 * PREVIEW_EDGE + 1:
        shown = [f"  {_clip(l)}" for l in lines]
    else:
        shown = [f"  {_clip(l)}" for l in lines[:PREVIEW_EDGE]]
        shown.append(f"  ... {len(lines) - 2 * PREVIEW_EDGE} more line(s) ...")
        shown.extend(f"  {_clip(l)}" for l in lines[-PREVIEW_EDGE:])
    return "\n".join(shown)


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
