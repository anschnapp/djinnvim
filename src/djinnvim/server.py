"""MCP wiring for the tool surface: open, motion, edit, substitute,
matches, write. Thin wrapper — all logic lives in session.Session; this module
owns only the MCP registration and the tool descriptions. Descriptions are
written to carry a cold agent alone: compact, but every deviation from vim
stated explicitly. structured_output=False keeps results as plain multi-line
text — the structured {"result": ...} wrapping reached the model JSON-escaped,
destroying viewport alignment (found in benchmark transcripts, 2026-07-13)."""

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .session import Session

mcp = FastMCP("djinnvim")

session = Session(Path(os.environ.get("DJINNVIM_ROOT", os.getcwd())))


@mcp.tool(structured_output=False)
def open(path: str) -> str:
    """Open a file as the active buffer (or switch to an already-open one).
    Returns metadata + a small viewport, never the full content. Navigate by
    pattern with `motion`, not by reading."""
    return session.open(path)


@mcp.tool(structured_output=False)
def motion(command: str) -> str:
    """Move the cursor in the active buffer. One motion per call: /pattern
    (regex forward), ?pattern (backward), n/N (next/previous match — n is
    ALWAYS forward and N ALWAYS backward, unlike vim), :N (line N), gg/G
    (first/last line), f<char>/F<char> (char on the cursor line). Regex is
    Python re syntax. A match at the cursor is skipped (strictly after);
    search wraps, reporting `(wrapped)`; results say `match i of n`.
    Returns the viewport where you landed.

    Examples: motion("/def parse")   motion(":80")   motion("n")
    """
    return session.motion(command)


@mcp.tool(structured_output=False)
def edit(command: str) -> str:
    """Edit at the cursor, or anchored: `at /pattern/ <cmd>` (ordinal:
    `at 2nd /pattern/ <cmd>`). The anchor lands at the START of the match —
    anchor on the exact text to change: `at /15\\)/ ciw 60` changes the 15
    in `retries(15)`; `at /retries=15/ ciw 60` would change `retries`.
    <cmd> is an edit command, never a motion.

    Commands: ciw/caw TEXT, ci(/{/[/"/' TEXT (di/da delete),
    cip/cap/dip/dap (paragraph), dd, cc TEXT, D, C TEXT, x, r<char>,
    o/O TEXT (line below/above, may be multi-line), A/I TEXT (line
    end/start), i/a TEXT (insert before / append after the cursor char —
    anchored, `a` lands after the match's FIRST char), cs<old><new>
    (cs"' turns "x" into 'x'), ds<char>, ysiw<char>. Changes need TEXT,
    deletes take none; everything after the first space is TEXT, verbatim.

    Registers: yy / y<i|a><obj> yank, p/P paste below/above the cursor line
    (charwise: within it). `"name` prefix composes with the anchor:
    `at /def helper/ "fn dap` cuts the function; `"fn p` pastes it. Only
    "name-prefixed deletes write registers; yanks/cuts echo their content;
    a wrong name on p lists them all. `u` undoes the last buffer change
    (repeat to go further; crosses writes; no redo).

    Returns a summary (`changed line 9 (match 1 of 3)` — if n > 1, check
    the site) + post-edit viewport. Failures never touch the buffer.

    Examples:
      edit("at /old_name/ ciw new_name")
      edit("at /def helper/ \\"fn dap")   then   edit("\\"fn p")
      edit("u")
    """
    return session.edit(command)


@mcp.tool(structured_output=False)
def substitute(command: str) -> str:
    """Ex commands for file-wide or ranged changes (call matches first to
    see all sites). Forms: `:%s/old/new/g` (file), `:s/old/new/` (cursor
    line), `:10,40s/foo/bar/`, `:/start/,/end/s/x/y/g` (pattern range),
    `:g/pat/d` (delete matching lines). Flags: g, i. Regex and replacement
    are Python re syntax (\\1 for groups). The pattern-range end is
    searched forward FROM the start and BOTH addresses are inclusive; any
    address takes +N/-N — end on `/pat/-1` for "up to but not including".
    Returns the count + a compact diff of changed lines; zero matches is a
    loud error; one undo step per command (edit("u") reverts an over-match
    whole).

    Register ranges, for blocks text objects can't select (e.g. a function
    with internal blank lines): `:RANGE y NAME` yanks, `:RANGE d NAME`
    cuts — paste with p/P in edit (works across files). Move recipe:
    `:/def helper/,/^def /-1d fn`, then paste ABOVE the destination def
    (`at /def target/ "fn P`). Bare `:RANGE d` never touches a register.

    Examples:
      substitute(":%s/parse_config/load_config/g")
      substitute(":g/DEBUG/d")
      substitute(":/def helper/,/^def /-1d fn")
    """
    return session.substitute(command)


@mcp.tool(structured_output=False)
def matches(pattern: str, context: int = 0) -> str:
    """Grep-style listing of all regex matches in the active buffer — one
    line per matching line, capped at 50. Call before rename-like refactors
    to see every affected site. `context` (0 or 1) adds surrounding lines.

    Example: matches("parse_config")
    """
    return session.matches(pattern, context)


@mcp.tool(structured_output=False)
def write() -> str:
    """Save the active buffer to disk. Returns confirmation + how many lines
    changed since the last write. Buffers are in-memory until written."""
    return session.write()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
