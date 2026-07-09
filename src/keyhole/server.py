"""MCP server wiring for the v0 tool surface: open, motion, edit, matches, write."""

import difflib
import os
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import edit as edit_mod
from . import motion as motion_mod
from .buffer import Buffer
from .viewport import render

mcp = FastMCP("keyhole")

ROOT = Path(os.environ.get("KEYHOLE_ROOT", os.getcwd())).resolve()

_buffers: dict[Path, Buffer] = {}
_active: Buffer | None = None

_LANGUAGES = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".jsx": "jsx", ".rs": "rust", ".go": "go", ".c": "c", ".h": "c",
    ".cpp": "c++", ".java": "java", ".rb": "ruby", ".sh": "shell",
    ".md": "markdown", ".json": "json", ".toml": "toml", ".yaml": "yaml",
    ".yml": "yaml", ".html": "html", ".css": "css", ".sql": "sql",
    ".txt": "text",
}

MATCHES_CAP = 50


def _require_active() -> Buffer:
    if _active is None:
        raise edit_mod.EditError("no active buffer — call open(path) first")
    return _active


def _check_fresh(buf: Buffer) -> None:
    try:
        stale = buf.stale()
    except FileNotFoundError:
        return  # deleted on disk: the buffer is the only copy; write recreates it
    if stale:
        raise edit_mod.EditError(
            f"{buf.path} changed on disk since open — re-open it "
            "(unwritten buffer changes will be lost)"
        )


@mcp.tool()
def open(path: str) -> str:
    """Open a file as the active buffer. Returns metadata + a small viewport at
    line 1, never the full content. Navigate by pattern with `motion`, not by
    reading.

    Examples:
      open("src/app.py")
      open("README.md")
    """
    global _active
    p = Path(path)
    p = (p if p.is_absolute() else ROOT / p).resolve()
    if not p.is_relative_to(ROOT):
        return f"error: {p} is outside the allowed root {ROOT}"
    if not p.is_file():
        return f"error: no such file: {p}"

    notes = []
    buf = _buffers.get(p)
    if buf is not None and not buf.stale():
        if buf.dirty:
            notes.append("(buffer has unwritten changes)")
    else:
        if buf is not None:
            notes.append(
                "(file changed on disk; reloaded"
                + (", unwritten changes discarded)" if buf.dirty else ")")
            )
        buf = Buffer.open(p)
        _buffers[p] = buf
    _active = buf

    lang = _LANGUAGES.get(p.suffix, p.suffix.lstrip(".") or "unknown")
    size = p.stat().st_size
    head = f"{p} — {len(buf.lines)} lines, {size} bytes, {lang}"
    if notes:
        head += " " + " ".join(notes)
    return head + "\n" + render(buf)


@mcp.tool()
def motion(command: str) -> str:
    """Move the cursor in the active buffer. One motion per call:
    /pattern (regex search forward), ?pattern (backward), n/N (next/previous
    match), :N (go to line N), gg/G (first/last line). Searches wrap and
    report `match i of n`. Returns the viewport where you landed.

    Examples:
      motion("/def parse")   -> match 2 of 5, cursor on that line
      motion(":80")          -> line 80
      motion("n")            -> next match of the last search
    """
    buf = _active
    if buf is None:
        return "error: no active buffer — call open(path) first"
    try:
        status, show_col = motion_mod.execute(buf, command)
    except motion_mod.MotionError as e:
        return f"error: {e}"
    return status + "\n" + render(buf, show_column=show_col)


@mcp.tool()
def edit(command: str) -> str:
    """Edit the active buffer at the cursor, or anchored in the same call:
    `at /pattern/ <cmd>` (optional ordinal: `at 2nd /pattern/ <cmd>`).
    Commands: ciw/caw TEXT, ci(/ci{/ci[/ci"/ci' TEXT (+ di/da to delete),
    dd, cc TEXT, D, C TEXT, x, r<char>, o/O TEXT (insert line below/above,
    TEXT may be multi-line), A/I TEXT (append/insert on line).
    Returns a one-line summary + the post-edit viewport. Failed commands
    never modify the buffer.

    Examples:
      edit("at /old_name/ ciw new_name")   -> rename the word at the match
      edit("at /timeout=30/ ci( timeout=60")
      edit("o import sys")                 -> new line below the cursor
      edit("dd")                           -> delete the cursor line
    """
    buf = _active
    if buf is None:
        return "error: no active buffer — call open(path) first"
    try:
        _check_fresh(buf)
        summary, first, last = edit_mod.execute(buf, command)
    except edit_mod.EditError as e:
        return f"error: {e}"
    return summary + "\n" + render(buf, first=first, last=last)


@mcp.tool()
def matches(pattern: str, context: int = 0) -> str:
    """Grep-style listing of all regex matches in the active buffer — one line
    per matching line, capped at 50, tens of tokens instead of thousands.
    Call this before rename-like refactors to see every affected site.
    `context` (0 or 1) adds that many surrounding lines per hit.

    Examples:
      matches("parse_config")        -> 3 matches on 3 lines / 12: ...
      matches("TODO", context=1)
    """
    buf = _active
    if buf is None:
        return "error: no active buffer — call open(path) first"
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"error: bad regex {pattern!r}: {e}"

    hit_lines = []
    total = 0
    for i, line in enumerate(buf.lines):
        n = sum(1 for _ in rx.finditer(line))
        if n:
            hit_lines.append(i)
            total += n
    if not hit_lines:
        return f"no match: {pattern}"

    width = len(str(hit_lines[min(len(hit_lines), MATCHES_CAP) - 1] + 1))
    out = [f"{total} match(es) on {len(hit_lines)} line(s)"]
    for i in hit_lines[:MATCHES_CAP]:
        for j in range(max(i - context, 0), min(i + context, len(buf.lines) - 1) + 1):
            sep = ":" if j == i else " "
            out.append(f"{j + 1:>{width}}{sep} {buf.lines[j]}")
        if context:
            out.append("--")
    if len(hit_lines) > MATCHES_CAP:
        out.append(f"... and {len(hit_lines) - MATCHES_CAP} more lines")
    return "\n".join(out)


@mcp.tool()
def write() -> str:
    """Save the active buffer to disk. Returns confirmation + how many lines
    changed since the last write. Buffers are in-memory until written."""
    buf = _active
    if buf is None:
        return "error: no active buffer — call open(path) first"
    try:
        _check_fresh(buf)
    except edit_mod.EditError as e:
        return f"error: {e}"

    changed = sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, buf.saved_lines, buf.lines
        ).get_opcodes()
        if tag != "equal"
    )
    buf.write()
    return f"wrote {buf.path} ({len(buf.lines)} lines, {changed} line(s) changed)"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
