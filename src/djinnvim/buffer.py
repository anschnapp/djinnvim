"""In-memory buffer: list of lines, a cursor, and dirty/staleness tracking."""

import os
import stat as stat_mod
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path


MAX_UNDO = 100  # snapshot stack cap per buffer; oldest steps fall off


@dataclass
class Cursor:
    line: int = 0  # 0-based index into Buffer.lines
    col: int = 0   # 0-based column; only meaningful after column-wise operations


@dataclass
class UndoEntry:
    lines: list[str]   # buffer content before the command
    cursor_line: int   # cursor before the command
    cursor_col: int
    command: str       # the command being undone, for the echo
    # exact changed-tuples of the command (batch edits set this), so undo
    # can echo the inverted compact diff instead of a spanning viewport
    changed: list[tuple[int, str | None, str | None]] | None = None


@dataclass
class Buffer:
    path: Path
    lines: list[str] = field(default_factory=list)
    cursor: Cursor = field(default_factory=Cursor)
    dirty: bool = False
    disk_mtime: float = 0.0
    last_search: str | None = None  # pattern for n/N
    saved_lines: list[str] = field(default_factory=list)  # snapshot at last open/write
    undo_stack: list[UndoEntry] = field(default_factory=list)

    @classmethod
    def open(cls, path: Path) -> "Buffer":
        # A hard kill during a previous write strands a temp next to this
        # file, and only a write of the same file clears it. Opening is the
        # other moment we are certainly interested in this path, so it is
        # where "restart and reopen" gets to clean up.
        _sweep_stranded_temps(path)
        text = path.read_text()
        buf = cls(path=path, lines=text.splitlines())
        buf.disk_mtime = path.stat().st_mtime
        buf.saved_lines = list(buf.lines)
        return buf

    def push_undo(
        self, lines: list[str], cursor: tuple[int, int], command: str,
        changed: list[tuple[int, str | None, str | None]] | None = None,
    ) -> None:
        self.undo_stack.append(UndoEntry(lines, cursor[0], cursor[1], command, changed))
        if len(self.undo_stack) > MAX_UNDO:
            del self.undo_stack[0]

    def stale(self) -> bool:
        """True if the file changed on disk since open/last write."""
        return self.path.stat().st_mtime != self.disk_mtime

    def write(self) -> None:
        _atomic_write(self.path, "\n".join(self.lines) + "\n")
        self.disk_mtime = self.path.stat().st_mtime
        self.saved_lines = list(self.lines)
        self.dirty = False


TMP_SUFFIX = ".djinnvim-tmp"
TMP_STALE_SECONDS = 60.0  # a live temp exists for milliseconds, never a minute


def _sweep_stranded_temps(path: Path) -> None:
    """Delete temps a hard kill stranded next to `path`.

    SIGKILL and power loss run no cleanup code, so the temp for an
    interrupted write survives. Clearing it on the next write of the same
    file keeps the user's tree tidy without a background sweeper.

    Two deliberate narrowings, so this can never eat something live: only
    names carrying *this target's* prefix and our suffix are considered,
    and only if untouched for a minute, which no in-flight write ever is.
    A concurrent writer's temp is therefore safe.
    """
    prefix = f".{path.name}."
    cutoff = time.time() - TMP_STALE_SECONDS
    try:
        entries = list(path.parent.iterdir())
    except OSError:
        return
    for e in entries:
        if not (e.name.startswith(prefix) and e.name.endswith(TMP_SUFFIX)):
            continue
        try:
            if e.stat().st_mtime < cutoff:
                e.unlink()
        except OSError:
            pass  # vanished, or not ours to remove: either way, fine


def _atomic_write(path: Path, text: str) -> None:
    """Write `text` to `path` without ever leaving it truncated: fill a temp
    file, then swap it in with one atomic rename.

    The temp file has to sit in the *target's own directory* - `os.replace`
    is only atomic within a filesystem, so /tmp is not an option - which
    puts it briefly in the user's source tree. Everything below is about
    keeping it out of the way while it is there:

    - Named `.<file>.<random>.djinnvim-tmp`: hidden, obviously transient,
      obviously ours, and unique so concurrent writers cannot collide.
    - Removed on every failure path this process can still run code on. A
      SIGKILL or a power cut cannot clean up, and *does* strand a temp file
      next to the target (measured: 25 of 25 hard kills). The original file
      is still intact, which is the point, but the litter is real, so each
      write first sweeps stranded temps belonging to this same target.
    - Alive for microseconds; a watcher that ignores dotfiles never sees it.

    Two cases keep the old in-place write on purpose, because a rename
    swaps the inode and that is visible to someone else:

    - **Hard links** (`st_nlink > 1`): replacing the inode silently detaches
      every other link, so the file the user edits through another name
      would stop tracking this one.
    - **A file we do not own**: the replacement would be owned by us, so a
      shared file would quietly change hands.

    A failure to *create* the temp (read-only directory holding a writable
    file) also falls back - atomicity is not worth failing a write that the
    old path would have completed. A failure *after* creation never falls
    back: if filling the temp failed (a full disk, most likely), writing in
    place would fail the same way but destructively, which is the whole
    thing we are preventing.
    """
    try:
        st = path.stat()
    except FileNotFoundError:
        st = None  # first write of a buffer whose file was deleted
    if st is not None and (st.st_nlink > 1 or st.st_uid != os.getuid()):
        path.write_text(text)
        return

    _sweep_stranded_temps(path)

    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=TMP_SUFFIX
        )
    except OSError:
        path.write_text(text)  # e.g. read-only dir: in-place is all there is
        return

    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())  # content on disk before the rename claims it
        if st is not None:
            os.chmod(tmp, stat_mod.S_IMODE(st.st_mode))  # mkstemp gives 0600
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
