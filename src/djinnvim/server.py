"""MCP wiring for the tool surface: open, motion, edit, substitute,
matches, write. Thin wrapper — all logic lives in session.Session; this module
owns only the MCP registration and the tool descriptions. Descriptions are
written to carry a cold agent alone: compact, but every deviation from vim
stated explicitly. structured_output=False keeps results as plain multi-line
text — the structured {"result": ...} wrapping reached the model JSON-escaped,
destroying viewport alignment (found in benchmark transcripts, 2026-07-13)."""

from pathlib import Path
from urllib.parse import unquote, urlparse

from mcp import types
from mcp.server.fastmcp import Context, FastMCP

from . import roots as roots_mod
from .session import Session

mcp = FastMCP("djinnvim")

# Explicit env roots are exclusive: when set, client roots/list is never
# consulted — the pinned boundary no client chatter can widen.
_ENV_ROOTS = roots_mod.env_roots()
session = Session(roots=_ENV_ROOTS)
_roots_stale = False


async def _on_roots_changed(_notification: types.RootsListChangedNotification) -> None:
    global _roots_stale
    _roots_stale = True


mcp._mcp_server.notification_handlers[types.RootsListChangedNotification] = (
    _on_roots_changed
)


async def _client_roots(ctx: Context) -> list[Path] | None:
    """Roots granted by the MCP client, or None if it offers none."""
    caps = types.ClientCapabilities(roots=types.RootsCapability())
    if not ctx.session.check_client_capability(caps):
        return None
    result = await ctx.session.list_roots()
    paths = [
        roots_mod.check_sane(
            Path(unquote(urlparse(str(root.uri)).path)), "client roots/list"
        )
        for root in result.roots
        if str(root.uri).startswith("file:")
    ]
    return paths or None


async def _ensure_roots(ctx: Context | None) -> str | None:
    """Resolve sandbox roots lazily (roots/list can't run before initialize,
    so it happens on the first tool call). Returns an error string or None."""
    global _roots_stale
    if _ENV_ROOTS is not None:
        return None
    if session.roots is not None and not _roots_stale:
        return None
    try:
        roots = (await _client_roots(ctx)) if ctx is not None else None
        if roots is None:
            roots = roots_mod.fallback_roots()
    except roots_mod.RootsError as e:
        return f"error: {e}"
    session.roots = roots
    _roots_stale = False
    return None


@mcp.tool(structured_output=False)
async def open(path: str, ctx: Context | None = None) -> str:
    """Open a file as the active buffer (or switch to an already-open one).
    Returns metadata + a small viewport, never the full content. Navigate by
    pattern with `motion`, not by reading. Then: `matches` to see all sites
    of a pattern, `edit` for vim normal-mode edits (text objects, whole
    blocks/paragraphs, registers, undo), `substitute` for ex-style regex
    line edits. In every viewport the cursor line's `→ ` prefix is exactly
    as wide as other lines' two-space prefix — indentation shown is exact."""
    err = await _ensure_roots(ctx)
    return err if err else session.open(path)


@mcp.tool(structured_output=False)
async def motion(command: str, ctx: Context | None = None) -> str:
    """Move the cursor in the active buffer. One motion per call: /pattern
    (regex forward), ?pattern (backward), n/N (next/previous match — n is
    ALWAYS forward and N ALWAYS backward, unlike vim), :N (line N), gg/G
    (first/last line), f<char>/F<char> (char on the cursor line). Regex is
    Python re syntax. A match at the cursor is skipped (strictly after);
    search wraps, reporting `(wrapped)`; results say `match i of n`.
    Returns the viewport where you landed.

    Examples: motion("/def parse")   motion(":80")   motion("n")
    """
    err = await _ensure_roots(ctx)
    return err if err else session.motion(command)


@mcp.tool(structured_output=False)
async def edit(command: str, ctx: Context | None = None) -> str:
    """Edit at the cursor, or anchored: `at /pattern/ <cmd>` (ordinal:
    `at 2nd /pattern/ <cmd>`). The anchor lands at the START of the match —
    anchor on the exact text to change: `at /15\\)/ ciw 60` changes the 15
    in `retries(15)`; `at /retries=15/ ciw 60` would change `retries`.
    <cmd> is an edit command, never a motion. A `+N`/`-N` after the closing
    slash moves the anchor N whole lines (cursor at column 0):
    `at /# Merge logic/-1 O text` inserts above the line ABOVE the match —
    e.g. above a comment banner the match sits inside.

    `at each /pattern/ <cmd>` applies the command at EVERY match (top to
    bottom, cursor at each match start) and returns a compact ±diff instead
    of a viewport. One undo step; if the command fails at any site, nothing
    is changed. Edit commands only (no y/p/u, no registers). Text objects
    make it structural: `at each /# obsolete/ dap` deletes every marked
    block/paragraph whole — blank spacing handled, no line counting. To
    repeat an edit match-by-match instead, reissue the same
    `at /pattern/ <cmd>` — it anchors on the NEXT match each time.

    Commands: ciw/caw TEXT, ci(/{/[/"/' TEXT (di/da delete),
    cip/cap/dip/dap (paragraph), dd, cc TEXT, D, C TEXT, x, r<char>,
    o/O TEXT (line below/above, may be multi-line), A/I TEXT (line
    end/start), i/a TEXT (insert before / append after the cursor char —
    anchored, `a` lands after the match's FIRST char), cs<old><new>
    (cs"' turns "x" into 'x'), ds<char>, ysiw<char>. Changes need TEXT,
    deletes take none; everything after the first space is TEXT, verbatim —
    every `\\n` in it is literal (one Enter each, vim-exact): `o body\\n`
    leaves one blank line below "body". o/O are line-wise — to insert below
    a multi-line statement, anchor on its LAST line.

    o/O inherit the current line's indentation by default (vim autoindent):
    TEXT's own leading whitespace is added on top, so `o  x = 1` after a
    4-space line lands at 6 spaces. `o!`/`O!` opt out and insert TEXT
    literally. Both echo pre-edit blank-line counts adjacent to where they
    landed (`2 blank line(s) above insertion point, 0 below`) so blank-line
    convention (e.g. 2 lines between top-level defs) can be matched without
    counting from the viewport.

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
      edit("at each /log_debug\\(/ dd")
      edit("at each /# obsolete/ dap")
      edit("at /def helper/ \\"fn dap")   then   edit("\\"fn p")
      edit("u")
    """
    err = await _ensure_roots(ctx)
    return err if err else session.edit(command)


@mcp.tool(structured_output=False)
async def substitute(command: str, ctx: Context | None = None) -> str:
    """Ex commands for file-wide or ranged changes (call matches first to
    see all sites). Forms: `:%s/old/new/g` (file), `:s/old/new/` (cursor
    line), `:10,40s/foo/bar/`, `:/start/,/end/s/x/y/g` (pattern range),
    `:g/pat/d` (delete matching lines). Flags: g, i. Regex and replacement
    are Python re syntax (\\1 for groups). The pattern-range end is
    searched forward FROM the start and BOTH addresses are inclusive; any
    address takes +N/-N — end on `/pat/-1` for "up to but not including".
    Numeric addresses go stale after every edit; prefer pattern addresses.
    To rewrite one line into several without retyping its indentation,
    capture it: `:s/^( +)old_tail/\\1new\\n\\1    second line/` (`\\n` in
    the replacement inserts a line break).
    Returns the count + a compact diff of changed lines; zero matches is a
    loud error; one undo step per command (edit("u") reverts an over-match
    whole).

    This tool is line/regex-shaped. To delete or change a whole
    block/paragraph at every match, don't hand-count line ranges (blank
    lines miscount) — use edit's `at each /pattern/ <cmd>`, e.g.
    `at each /# obsolete/ dap`; `:g/pat/d` deletes only the matching
    lines themselves.

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
    err = await _ensure_roots(ctx)
    return err if err else session.substitute(command)


@mcp.tool(structured_output=False)
async def matches(pattern: str, context: int = 0, ctx: Context | None = None) -> str:
    """Grep-style listing of all regex matches in the active buffer — one
    line per matching line, capped at 50. Call before rename-like refactors
    to see every affected site. `context` (0 or 1) adds surrounding lines.

    Example: matches("parse_config")
    """
    err = await _ensure_roots(ctx)
    return err if err else session.matches(pattern, context)


@mcp.tool(structured_output=False)
async def write(preview: bool = False, ctx: Context | None = None) -> str:
    """Save the active buffer to disk. Returns confirmation + how many lines
    changed since the last write. Buffers are in-memory until written —
    nothing else (tests, other tools, file reads) sees buffer changes, so
    write BEFORE running anything against the file. preview=True writes
    NOTHING and returns the pending ±diff (buffer vs disk, disk line
    numbers) — the final review before committing."""
    err = await _ensure_roots(ctx)
    return err if err else session.write(preview)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
