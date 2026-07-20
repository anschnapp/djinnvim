"""Undo: `u` in edit — one buffer change per step, snapshots pushed by both
edit and substitute mutations, crosses write boundaries, no redo. Registers
deliberately survive undo (vim semantics)."""

from pathlib import Path

import pytest

from djinnvim.buffer import Buffer, MAX_UNDO
from djinnvim.edit import EditError, execute
from djinnvim.session import Session
from djinnvim.substitute import execute as ex_execute


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


# --- basics ---

def test_undo_reverts_edit_and_cursor():
    buf = make(LINES, line=1, col=4)
    execute(buf, "dd")
    assert len(buf.lines) == 5
    summary, first, last = execute(buf, "u")
    assert buf.lines == LINES
    assert (buf.cursor.line, buf.cursor.col) == (1, 4)
    assert summary.startswith("undid: dd")
    assert (first, last) == (1, 1)


def test_undo_names_the_undone_command():
    buf = make(LINES)
    execute(buf, "at /helper/ ciw assist")
    summary, _, _ = execute(buf, "u")
    assert "at /helper/ ciw assist" in summary


def test_undo_steps_back_one_change_at_a_time():
    buf = make(LINES)
    execute(buf, "at /helper\\(x\\)/ ciw assist")
    execute(buf, "at /return 0/ cc     return 1")
    execute(buf, "u")
    assert buf.lines[5] == "    return 0"
    assert buf.lines[0] == "def assist(x):"
    execute(buf, "u")
    assert buf.lines == LINES


def test_undo_empty_stack_fails_loudly():
    buf = make(LINES)
    with pytest.raises(EditError, match="nothing to undo"):
        execute(buf, "u")


def test_undo_summary_reports_remaining_steps():
    buf = make(LINES)
    execute(buf, "dd")
    execute(buf, "dd")
    summary, _, _ = execute(buf, "u")
    assert "1 more undo step" in summary
    summary, _, _ = execute(buf, "u")
    assert "more undo step" not in summary


def test_failed_command_pushes_nothing():
    buf = make(LINES)
    execute(buf, "dd")
    with pytest.raises(EditError):
        execute(buf, "at /nowhere-to-be-found/ ciw x")
    execute(buf, "u")
    assert buf.lines == LINES


def test_yank_pushes_nothing():
    buf = make(LINES)
    execute(buf, "dd")
    regs = {}
    execute(buf, "yy", regs)
    execute(buf, "u", regs)
    assert buf.lines == LINES


def test_undo_restores_multiline_delete():
    buf = make(LINES, line=0)
    execute(buf, "dap")
    assert buf.lines[0] == "def main():"
    _, first, last = execute(buf, "u")
    assert buf.lines == LINES
    assert (first, last) == (0, 2)


def test_undo_of_insert_shrinks_buffer():
    buf = make(LINES, line=5)
    execute(buf, "o     # done")
    assert len(buf.lines) == 7
    execute(buf, "u")
    assert buf.lines == LINES


# --- substitute integration ---

def test_substitute_is_one_undo_step():
    buf = make(LINES)
    ex_execute(buf, ":%s/helper/assist/g")
    summary, _, _ = execute(buf, "u")
    assert buf.lines == LINES
    assert ":%s/helper/assist/g" in summary


def test_global_delete_is_one_undo_step():
    buf = make(LINES)
    ex_execute(buf, ":g/return/d")
    assert len(buf.lines) == 4
    execute(buf, "u")
    assert buf.lines == LINES


def test_ex_yank_pushes_nothing():
    buf = make(LINES)
    execute(buf, "dd")
    ex_execute(buf, ":1,2y block", {})
    execute(buf, "u")
    assert buf.lines == LINES


# --- registers survive undo ---

def test_undo_of_register_cut_keeps_the_register():
    buf = make(LINES)
    regs = {}
    execute(buf, '"fn dd', regs)
    execute(buf, "u", regs)
    assert buf.lines == LINES
    assert regs["fn"].lines == ["def helper(x):"]


def test_register_prefix_on_u_fails_loudly():
    buf = make(LINES)
    execute(buf, "dd")
    with pytest.raises(EditError):
        execute(buf, '"fn u')


# --- dirty flag & write boundary (via Session) ---

@pytest.fixture
def sess(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("\n".join(LINES) + "\n")
    s = Session(roots=[tmp_path])
    s.open("code.py")
    return s


def test_undo_to_saved_state_clears_dirty(sess):
    sess.edit("dd")
    assert sess.active.dirty
    sess.edit("u")
    assert not sess.active.dirty


def test_undo_crosses_write_and_marks_dirty(sess):
    sess.edit("at /return 0/ cc     return 1")
    sess.write()
    assert not sess.active.dirty
    out = sess.edit("u")
    assert not out.startswith("error")
    assert sess.active.lines[5] == "    return 0"
    assert sess.active.dirty  # buffer now differs from what was written
    assert "wrote" in sess.write()
    assert not sess.active.dirty


def test_undo_stack_is_capped():
    buf = make(["x = 0"])
    for i in range(MAX_UNDO + 10):
        execute(buf, f"cc x = {i + 1}")
    for _ in range(MAX_UNDO):
        execute(buf, "u")
    with pytest.raises(EditError, match="nothing to undo"):
        execute(buf, "u")
    assert buf.lines == ["x = 10"]  # the 10 oldest steps fell off
