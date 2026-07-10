"""MCP wiring for the v0.1 tool surface: open, motion, edit, substitute,
matches, write. Thin wrapper — all logic lives in session.Session; this module
owns only the MCP registration and the tool descriptions."""

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .session import Session

mcp = FastMCP("djinnvim")

session = Session(Path(os.environ.get("DJINNVIM_ROOT", os.getcwd())))


@mcp.tool()
def open(path: str) -> str:
    """Open a file as the active buffer. Returns metadata + a small viewport at
    line 1, never the full content. Navigate by pattern with `motion`, not by
    reading.

    Examples:
      open("src/app.py")
      open("README.md")
    """
    return session.open(path)


@mcp.tool()
def motion(command: str) -> str:
    """Move the cursor in the active buffer. One motion per call:
    /pattern (regex search forward), ?pattern (backward), n/N (next/previous
    match), :N (go to line N), gg/G (first/last line), f<char>/F<char>
    (next/previous occurrence of char on the cursor line — sub-line hops).
    Searches wrap and report `match i of n`. Returns the viewport where you
    landed. Regex is Python re syntax, not PCRE.

    Examples:
      motion("/def parse")   -> match 2 of 5, cursor on that line
      motion(":80")          -> line 80
      motion("n")            -> next match of the last search
      motion("f\\"")          -> cursor to the next " on this line
    """
    return session.motion(command)


@mcp.tool()
def edit(command: str) -> str:
    """Edit the active buffer at the cursor, or anchored in the same call:
    `at /pattern/ <cmd>` (optional ordinal: `at 2nd /pattern/ <cmd>`).
    Anchored summaries report `(match i of n)` — if n > 1 and you didn't
    pick an ordinal, check you hit the right site.
    Commands: ciw/caw TEXT, ci(/ci{/ci[/ci"/ci' TEXT (+ di/da to delete),
    dd, cc TEXT, D, C TEXT, x, r<char>, o/O TEXT (insert line below/above,
    TEXT may be multi-line), A/I TEXT (append/insert on line),
    cs<old><new> (change surround, e.g. cs"' turns "x" into 'x'),
    ds<char> (delete surround), ysiw<char> (surround word under cursor).
    Returns a one-line summary + the post-edit viewport. Failed commands
    never modify the buffer.

    Examples:
      edit("at /old_name/ ciw new_name")   -> rename the word at the match
      edit("at /timeout=30/ ci( timeout=60")
      edit("at /'hello'/ cs'\\"")           -> 'hello' becomes "hello"
      edit("o import sys")                 -> new line below the cursor
      edit("dd")                           -> delete the cursor line
    """
    return session.edit(command)


@mcp.tool()
def substitute(command: str) -> str:
    """Ex-style commands on the active buffer — for repetitive, file-wide,
    or ranged changes where one pattern beats many single edits (call matches
    first to see every affected site). Forms: `:%s/old/new/g` (whole file),
    `:s/old/new/` (cursor line), `:10,40s/foo/bar/` (line range),
    `:/start pat/,/end pat/s/x/y/g` (pattern range), `:g/pat/d` (delete
    matching lines). Flags: g (all per line), i (ignore case). Regex and
    replacement are Python re syntax (\\1 for groups). Returns the
    substitution count + a compact diff of changed lines. Zero matches is a
    loud error; the buffer is untouched.

    Registers — move text without retyping it: `:RANGE y NAME` yanks the
    range into register NAME, `:RANGE d NAME` cuts it, then position the
    cursor with motion and `:put NAME` inserts it below the cursor line
    (works across files). Ranges as above (`:10,20y block`,
    `:/def helper/,/^$/d block`). Bare `:RANGE d` is a plain delete and
    never touches a register; bare `:y`/`:put` use the unnamed register.
    Yank/cut echo the stored content; you never retype it.

    Examples:
      substitute(":%s/parse_config/load_config/g")
      substitute(":g/print\\(.*DEBUG/d")
      substitute(":/def render/,/^$/s/ctx/context/g")
      substitute(":/def helper/,/^$/d block")  then  substitute(":put block")
    """
    return session.substitute(command)


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
    return session.matches(pattern, context)


@mcp.tool()
def write() -> str:
    """Save the active buffer to disk. Returns confirmation + how many lines
    changed since the last write. Buffers are in-memory until written."""
    return session.write()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
