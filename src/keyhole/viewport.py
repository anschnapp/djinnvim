"""Viewport rendering — the 'screen' every command echoes back.

Format (see design.md):

      78      opts = {}
    → 79      for line in open(path):
                           ^
      80          key, val = line.split("=")

- line numbers 1-based, right-aligned, two-space gutter
- `→` marks the cursor line
- `^` column marker on its own line, only when show_column is True
- cursor rendering style is a config flag (future ablation: caret / inline / block)
"""

from .buffer import Buffer

DEFAULT_CONTEXT = 2  # lines above and below

CURSOR_STYLE = "caret"  # caret | inline | block  (v0 implements caret only)


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
            out.append(" " * (2 + width + 2 + buf.cursor.col) + "^")
    return "\n".join(out)
