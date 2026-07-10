"""Registers: :RANGE y NAME (yank), :RANGE d NAME (cut), :RANGE d (plain
delete, no register), :put NAME — and the loud wrong-name recovery."""

from pathlib import Path

import pytest

from djinnvim.buffer import Buffer
from djinnvim.session import Session
from djinnvim.substitute import SubstituteError, execute


def make(lines, line=0, col=0):
    buf = Buffer(path=Path("test.txt"), lines=list(lines))
    buf.cursor.line, buf.cursor.col = line, col
    return buf


LINES = [
    "def helper(x):",       # 1
    "    return x + 1",     # 2
    "",                     # 3
    "def main():",          # 4
    "    print(helper(1))", # 5
    "    return 0",         # 6
]


# --- yank ---

def test_yank_range_into_named_register():
    buf = make(LINES)
    regs = {}
    out = execute(buf, ":1,2y block", regs)
    assert regs["block"] == ["def helper(x):", "    return x + 1"]
    assert out.splitlines()[0] == 'yanked 2 line(s) (1–2) into register "block"'
    assert "  def helper(x):" in out
    assert buf.lines == LINES          # buffer untouched
    assert buf.cursor.line == 0        # cursor unmoved
    assert not buf.dirty


def test_bare_y_yanks_cursor_line_into_unnamed():
    buf = make(LINES, line=3)
    regs = {}
    out = execute(buf, ":y", regs)
    assert regs[""] == ["def main():"]
    assert "into the unnamed register" in out


def test_yank_pattern_range():
    buf = make(LINES)
    regs = {}
    execute(buf, ":/def helper/,/^$/y block", regs)
    assert regs["block"] == ["def helper(x):", "    return x + 1", ""]


def test_yank_percent_range():
    buf = make(LINES)
    regs = {}
    execute(buf, ":%y all", regs)
    assert regs["all"] == LINES


# --- cut and plain delete ---

def test_cut_stores_and_deletes():
    buf = make(LINES)
    regs = {}
    out = execute(buf, ":1,3d block", regs)
    assert regs["block"] == ["def helper(x):", "    return x + 1", ""]
    assert buf.lines == LINES[3:]
    assert (buf.cursor.line, buf.cursor.col) == (0, 0)
    assert buf.dirty
    assert out.splitlines()[0] == 'cut 3 line(s) (1–3) into register "block"'


def test_plain_range_delete_never_touches_registers():
    buf = make(LINES)
    regs = {"block": ["precious"]}
    out = execute(buf, ":3,4d", regs)
    assert regs == {"block": ["precious"]}  # anti-clobber rule
    assert buf.lines == LINES[:2] + LINES[4:]
    assert "not saved to a register" in out


def test_cut_whole_buffer_leaves_empty_line():
    buf = make(LINES)
    regs = {}
    execute(buf, ":%d all", regs)
    assert buf.lines == [""]
    assert regs["all"] == LINES


# --- put ---

def test_put_inserts_below_cursor_and_moves_cursor():
    buf = make(LINES, line=5)
    regs = {"block": ["# moved", "# here"]}
    out = execute(buf, ":put block", regs)
    assert buf.lines[6:8] == ["# moved", "# here"]
    assert (buf.cursor.line, buf.cursor.col) == (7, 0)
    assert buf.dirty
    assert out.splitlines()[0] == 'put 2 line(s) from register "block" below line 6'
    assert "→" in out  # standard post-edit viewport


def test_bare_put_uses_unnamed_register():
    buf = make(LINES, line=0)
    regs = {"": ["yanked line"]}
    execute(buf, ":put", regs)
    assert buf.lines[1] == "yanked line"


def test_put_rejects_range():
    buf = make(LINES)
    with pytest.raises(SubstituteError, match="put takes no range"):
        execute(buf, ":5put block", {"block": ["x"]})


def test_put_unknown_name_lists_registers_with_previews():
    buf = make(LINES)
    regs = {"block": ["def helper(x):", "    return x + 1"], "": ["one liner"]}
    with pytest.raises(SubstituteError) as e:
        execute(buf, ":put blok", regs)
    msg = str(e.value)
    assert 'no register "blok"' in msg
    assert '"block": def helper(x): ... (2 lines)' in msg
    assert "(unnamed): one liner" in msg
    assert buf.lines == LINES  # buffer untouched


def test_bare_put_with_nothing_yanked():
    buf = make(LINES)
    with pytest.raises(SubstituteError, match="unnamed register is empty"):
        execute(buf, ":put", {})


# --- previews ---

def test_long_block_preview_is_elided():
    lines = [f"line {i}" for i in range(1, 21)]
    buf = make(lines)
    regs = {}
    out = execute(buf, ":%y big", regs)
    assert "  line 1" in out
    assert "  ... 14 more line(s) ..." in out
    assert "  line 20" in out
    assert "line 10" not in out
    assert regs["big"] == lines  # register holds the full text regardless


def test_short_block_preview_shown_in_full():
    buf = make(LINES)
    out = execute(buf, ":1,6y all", {})
    for line in LINES:
        if line:
            assert f"  {line}" in out
    assert "more line(s)" not in out


# --- session integration ---

def test_registers_survive_across_buffers(tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("keep = 1\nmove_me = 2\n")
    b.write_text("target = 3\n")
    s = Session(root=tmp_path)

    s.open("a.py")
    out = s.substitute(":2,2d block")
    assert 'cut 1 line(s) (2–2) into register "block"' in out

    s.open("b.py")
    out = s.substitute(":put block")
    assert "put 1 line(s)" in out
    s.write()
    assert b.read_text() == "target = 3\nmove_me = 2\n"


def test_session_error_string_for_unknown_register(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    s = Session(root=tmp_path)
    s.open("a.py")
    out = s.substitute(":put nope")
    assert out.startswith("error: ")
    assert "no registers set" in out
