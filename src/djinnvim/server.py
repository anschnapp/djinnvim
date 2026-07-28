"""MCP wiring for the tool surface: open, motion, edit, substitute, print,
matches, write. Thin wrapper — all logic lives in session.Session; this module
owns only the MCP registration and the tool descriptions. Descriptions are
written to carry a cold agent alone: compact, but every deviation from vim
stated explicitly. structured_output=False keeps results as plain multi-line
text — the structured {"result": ...} wrapping reached the model JSON-escaped,
destroying viewport alignment (found in benchmark transcripts, 2026-07-13)."""

import inspect
from pathlib import Path
from urllib.parse import unquote, urlparse

from mcp import types
from mcp.server.fastmcp import Context, FastMCP

from . import roots as roots_mod
from .session import Session

# Cross-cutting guidance lives here, not in the tool descriptions (v0.18).
# Claude Code truncates every MCP-supplied string at 2048 chars, silently:
# `edit` had grown to 3944 and half of it — the indent rule, registers, undo,
# every example — never reached a model. Server instructions are a second
# 2048-char channel, loaded once and shared by all seven tools, so the rules
# that span tools belong here and each description keeps only its own.
# Budget rule: keep this under 2000 chars, and check with the drift test.
INSTRUCTIONS = """\
djinnvim is keyhole editing: you never read whole files, you hop between
pattern anchors and small viewports. Reach for it when finding or changing
something would otherwise mean reading a whole file, or when a change repeats
across many sites; creating or wholesale-rewriting a file is not its job.
Use `matches` to see every relevant site, then one `edit` or `substitute`
call per change, reading the echoed viewport or diff before the next call.
`print` when you need a bigger look. Every tool takes `path`, so no separate
`open` step is needed.

You already know vim. These are the differences that matter:

- No counts, no `.`, no macros, marks or visual mode, and one command per
  call. Position always comes from a pattern, never from counting lines or
  columns.
- TEXT is passed inline instead of typed in insert mode: `ciw foo`,
  `o     body`, `A  # note`. Exactly one space separates the command from
  TEXT and the rest is verbatim, so leading and trailing whitespace survive.
- Newlines in `edit` TEXT must be real newline characters and are inserted
  1:1, including trailing ones. The two characters backslash-n are NOT
  translated, they stay as typed, so source like print("a\\nb") lands
  correctly. In a `substitute` replacement backslash-n does insert a
  newline: same two characters, opposite meaning in the two tools.
- Indentation is vim autoindent. Line-wise inserts (`o`, `O`, `cc`) take the
  reference line's indent and your TEXT's own leading whitespace stacks on
  top, so pass only the indent BEYOND the anchor's. `o!` / `O!` / `cc!`
  insert TEXT literally. `substitute` replacements are always literal;
  capture the indent with `^(\\s*)` and `\\1` if you need it there.
- The buffer is not the disk. Nothing is saved until `write`, so write
  before running tests or reading the file another way.
  `write(preview=True)` shows what is pending.
- Every success echoes a viewport or a diff; every failure is loud and
  changes nothing. The echo is your screen: read it before the next call.
"""

mcp = FastMCP("djinnvim", instructions=INSTRUCTIONS)

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
    """Open a file as the active buffer and show its head: metadata + a
    small viewport, never the full content. Optional — every other tool
    takes `path` and opens the file itself, so `open` is for when you want
    the header, or to switch back to an already-open buffer.

    Then: `matches` to see all sites of a pattern, `print` to read a window
    of lines around a spot, `motion` to move by pattern rather than by
    reading, `edit` for vim normal-mode edits (text objects, whole
    blocks/paragraphs, registers, undo), `substitute` for ex-style regex
    line edits, `write` to save — nothing reaches disk before that.

    In every viewport the cursor line's `→ ` prefix is exactly as wide as
    other lines' two-space prefix — indentation shown is exact."""
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
async def edit(command: str, path: str | None = None, ctx: Context | None = None) -> str:
    """Change a file in place with one vim normal-mode command, TEXT inline
    (`ciw foo`). You name the site by pattern instead of quoting the old and
    new text back: worth it when the file is large relative to the change,
    or the change repeats across sites. Not for creating files or rewriting
    one wholesale. `path` opens that file first, so one call can be the
    whole edit.

    `at /regex/ <cmd>` edits at the next match; `at "literal text" <cmd>`
    needs no escaping; `at 2nd /pat/ <cmd>` picks the Nth; `/pat/+N` or
    `/pat/-N` shifts N whole lines, which is how you insert above a banner
    the match sits inside. The anchor lands at the START of the match, so
    anchor on the exact text you change: `at /15\\)/ ciw 60` changes the 15
    in retries(15), `at /retries=15/ ciw 60` the word retries. <cmd> is an
    edit command, never a motion.

    `at each /pat/ <cmd>` edits EVERY match, replacing vim's `:g//normal`.
    One undo step, all-or-nothing, echoing a compact diff instead of a
    viewport. No registers, no y/p/u. Text objects make it structural:
    `at each /# obsolete/ dap` deletes every marked block whole, blank lines
    included. To step through matches instead, reissue `at /pat/ <cmd>`:
    each call takes the next.

    Commands: ciw/caw, ci(/{/[/"/' plus di/da variants, dip/dap, dd, cc, D,
    C, x, r<char>, o/O (below/above, may be multi-line), A/I, i/a,
    cs<old><new>, ds<char>, ysiw<char>, yy and y<i|a><obj>, p/P, u. Changes
    take TEXT, deletes take none. `a` lands after the match's FIRST char, as
    in vim. `o`/`O`/`cc` autoindent from the reference line; `o!`/`O!`/`cc!`
    insert TEXT literally. `o`/`O` echo the blank-line counts around the
    insertion point, so match spacing from that echo, not by counting.

    A `"name` prefix composes with the anchor: `at /def helper/ "fn dap`
    cuts, `"fn p` pastes it back, across files too. Only named deletes write
    a register, `c` never does. `u` undoes one change, no redo.

    Examples:
      edit("at /old_name/ ciw new_name", path="src/app/config.py")
      edit("at \\"# merge (skip blocks)\\" O")
      edit("at each /log_debug\\(/ dd")
    """
    err = await _ensure_roots(ctx)
    return err if err else session.edit(command, path)


@mcp.tool(structured_output=False)
async def substitute(
    command: str, path: str | None = None, ctx: Context | None = None
) -> str:
    """Ex commands for file-wide or ranged changes — one regex pass instead
    of many hops, without the file in context (call matches first to see all
    sites). `path` opens that file first. Forms: `:%s/old/new/g` (file), `:s/old/new/` (cursor
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
    return err if err else session.substitute(command, path)


@mcp.tool(name="print", structured_output=False)
async def print_(
    command: str = "p", path: str | None = None, ctx: Context | None = None
) -> str:
    """Read a window of lines around a spot instead of the whole file
    (ed/vim `:p`) — read-only, it never modifies anything. `path` opens that
    file first. Forms: `p` (current line, cursor unchanged), `:80 p` / `:/def load/ p`
    (the cursor MOVES to the addressed line, then prints it), `:10,25 p`
    (explicit range; cursor to its last line). Window words widen the view
    around the cursor line: `p above tiny`, `p below middle`,
    `p around long` — tiny=8, middle=25, long=50 lines (`above`/`below`
    add that many on that side; `around` adds that many on EACH side); a
    plain number also works (`p below 12`). Address and window combine:
    `:/def load/ p around middle`. Addresses take +N/-N offsets. Output is
    the numbered viewport (`→` marks the cursor); to page further, address
    a line number from the gutter and print again. Max ~100 lines per call
    — for whole-file overviews use `matches`, not repeated prints.

    Examples:
      print(":/def load_config/ p around middle")
      print("p above tiny")
      print(":120,140 p", path="src/app/config.py")
    """
    err = await _ensure_roots(ctx)
    return err if err else session.print(command, path)


@mcp.tool(structured_output=False)
async def matches(
    pattern: str, context: int = 0, path: str | None = None, ctx: Context | None = None
) -> str:
    """Find every site of a regex in a file without loading the file into
    context — one line per matching line, capped at 50. The cheap
    alternative to reading a file to locate something, and the pre-check
    before any rename-like refactor. `context` (0 or 1) adds surrounding
    lines. `path` opens that file first; without it, the active buffer.

    Example: matches("parse_config", path="src/app/config.py")
    """
    err = await _ensure_roots(ctx)
    return err if err else session.matches(pattern, context, path)


@mcp.tool(structured_output=False)
async def write(
    preview: bool = False, path: str | None = None, ctx: Context | None = None
) -> str:
    """Save the active buffer to disk. Returns confirmation + how many lines
    changed since the last write. Buffers are in-memory until written —
    nothing else (tests, other tools, file reads) sees buffer changes, so
    write BEFORE running anything against the file. preview=True writes
    NOTHING and returns the pending ±diff (buffer vs disk, disk line
    numbers) — the final review before committing. `path` picks the buffer
    to save, when several files are open."""
    err = await _ensure_roots(ctx)
    return err if err else session.write(preview, path)


def _dedent_descriptions() -> None:
    """Docstring indentation is billed against the client's 2048-char budget
    (123 chars of it in `edit` alone), so strip it once at import."""
    for tool in mcp._tool_manager._tools.values():
        if tool.description:
            tool.description = inspect.cleandoc(tool.description)


_dedent_descriptions()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
