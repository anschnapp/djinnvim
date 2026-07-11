"""Shared register machinery for the two register surfaces: normal-mode
(edit.py: yy / "name yap / "name dd / p / P) and the ex-range fallback
(substitute.py: :RANGE y NAME, :RANGE d NAME).

Registers are session-wide *visible* state: every yank/cut echoes name +
content, and a wrong-name paste fails loudly listing every register. The
key "" is the unnamed register. Registers have a kind, like vim's:
linewise (yy, yap, dd, ex ranges — paste inserts whole lines) or charwise
(yiw, yi( — paste inserts within the line).
"""

from dataclasses import dataclass

PREVIEW_EDGE = 3      # content previews: lines shown at each end when elided
PREVIEW_LINE_CAP = 120  # content previews: max chars per line


@dataclass
class Register:
    lines: list[str]
    linewise: bool = True


def display(name: str | None) -> str:
    return f'register "{name}"' if name else "the unnamed register"


def clip(line: str) -> str:
    return line if len(line) <= PREVIEW_LINE_CAP else line[:PREVIEW_LINE_CAP] + "…"


def preview(lines: list[str]) -> str:
    """Stripped register-content echo: short blocks in full, long ones
    first/last PREVIEW_EDGE with an elision marker."""
    if len(lines) <= 2 * PREVIEW_EDGE + 1:
        shown = [f"  {clip(l)}" for l in lines]
    else:
        shown = [f"  {clip(l)}" for l in lines[:PREVIEW_EDGE]]
        shown.append(f"  ... {len(lines) - 2 * PREVIEW_EDGE} more line(s) ...")
        shown.extend(f"  {clip(l)}" for l in lines[-PREVIEW_EDGE:])
    return "\n".join(shown)


def missing(name: str | None, registers: dict[str, Register]) -> str:
    """Wrong-name recovery message: what's missing + every register with a
    preview, so recovery is one glance at the error, never a guess."""
    what = (
        f'no register "{name}"' if name
        else "unnamed register is empty (nothing yanked yet)"
    )
    if not registers:
        return (
            what + ' — no registers set; yank with yy / "NAME yap, '
            'cut with "NAME dd, or ex ranges (:N,My NAME)'
        )
    out = [what + " — available registers:"]
    for key, reg in registers.items():
        label = f'"{key}"' if key else "(unnamed)"
        tail = "" if len(reg.lines) == 1 else f" ... ({len(reg.lines)} lines)"
        out.append(f"  {label}: {clip(reg.lines[0])}{tail}")
    return "\n".join(out)
