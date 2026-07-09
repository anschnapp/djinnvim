"""In-memory buffer: list of lines, a cursor, and dirty/staleness tracking."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Cursor:
    line: int = 0  # 0-based index into Buffer.lines
    col: int = 0   # 0-based column; only meaningful after column-wise operations


@dataclass
class Buffer:
    path: Path
    lines: list[str] = field(default_factory=list)
    cursor: Cursor = field(default_factory=Cursor)
    dirty: bool = False
    disk_mtime: float = 0.0
    last_search: str | None = None  # pattern for n/N
    saved_lines: list[str] = field(default_factory=list)  # snapshot at last open/write

    @classmethod
    def open(cls, path: Path) -> "Buffer":
        text = path.read_text()
        buf = cls(path=path, lines=text.splitlines())
        buf.disk_mtime = path.stat().st_mtime
        buf.saved_lines = list(buf.lines)
        return buf

    def stale(self) -> bool:
        """True if the file changed on disk since open/last write."""
        return self.path.stat().st_mtime != self.disk_mtime

    def write(self) -> None:
        self.path.write_text("\n".join(self.lines) + "\n")
        self.disk_mtime = self.path.stat().st_mtime
        self.saved_lines = list(self.lines)
        self.dirty = False
