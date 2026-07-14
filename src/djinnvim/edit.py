"""Edit command parsing and execution — v0.1 subset + v0.3 registers.

Anchored form (preferred): `at /pattern/ <command>` — search, then apply.
Optional ordinal: `at 2nd /pattern/ <command>` (2nd match after cursor).
Anchored summaries carry the ambiguity count: `changed line 9 (match 1 of 3)`.
Global form (v0.8): `at each /pattern/ <command>` — one edit command applied
at EVERY match (per match, column-precise, bottom-up, transactional, one
undo step); echoes a substitute-style compact diff instead of a viewport.

Commands: ciw caw  ci( ci{ ci[ ci" ci'  (+ di/da variants)  diw
          cip/cap dip/dap (paragraph)  dd  cc  o O  A I  i a  D C  x r
          cs{old}{new}  ds{char}  ysiw{char}  (vim-surround)
          yy  y{i,a}{object}  p P  with register prefix `"name <cmd>`
          ("name yap / "name dd cuts / "name p; bare y→unnamed register)
          u (undo — one buffer change per step, crosses writes; no redo)
Rejected: `.` repeat (reissue the same anchored edit — search is strictly
after the cursor, so it advances match by match). Deferred: cit/dit, J, >> <<

Every edit returns (summary, affected_first, affected_last) so the server
can render the post-edit viewport; first/last are None when the echo
already carries the content (yanks, register cuts). Failures raise
EditError loudly and never modify the buffer or move the cursor.
"""

import re

from . import motion
from .buffer import Buffer
from .registers import Register, clip, display, missing, preview
from .substitute import diff_lines


class EditError(Exception):
    """Loud, specific failure (e.g. 'no enclosing ( on line 80')."""


_ANCHOR = re.compile(r"^at\s+(?:(\d+)(?:st|nd|rd|th)\s+)?/((?:\\.|[^/])*)/\s*")
_EACH = re.compile(r"^at\s+each\s+/((?:\\.|[^/])*)/\s*")
_OBJECT_CMD = re.compile(r"^([cd])([ia])([wWp(){}\[\]\"'`])(?:\s(.*))?$", re.DOTALL)
_INSERT_CMD = re.compile(r"^(cc|C|o|O|A|I|i|a)(?:\s(.*))?$", re.DOTALL)
_CS_CMD = re.compile(r"^cs(.)(.)$")
_DS_CMD = re.compile(r"^ds(.)$")
_YSIW_CMD = re.compile(r"^ysiw(.)$")
_YANK_CMD = re.compile(r"^y(y|[ia][wWp(){}\[\]\"'`])(\s.*)?$", re.DOTALL)
# word-named register needs a space ("block yy); vim's no-space form works
# for single letters ("ayy)
_REGISTER_WORD = re.compile(r"^\"(\w+)\s+")
_REGISTER_CHAR = re.compile(r"^\"(\w)(?=\S)")

_BRACKETS = {"(": "()", ")": "()", "{": "{}", "}": "{}", "[": "[]", "]": "[]"}
_QUOTES = "\"'`"


def execute(
    buf: Buffer, command: str, registers: dict[str, Register] | None = None
) -> tuple[str, int | None, int | None]:
    """Apply one edit command; return (summary, first_line, last_line) 0-based.
    first/last are None when there is no viewport to render (yanks and
    register cuts echo their content instead)."""
    # Trailing spaces are preserved: TEXT like `I # ` keeps its trailing space.
    command = command.lstrip().rstrip("\n")
    if registers is None:
        registers = {}
    saved = (buf.cursor.line, buf.cursor.col)

    if command.strip() == "u":
        return _undo(buf)
    original = command  # kept for the undo-echo label
    pre_lines = list(buf.lines)

    # Register prefix may come before or after the anchor:
    # `"name at /pat/ yap` and `at /pat/ "name yap` both work.
    reg_name, command = _split_register(command)

    m = _EACH.match(command)
    if m:
        if reg_name is not None:
            raise EditError('"name registers do not compose with at each')
        try:
            summary, changed = _each(buf, m.group(1), command[m.end():])
        except EditError:
            buf.cursor.line, buf.cursor.col = saved
            raise
        if buf.lines != pre_lines:
            buf.push_undo(pre_lines, saved, original, changed=changed)
        buf.dirty = True
        return summary, None, None

    anchor_note = ""
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
        chosen = (start + ordinal - 1) % len(hits)
        buf.cursor.line, buf.cursor.col = hits[chosen]
        anchor_note = f" (match {chosen + 1} of {len(hits)})"
        command = rest

    if reg_name is None:
        reg_name, command = _split_register(command)

    try:
        summary, first, last, mutates = _dispatch(buf, command, reg_name, registers)
    except EditError:
        buf.cursor.line, buf.cursor.col = saved
        raise
    if mutates:
        buf.dirty = True
        if buf.lines != pre_lines:  # no-op mutations (e.g. `r` with same char) skip
            buf.push_undo(pre_lines, saved, original)
    if anchor_note:
        head, sep, rest = summary.partition("\n")
        summary = head + anchor_note + sep + rest
    return summary, first, last


def _undo(buf: Buffer) -> tuple[str, int | None, int | None]:
    """u: pop one snapshot. Restores lines + pre-command cursor; dirty is
    recomputed against saved_lines so undoing back across a write is exact.
    Registers deliberately survive (vim semantics)."""
    if not buf.undo_stack:
        raise EditError("nothing to undo")
    entry = buf.undo_stack.pop()
    before = buf.lines
    buf.lines = entry.lines
    buf.cursor.line, buf.cursor.col = entry.cursor_line, entry.cursor_col
    buf.dirty = buf.lines != buf.saved_lines

    label = clip(entry.command.splitlines()[0])
    if "\n" in entry.command:
        label += "…"
    summary = f"undid: {label}"
    if buf.undo_stack:
        summary += f" ({len(buf.undo_stack)} more undo step(s))"
    if entry.changed is not None:
        # batch edits restore scattered sites: a spanning viewport would
        # dump everything between the first and last site — echo the
        # inverted compact diff instead (numbering = post-undo lines)
        inverted = [(ln, new, old) for ln, old, new in entry.changed]
        return summary + "\n" + diff_lines(inverted), None, None
    first, last = _restored_span(before, buf.lines)
    return summary, first, last


def _restored_span(before: list[str], after: list[str]) -> tuple[int, int]:
    """(first, last) 0-based span in `after` where it differs from `before`,
    for the post-undo viewport."""
    n = min(len(before), len(after))
    lo = 0
    while lo < n and before[lo] == after[lo]:
        lo += 1
    hi_b, hi_a = len(before) - 1, len(after) - 1
    while hi_b >= lo and hi_a >= lo and before[hi_b] == after[hi_a]:
        hi_b -= 1
        hi_a -= 1
    last_idx = len(after) - 1  # buffer is never empty
    return min(lo, last_idx), min(max(hi_a, lo), last_idx)


def _split_register(command: str) -> tuple[str | None, str]:
    if not command.startswith('"'):
        return None, command
    m = _REGISTER_WORD.match(command) or _REGISTER_CHAR.match(command)
    if not m:
        raise EditError(
            'bad register prefix: use "name <cmd> (e.g. "block yap, "block p)'
        )
    return m.group(1), command[m.end():]


def _each(
    buf: Buffer, pattern: str, cmd: str
) -> tuple[str, list[tuple[int, str | None, str | None]]]:
    """at each /pattern/ <cmd>: one edit command at EVERY match. Per match
    (column-precise), not per-line like vim's :g. Bottom-up so earlier
    positions stay valid; each site is revalidated first — a match consumed
    by a previous edit in the batch is skipped and reported. Transactional:
    a command failure at any surviving site rolls the whole batch back.
    Returns (report, changed-tuples); the tuples come from exact per-site
    spans, never difflib — repeated lines must not misalign the echo."""
    if not cmd:
        raise EditError("at each needs a command: at each /pattern/ <cmd>")
    bare = cmd.strip()
    if (
        bare == "u"
        or bare in ("p", "P")
        or bare.startswith('"')
        or (_YANK_CMD.match(bare) and not _YSIW_CMD.match(bare))
    ):
        raise EditError(
            "at each takes buffer-changing edit commands only "
            '(no y/p/u, no "name registers)'
        )
    try:
        hits = motion.find_matches(buf, pattern)
    except motion.MotionError as e:
        raise EditError(str(e)) from None
    if not hits:
        raise EditError(f"no match: {pattern}")
    rx = re.compile(pattern)  # find_matches already validated it

    pre_lines = list(buf.lines)
    applied = 0
    changed: list[tuple[int, str | None, str | None]] = []
    for line_i, col in reversed(hits):  # bottom-up: edits don't shift earlier sites
        if line_i >= len(buf.lines) or not rx.match(buf.lines[line_i], col):
            continue  # consumed by a previous edit in this batch
        before = list(buf.lines)
        buf.cursor.line, buf.cursor.col = line_i, col
        try:
            _apply(buf, cmd)
        except EditError as e:
            buf.lines = pre_lines  # transactional: all or nothing
            raise EditError(
                f"at each /{pattern}/ failed at the match on line "
                f"{line_i + 1}: {e} — no changes applied"
            ) from None
        # bottom-up keeps every earlier site's numbering pre-edit exact,
        # so prepending yields an ascending pre-edit-numbered list
        changed = _site_delta(before, buf.lines) + changed
        applied += 1

    # two matches on one line = two edits: merge into one old→new pair
    merged: list[tuple[int, str | None, str | None]] = []
    for t in changed:
        if (
            merged and t[0] == merged[-1][0]
            and t[1] is not None and t[2] is not None
            and merged[-1][1] is not None and merged[-1][2] is not None
        ):
            merged[-1] = (t[0], t[1], merged[-1][2])
        else:
            merged.append(t)

    skipped = len(hits) - applied
    if skipped:
        head = (
            f"edited {applied} of {len(hits)} match(es) "
            f"({skipped} consumed by earlier edits in this batch)"
        )
    else:
        head = f"edited {applied} match(es)"
    return head + "\n" + diff_lines(merged), merged


def _site_delta(
    before: list[str], after: list[str]
) -> list[tuple[int, str | None, str | None]]:
    """Changed-tuples for ONE contiguous edit: guarded common prefix/suffix
    trim. Deterministic and exact for a single site — unlike difflib, which
    may align a deletion onto identical lines elsewhere."""
    lo = 0
    n = min(len(before), len(after))
    while lo < n and before[lo] == after[lo]:
        lo += 1
    hi_b, hi_a = len(before) - 1, len(after) - 1
    while hi_b >= lo and hi_a >= lo and before[hi_b] == after[hi_a]:
        hi_b -= 1
        hi_a -= 1
    olds = before[lo:hi_b + 1]
    news = after[lo:hi_a + 1]
    return [
        (
            lo + k,
            olds[k] if k < len(olds) else None,
            news[k] if k < len(news) else None,
        )
        for k in range(max(len(olds), len(news)))
    ]


def _dispatch(
    buf: Buffer, cmd: str, reg_name: str | None, registers: dict[str, Register]
) -> tuple[str, int | None, int | None, bool]:
    bare = cmd.strip()

    m = _YANK_CMD.match(bare)
    if m and not _YSIW_CMD.match(bare):
        if m.group(2) and m.group(2).strip():
            raise EditError(f"y{m.group(1)} takes no TEXT (yank only copies)")
        return _yank(buf, m.group(1), reg_name, registers)

    if bare in ("p", "P"):
        return _paste(buf, bare, reg_name, registers)

    if reg_name is not None:
        return _cut(buf, bare, reg_name, registers)

    summary, first, last = _apply(buf, cmd)
    return summary, first, last, True


def _yank(
    buf: Buffer, what: str, name: str | None, registers: dict[str, Register]
) -> tuple[str, int | None, int | None, bool]:
    """yy / y{i,a}{object}: copy into a register. Buffer and cursor untouched."""
    i = buf.cursor.line
    if what == "y":
        lines = [buf.lines[i]]
        registers[name or ""] = Register(lines, linewise=True)
        head = f"yanked line {i + 1} into {display(name)}"
        return head + "\n" + preview(lines), None, None, False
    scope, obj = what[0], what[1]
    if obj == "p":
        a, b = _paragraph_span(buf.lines, i, around=scope == "a")
        lines = list(buf.lines[a:b + 1])
        registers[name or ""] = Register(lines, linewise=True)
        head = f"yanked {len(lines)} line(s) ({a + 1}–{b + 1}) into {display(name)}"
        return head + "\n" + preview(lines), None, None, False
    start, end = find_object(buf.lines[i], buf.cursor.col, obj, around=scope == "a")
    text = buf.lines[i][start:end]
    registers[name or ""] = Register([text], linewise=False)
    return f'yanked "{clip(text)}" into {display(name)}', None, None, False


def _paste(
    buf: Buffer, cmd: str, name: str | None, registers: dict[str, Register]
) -> tuple[str, int | None, int | None, bool]:
    """p/P: paste a register. Linewise below/above the cursor line, charwise
    after/at the cursor column."""
    key = name or ""
    if key not in registers:
        raise EditError(missing(name, registers))
    reg = registers[key]
    i = buf.cursor.line

    if reg.linewise:
        at = i + 1 if cmd == "p" else i
        buf.lines[at:at] = list(reg.lines)
        first, last = at, at + len(reg.lines) - 1
        buf.cursor.line, buf.cursor.col = last, 0
        where = f"{'below' if cmd == 'p' else 'above'} line {i + 1}"
        head = f"pasted {len(reg.lines)} line(s) from {display(name)} {where}"
        return head, first, last, True

    text = reg.lines[0] if reg.lines else ""
    line = buf.lines[i]
    col = min(buf.cursor.col + 1, len(line)) if cmd == "p" else buf.cursor.col
    buf.lines[i] = line[:col] + text + line[col:]
    buf.cursor.col = col
    head = f'pasted "{clip(text)}" from {display(name)} on line {i + 1}'
    return head, i, i, True


def _cut(
    buf: Buffer, bare: str, name: str, registers: dict[str, Register]
) -> tuple[str, int | None, int | None, bool]:
    """Explicit-register delete: `"name dd` / `"name d{i,a}{object}` cuts
    into the register (the only deletes that touch registers)."""
    i = buf.cursor.line

    if bare == "dd":
        lines = [buf.lines[i]]
        registers[name] = Register(lines, linewise=True)
        del buf.lines[i]
        if not buf.lines:
            buf.lines = [""]
        buf.cursor.line = min(i, len(buf.lines) - 1)
        buf.cursor.col = 0
        head = f"cut line {i + 1} into {display(name)}"
        return head + "\n" + preview(lines), None, None, True

    m = _OBJECT_CMD.match(bare)
    if m and m.group(1) == "d":
        _, scope, obj, text = m.groups()
        if text and text.strip():
            raise EditError(f"d{scope}{obj} takes no TEXT")
        if obj == "p":
            a, b = _paragraph_span(buf.lines, i, around=scope == "a")
            lines = list(buf.lines[a:b + 1])
            registers[name] = Register(lines, linewise=True)
            del buf.lines[a:b + 1]
            if not buf.lines:
                buf.lines = [""]
            buf.cursor.line = min(a, len(buf.lines) - 1)
            buf.cursor.col = 0
            head = f"cut {len(lines)} line(s) ({a + 1}–{b + 1}) into {display(name)}"
            return head + "\n" + preview(lines), None, None, True
        start, end = find_object(buf.lines[i], buf.cursor.col, obj, around=scope == "a")
        cut_text = buf.lines[i][start:end]
        registers[name] = Register([cut_text], linewise=False)
        buf.lines[i] = buf.lines[i][:start] + buf.lines[i][end:]
        buf.cursor.col = start
        return f'cut "{clip(cut_text)}" into {display(name)} (line {i + 1})', i, i, True

    raise EditError(
        f'register prefix "{name} applies to y (yank), d (cut into register), '
        "and p/P (paste) only"
    )


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
            if op in ("C", "A", "I", "i", "a"):
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

        if op == "i":  # insert before the cursor char (anchored: before the match)
            at = min(col, len(line))
            return _splice(buf, i, at, at, text)

        if op == "a":  # append after the cursor char (vim semantics — anchored,
            at = min(col + 1, len(line)) if line else 0  # after the match's FIRST char)
            return _splice(buf, i, at, at, text)

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
        if obj == "p":  # paragraph: the one line-wise text object
            a, b = _paragraph_span(buf.lines, i, around=scope == "a")
            if op == "d":
                del buf.lines[a:b + 1]
                if not buf.lines:
                    buf.lines = [""]
                buf.cursor.line = min(a, len(buf.lines) - 1)
                buf.cursor.col = 0
                return f"deleted lines {a + 1}–{b + 1}", buf.cursor.line, buf.cursor.line
            parts = (text or "").split("\n")
            buf.lines[a:b + 1] = parts
            buf.cursor.line, buf.cursor.col = a, 0
            last = a + len(parts) - 1
            return f"replaced lines {a + 1}–{b + 1} with {len(parts)} line(s)", a, last
        start, end = find_object(line, col, obj, around=scope == "a")
        return _splice(buf, i, start, end, text or "")

    m = _CS_CMD.match(bare)
    if m:
        old, new = m.groups()
        a, b = _surround_span(line, col, old)
        inner = line[a + 1:b - 1]
        if old in "({[":  # open-bracket target trims inner space (vim-surround)
            inner = inner.strip()
        oc, cc_, pad = _surround_delims(new)
        if pad:
            inner = f" {inner} "
        buf.lines[i] = line[:a] + oc + inner + cc_ + line[b:]
        buf.cursor.col = a
        return f"changed surround {old} → {new} on line {i + 1}", i, i

    m = _DS_CMD.match(bare)
    if m:
        old = m.group(1)
        a, b = _surround_span(line, col, old)
        inner = line[a + 1:b - 1]
        if old in "({[":
            inner = inner.strip()
        buf.lines[i] = line[:a] + inner + line[b:]
        buf.cursor.col = a
        return f"deleted surround {old} on line {i + 1}", i, i

    m = _YSIW_CMD.match(bare)
    if m:
        new = m.group(1)
        start, end = _word_span(line, col, around=False)
        oc, cc_, pad = _surround_delims(new)
        word = line[start:end]
        if pad:
            word = f" {word} "
        buf.lines[i] = line[:start] + oc + word + cc_ + line[end:]
        buf.cursor.col = start
        return f"surrounded word with {new} on line {i + 1}", i, i

    raise EditError(
        f"unknown edit command: {cmd!r} "
        "(supported: ciw/caw ci(/{{/[/\"/' di/da-variants cip/dap dd cc D C x r "
        "o O A I i a cs<old><new> ds<char> ysiw<char> yy y<i|a><obj> p P "
        "\"name-prefix for registers, u to undo)"
    )


def _surround_span(line: str, col: int, old: str) -> tuple[int, int]:
    """Span of the enclosing pair for a surround target char, end-exclusive
    (delimiters at [a] and [b-1])."""
    if old not in _BRACKETS and old not in _QUOTES:
        raise EditError(
            f"unsupported surround target: {old!r} (use a bracket or quote)"
        )
    return find_object(line, col, old, around=True)


def _surround_delims(new: str) -> tuple[str, str, bool]:
    """(open, close, pad) for a replacement delimiter. Open-bracket aliases
    pad the content with one inner space, close aliases don't (vim-surround)."""
    if new in _BRACKETS:
        pair = _BRACKETS[new]
        return pair[0], pair[1], new in "({["
    if new in _QUOTES:
        return new, new, False
    raise EditError(
        f"unsupported surround delimiter: {new!r} (use a bracket or quote)"
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


def _paragraph_span(lines: list[str], i: int, around: bool) -> tuple[int, int]:
    """Blank-line-delimited paragraph as 0-based inclusive line span (vim
    semantics: `ap` takes trailing blanks, or leading ones if none trail;
    on a blank line, the blank run — plus the next paragraph for `ap`)."""
    def blank(k: int) -> bool:
        return not lines[k].strip()

    n = len(lines)
    a = b = i
    if blank(i):
        while a > 0 and blank(a - 1):
            a -= 1
        while b + 1 < n and blank(b + 1):
            b += 1
        if around:
            while b + 1 < n and not blank(b + 1):
                b += 1
        return a, b
    while a > 0 and not blank(a - 1):
        a -= 1
    while b + 1 < n and not blank(b + 1):
        b += 1
    if around:
        e = b
        while e + 1 < n and blank(e + 1):
            e += 1
        if e > b:
            b = e
        else:
            while a > 0 and blank(a - 1):
                a -= 1
    return a, b


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
