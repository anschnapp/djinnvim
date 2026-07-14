"""Viewport rendering — the 'screen' every command echoes back.

Format (see design.md):

      78      opts = {}
    → 79      for line in open(path):
                           ^
      80          key, val = line.split("=")

- line numbers 1-based, right-aligned, two-space gutter
- `→` marks the cursor line
- `^` column marker on its own line, only when show_column is True
- `caret-labeled` (default) appends a factual prose label to the caret,
  compiler-diagnostic style: `^ on "r" of "retries"` — the word is the
  exact `ciw` span, so the label names what an edit would change
- cursor rendering style is a config flag (ablation: caret / caret-labeled)
"""

import os

from .buffer import Buffer

DEFAULT_CONTEXT = 2  # lines above and below

CURSOR_STYLE = os.environ.get("DJINNVIM_CURSOR_STYLE", "caret-labeled")  # caret | caret-labeled


def render(
    buf: Buffer,
    first: int | None = None,
    last: int | None = None,
    show_column: bool = False,
    context: int = DEFAULT_CONTEXT,
) -> str:
    """Render lines [first, last] (0-based, defaults to cursor line) plus context."""
    lo = (first if first is not None else buf.cursor.line) - context
    hi = (last if last is not None else buf.cursor.line) + context
    lo, hi = max(lo, 0), min(hi, len(buf.lines) - 1)

    width = len(str(hi + 1))
    out: list[str] = []
    for i in range(lo, hi + 1):
        marker = "→" if i == buf.cursor.line else " "
        out.append(f"{marker} {i + 1:>{width}}  {buf.lines[i]}")
        if show_column and i == buf.cursor.line:
            caret = "^"
            if CURSOR_STYLE == "caret-labeled":
                caret += " " + _caret_label(buf.lines[i], buf.cursor.col)
            out.append(" " * (2 + width + 2 + buf.cursor.col) + caret)
    return "\n".join(out)


def _caret_label(line: str, col: int) -> str:
    """Factual description of the char under the caret. On a word char the
    word is the exact `ciw` span (same `_word_span` as edit.py) — the label
    must never name something an edit wouldn't touch."""
    from .edit import _is_word, _word_span

    if col >= len(line):
        return "at end of line"
    ch = line[col]
    if _is_word(ch):
        start, end = _word_span(line, col, around=False)
        return f'on "{ch}" of "{line[start:end]}"'
    if ch == "\t":
        return 'on tab'
    return f'on "{ch}"'
