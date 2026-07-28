"""Interface-neutral session: the seven keyhole operations as plain
string-in/string-out methods (errors included, as `error: ...` strings).

Both the MCP server (server.py) and the future CLI are thin wrappers around
this class. All session state (open buffers, active buffer) lives here so a
CLI can later persist it to a state file between invocations.
"""

import difflib
import re
from pathlib import Path

from . import edit as edit_mod
from . import motion as motion_mod
from . import printcmd as printcmd_mod
from . import substitute as substitute_mod
from .buffer import Buffer
from .registers import Register
from .viewport import render

_LANGUAGES = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".jsx": "jsx", ".rs": "rust", ".go": "go", ".c": "c", ".h": "c",
    ".cpp": "c++", ".java": "java", ".rb": "ruby", ".sh": "shell",
    ".md": "markdown", ".json": "json", ".toml": "toml", ".yaml": "yaml",
    ".yml": "yaml", ".html": "html", ".css": "css", ".sql": "sql",
    ".txt": "text",
}

MATCHES_CAP = 50


class Session:
    def __init__(self, roots: list[Path] | None = None):
        # None = not yet resolved (the server fills this in lazily from the
        # client); may be reassigned when the client's root grants change.
        self.roots: list[Path] | None = (
            [Path(r).resolve() for r in roots] if roots is not None else None
        )
        self.buffers: dict[Path, Buffer] = {}
        self.active: Buffer | None = None
        # Session-wide (not per-buffer), so cut in one file / paste in
        # another works. Key "" is the unnamed register.
        self.registers: dict[str, Register] = {}

    def _check_fresh(self, buf: Buffer) -> None:
        try:
            stale = buf.stale()
        except FileNotFoundError:
            return  # deleted on disk: the buffer is the only copy; write recreates it
        if stale:
            raise edit_mod.EditError(
                f"{buf.path} changed on disk since open — re-open it "
                "(unwritten buffer changes will be lost)"
            )

    def _roots_display(self) -> str:
        return ", ".join(str(r) for r in (self.roots or []))

    def _contained(self, p: Path) -> bool:
        return any(p.is_relative_to(r) for r in (self.roots or []))

    def _switch(
        self, path: str, allow_discard: bool = True
    ) -> tuple[Buffer | None, str, list[str]]:
        """Resolve `path` against the sandbox, then open its buffer (or
        re-activate an already-open one) and make it active. Returns
        (buffer, error, notes); buffer is None exactly when error is set.
        Shared by `open` and by every op's optional `path` argument;
        `allow_discard=False` refuses the reload that would drop unwritten
        changes (the implicit-switch carve-out, see `_activate`)."""
        if not self.roots:
            return None, "error: no sandbox roots configured — set DJINNVIM_ROOTS", []
        p = Path(path)
        if not p.is_absolute():
            if len(self.roots) > 1:
                return (
                    None,
                    f"error: relative path {path!r} with multiple sandbox "
                    f"roots ({self._roots_display()}) — use an absolute path",
                    [],
                )
            p = self.roots[0] / p
        p = p.resolve()  # BEFORE the containment check: symlinks resolve to
        # their true target, so a link inside a root pointing out is rejected
        if not self._contained(p):
            return (
                None,
                f"error: {p} is outside the sandbox root(s): "
                f"{self._roots_display()}",
                [],
            )
        if not p.is_file():
            return None, f"error: no such file: {p}", []

        notes = []
        buf = self.buffers.get(p)
        if buf is not None and not buf.stale():
            if buf.dirty:
                notes.append("(buffer has unwritten changes)")
        else:
            if buf is not None:
                if buf.dirty and not allow_discard:
                    return (
                        None,
                        f"error: {p} changed on disk since open — re-open it "
                        "(unwritten buffer changes will be lost)",
                        [],
                    )
                notes.append(
                    "(file changed on disk; reloaded"
                    + (", unwritten changes discarded)" if buf.dirty else ")")
                )
            buf = Buffer.open(p)
            self.buffers[p] = buf
        self.active = buf
        return buf, "", notes

    def _activate(self, path: str | None) -> tuple[str, str]:
        """Honor an op's optional `path`: exactly as if `open(path)` had run
        first, with one carve-out — an implicit switch never discards
        unwritten changes, so a dirty buffer that went stale on disk raises
        the usual staleness error instead of silently reloading.
        Returns (error, note); the note announces the switch, since a
        changed active buffer must never be a silent state change."""
        if path is None:
            return "", ""
        was = self.active
        buf, err, notes = self._switch(path, allow_discard=False)
        if err:
            return err, ""
        if buf is was:
            return "", ""  # already there: no state change, no noise
        note = f"[now on {buf.path} — {len(buf.lines)} lines]"
        if notes:
            note += " " + " ".join(notes)
        return "", note

    def open(self, path: str) -> str:
        buf, err, notes = self._switch(path)
        if err:
            return err
        assert buf is not None
        p = buf.path
        lang = _LANGUAGES.get(p.suffix, p.suffix.lstrip(".") or "unknown")
        size = p.stat().st_size
        head = f"{p} — {len(buf.lines)} lines, {size} bytes, {lang}"
        if notes:
            head += " " + " ".join(notes)
        return head + "\n" + render(buf)

    def _enter(self, path: str | None) -> tuple[Buffer | None, str, str]:
        """Resolve an op's optional `path` and hand back the buffer to work
        on: (buffer, error, note). Every op starts here."""
        err, note = self._activate(path)
        if err:
            return None, err, ""
        if self.active is None:
            return (
                None,
                "error: no active buffer — pass path= to work on a file, "
                "or call open(path) first",
                "",
            )
        return self.active, "", note

    def motion(self, command: str) -> str:
        buf = self.active
        if buf is None:
            return "error: no active buffer — call open(path) first"
        try:
            status, show_col = motion_mod.execute(buf, command)
        except motion_mod.MotionError as e:
            return f"error: {e}"
        return status + "\n" + render(buf, show_column=show_col)

    def edit(self, command: str, path: str | None = None) -> str:
        buf, err, note = self._enter(path)
        if buf is None:
            return err
        try:
            self._check_fresh(buf)
            summary, first, last = edit_mod.execute(buf, command, self.registers)
        except edit_mod.EditError as e:
            return f"error: {e}"
        if first is None:  # yank / register cut: the echo carries the content
            return _with_note(note, summary)
        return _with_note(note, summary + "\n" + render(buf, first=first, last=last))

    def substitute(self, command: str, path: str | None = None) -> str:
        buf, err, note = self._enter(path)
        if buf is None:
            return err
        try:
            self._check_fresh(buf)
            return _with_note(
                note, substitute_mod.execute(buf, command, self.registers)
            )
        except (edit_mod.EditError, substitute_mod.SubstituteError) as e:
            return f"error: {e}"

    def print(self, command: str = "p", path: str | None = None) -> str:
        buf, err, note = self._enter(path)
        if buf is None:
            return err
        try:
            head, first, last = printcmd_mod.execute(buf, command)
        except printcmd_mod.PrintError as e:
            return f"error: {e}"
        return _with_note(
            note, head + "\n" + render(buf, first=first, last=last, context=0)
        )

    def matches(self, pattern: str, context: int = 0, path: str | None = None) -> str:
        buf, err, note = self._enter(path)
        if buf is None:
            return err
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
            return _with_note(note, f"no match: {pattern}")

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
        return _with_note(note, "\n".join(out))

    def write(self, preview: bool = False, path: str | None = None) -> str:
        # No switch note here: every one of write's echoes names the path itself.
        buf, err, _ = self._enter(path)
        if buf is None:
            return err
        try:
            self._check_fresh(buf)
        except edit_mod.EditError as e:
            return f"error: {e}"
        if preview:
            delta = _saved_delta(buf)
            if not delta:
                return f"no unwritten changes — buffer matches {buf.path}"
            head = (
                f"unwritten changes in {buf.path}: {len(delta)} line(s) "
                "differ from disk (nothing written)"
            )
            return head + "\n" + substitute_mod.diff_lines(delta)
        # Defense in depth: a buffer opened under a since-revoked root
        # (client roots/list shrank) must fail loudly instead of writing.
        if not self._contained(buf.path):
            return (
                f"error: {buf.path} is no longer inside the sandbox root(s) "
                f"({self._roots_display()}) — access was revoked; not written"
            )

        changed = len(_saved_delta(buf))
        buf.write()
        return f"wrote {buf.path} ({len(buf.lines)} lines, {changed} line(s) changed)"


def _with_note(note: str, body: str) -> str:
    """Prefix an op's echo with its buffer-switch note, if any. A changed
    active buffer is a state change, so it is never silent."""
    return f"{note}\n{body}" if note else body


def _saved_delta(buf: Buffer) -> list[tuple[int, str | None, str | None]]:
    """Changed-tuples between the on-disk snapshot (saved_lines) and the
    buffer, for diff_lines. Line numbers are disk-side (pre-edit), matching
    the substitute-diff convention. autojunk=False: popular lines (blanks)
    must not wreck alignment (dogfood #4 write-count bug)."""
    delta: list[tuple[int, str | None, str | None]] = []
    sm = difflib.SequenceMatcher(None, buf.saved_lines, buf.lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        olds = buf.saved_lines[i1:i2]
        news = buf.lines[j1:j2]
        for k in range(max(len(olds), len(news))):
            delta.append(
                (
                    i1 + k,
                    olds[k] if k < len(olds) else None,
                    news[k] if k < len(news) else None,
                )
            )
    return delta
