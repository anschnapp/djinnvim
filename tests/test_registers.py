"""Registers, both surfaces: normal-mode (yy / y-objects / "name dd cuts /
p / P — the primary) and the ex-range fallback (:RANGE y NAME, :RANGE d
NAME), plus the anti-clobber rule and the loud wrong-name recovery."""

from pathlib import Path

import pytest

from djinnvim import edit as edit_mod
from djinnvim.buffer import Buffer
from djinnvim.edit import EditError
from djinnvim.registers import Register
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


# --- ex-range yank (fallback surface) ---

def test_ex_yank_range_into_named_register():
    buf = make(LINES)
    regs = {}
    out = execute(buf, ":1,2y block", regs)
    assert regs["block"].lines == ["def helper(x):", "    return x + 1"]
    assert regs["block"].linewise
    assert out.splitlines()[0] == 'yanked 2 line(s) (1–2) into register "block"'
    assert "  def helper(x):" in out
    assert buf.lines == LINES          # buffer untouched
    assert buf.cursor.line == 0        # cursor unmoved
    assert not buf.dirty


def test_ex_bare_y_yanks_cursor_line_into_unnamed():
    buf = make(LINES, line=3)
    regs = {}
    out = execute(buf, ":y", regs)
    assert regs[""].lines == ["def main():"]
    assert "into the unnamed register" in out


def test_ex_yank_pattern_range():
    buf = make(LINES)
    regs = {}
    execute(buf, ":/def helper/,/^$/y block", regs)
    assert regs["block"].lines == ["def helper(x):", "    return x + 1", ""]


# --- ex-range cut and plain delete ---

def test_ex_cut_stores_and_deletes():
    buf = make(LINES)
    regs = {}
    out = execute(buf, ":1,3d block", regs)
    assert regs["block"].lines == ["def helper(x):", "    return x + 1", ""]
    assert buf.lines == LINES[3:]
    assert (buf.cursor.line, buf.cursor.col) == (0, 0)
    assert buf.dirty
    assert out.splitlines()[0] == 'cut 3 line(s) (1–3) into register "block"'


def test_ex_plain_range_delete_never_touches_registers():
    buf = make(LINES)
    regs = {"block": Register(["precious"])}
    out = execute(buf, ":3,4d", regs)
    assert regs["block"].lines == ["precious"]  # anti-clobber rule
    assert buf.lines == LINES[:2] + LINES[4:]
    assert "not saved to a register" in out


def test_ex_put_is_gone():
    buf = make(LINES)
    with pytest.raises(SubstituteError, match="paste with p/P in edit"):
        execute(buf, ":put block", {"block": Register(["x"])})


# --- normal-mode yank ---

def test_yy_yanks_cursor_line():
    buf = make(LINES, line=3)
    regs = {}
    out, first, last = edit_mod.execute(buf, "yy", regs)
    assert regs[""].lines == ["def main():"]
    assert regs[""].linewise
    assert (first, last) == (None, None)   # no viewport: echo carries content
    assert out.splitlines()[0] == "yanked line 4 into the unnamed register"
    assert "  def main():" in out
    assert buf.lines == LINES and not buf.dirty
    assert buf.cursor.line == 3            # yank never moves the cursor


def test_named_yy_word_register():
    buf = make(LINES)
    regs = {}
    out, _, _ = edit_mod.execute(buf, '"block yy', regs)
    assert regs["block"].lines == ["def helper(x):"]
    assert 'into register "block"' in out


def test_vim_style_single_letter_register_without_space():
    buf = make(LINES)
    regs = {}
    edit_mod.execute(buf, '"ayy', regs)
    assert regs["a"].lines == ["def helper(x):"]


def test_yiw_is_charwise():
    buf = make(LINES, line=0, col=4)  # on "helper"
    regs = {}
    out, first, _ = edit_mod.execute(buf, '"fn yiw', regs)
    assert regs["fn"].lines == ["helper"]
    assert not regs["fn"].linewise
    assert 'yanked "helper" into register "fn"' in out
    assert first is None
    assert not buf.dirty


def test_yap_yanks_paragraph():
    buf = make(LINES, line=0)
    regs = {}
    out, _, _ = edit_mod.execute(buf, '"top yap', regs)
    # paragraph = lines 1-2, ap takes the trailing blank line 3
    assert regs["top"].lines == LINES[:3]
    assert regs["top"].linewise
    assert "yanked 3 line(s) (1–3)" in out
    assert buf.lines == LINES


def test_yip_excludes_trailing_blank():
    buf = make(LINES, line=1)
    regs = {}
    edit_mod.execute(buf, "yip", regs)
    assert regs[""].lines == LINES[:2]


def test_anchored_yank_composes():
    buf = make(LINES)
    regs = {}
    out, _, _ = edit_mod.execute(buf, 'at /def main/ "block yap', regs)
    # last paragraph: nothing trails, so ap takes the leading blank line
    assert regs["block"].lines == LINES[2:6]
    assert "(match 1 of 1)" in out.splitlines()[0]


def test_register_prefix_before_anchor_also_works():
    buf = make(LINES)
    regs = {}
    edit_mod.execute(buf, '"block at /def main/ yap', regs)
    assert regs["block"].lines == LINES[2:6]


def test_yank_takes_no_text():
    buf = make(LINES)
    with pytest.raises(EditError, match="takes no TEXT"):
        edit_mod.execute(buf, "yy oops", {})


# --- normal-mode cut (explicit register only) ---

def test_named_dd_cuts_line():
    buf = make(LINES, line=2)
    regs = {}
    out, first, _ = edit_mod.execute(buf, '"gap dd', regs)
    assert regs["gap"].lines == [""]
    assert buf.lines == LINES[:2] + LINES[3:]
    assert buf.dirty
    assert first is None
    assert out.splitlines()[0] == 'cut line 3 into register "gap"'


def test_named_dap_cuts_paragraph():
    buf = make(LINES, line=4)
    regs = {}
    out, _, _ = edit_mod.execute(buf, '"fn dap', regs)
    # ap on the last paragraph: no trailing blank, takes the leading one
    assert regs["fn"].lines == LINES[2:6]
    assert buf.lines == LINES[:2]
    assert "cut 4 line(s) (3–6)" in out


def test_named_diw_cuts_charwise():
    buf = make(LINES, line=0, col=4)
    regs = {}
    out, first, last = edit_mod.execute(buf, '"w diw', regs)
    assert regs["w"].lines == ["helper"]
    assert not regs["w"].linewise
    assert buf.lines[0] == "def (x):"
    assert (first, last) == (0, 0)  # line edit: normal viewport echo
    assert 'cut "helper" into register "w"' in out


def test_bare_dd_never_touches_registers():
    buf = make(LINES)
    regs = {"block": Register(["precious"])}
    edit_mod.execute(buf, "dd", regs)
    assert regs["block"].lines == ["precious"]
    assert "" not in regs  # anti-clobber: plain deletes write nothing


def test_register_prefix_rejects_non_ydp_commands():
    buf = make(LINES)
    with pytest.raises(EditError, match="applies to y"):
        edit_mod.execute(buf, '"x cc hello', {})


# --- paste ---

def test_p_pastes_linewise_below_and_moves_cursor():
    buf = make(LINES, line=5)
    regs = {"block": Register(["# moved", "# here"])}
    out, first, last = edit_mod.execute(buf, '"block p', regs)
    assert buf.lines[6:8] == ["# moved", "# here"]
    assert (buf.cursor.line, buf.cursor.col) == (7, 0)
    assert buf.dirty
    assert (first, last) == (6, 7)
    assert out.splitlines()[0] == (
        'pasted 2 line(s) from register "block" below line 6'
    )


def test_P_pastes_linewise_above():
    buf = make(LINES, line=0)
    regs = {"block": Register(["# top"])}
    _, first, last = edit_mod.execute(buf, '"block P', regs)
    assert buf.lines[0] == "# top"
    assert (first, last) == (0, 0)


def test_bare_p_uses_unnamed_register():
    buf = make(LINES, line=0)
    regs = {"": Register(["yanked line"])}
    edit_mod.execute(buf, "p", regs)
    assert buf.lines[1] == "yanked line"


def test_charwise_paste_inserts_after_cursor():
    buf = make(["retries = old"], col=10)  # on the 'o' of old
    regs = {"v": Register(["N"], linewise=False)}
    out, _, _ = edit_mod.execute(buf, '"v p', regs)
    assert buf.lines[0] == "retries = oNld"
    assert 'pasted "N"' in out


def test_charwise_paste_P_at_cursor():
    buf = make(["retries = old"], col=10)
    regs = {"v": Register(["N"], linewise=False)}
    edit_mod.execute(buf, '"v P', regs)
    assert buf.lines[0] == "retries = Nold"


def test_yiw_then_p_round_trip():
    buf = make(["name = value"], col=0)
    regs = {}
    edit_mod.execute(buf, "yiw", regs)          # charwise "name"
    buf.cursor.col = 11                          # on the 'e' of value
    edit_mod.execute(buf, "p", regs)
    assert buf.lines[0] == "name = valuename"


def test_p_unknown_name_lists_registers_with_previews():
    buf = make(LINES)
    regs = {
        "block": Register(["def helper(x):", "    return x + 1"]),
        "": Register(["one liner"]),
    }
    with pytest.raises(EditError) as e:
        edit_mod.execute(buf, '"blok p', regs)
    msg = str(e.value)
    assert 'no register "blok"' in msg
    assert '"block": def helper(x): ... (2 lines)' in msg
    assert "(unnamed): one liner" in msg
    assert buf.lines == LINES  # buffer untouched


def test_bare_p_with_nothing_yanked():
    buf = make(LINES)
    with pytest.raises(EditError, match="unnamed register is empty"):
        edit_mod.execute(buf, "p", {})


# --- plain paragraph objects (no register) ---

def test_dap_plain_delete():
    buf = make(LINES, line=0)
    out, first, last = edit_mod.execute(buf, "dap", {})
    assert buf.lines == LINES[3:]
    assert "deleted lines 1–3" in out
    assert (first, last) == (0, 0)


def test_cip_removed_and_signposts_the_two_step():
    # v0.18: cip/cap dropped — a multi-line paragraph replacement was the one
    # place with no good answer to "how is this indented", and no dogfood ever
    # used it. dip/dap stay.
    buf = make(LINES, line=4)
    before = list(buf.lines)
    with pytest.raises(edit_mod.EditError) as e:
        edit_mod.execute(buf, "cip pass", {})
    assert "cip is not supported" in str(e.value)
    assert "dip" in str(e.value)
    assert buf.lines == before


def test_ap_on_blank_line_takes_next_paragraph():
    buf = make(LINES, line=2)
    regs = {}
    edit_mod.execute(buf, "yap", regs)
    assert regs[""].lines == LINES[2:6]


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
    assert regs["big"].lines == lines  # register holds the full text regardless


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
    s = Session(roots=[tmp_path])

    s.open("a.py")
    out = s.substitute(":2,2d block")
    assert 'cut 1 line(s) (2–2) into register "block"' in out

    s.open("b.py")
    out = s.edit('"block p')
    assert "pasted 1 line(s)" in out
    assert "→" in out  # standard post-edit viewport
    s.write()
    assert b.read_text() == "target = 3\nmove_me = 2\n"


def test_normal_mode_move_within_file(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("def a():\n    pass\n\ndef b():\n    pass\n")
    s = Session(roots=[tmp_path])
    s.open("a.py")
    out = s.edit('at /def a/ "fn dap')
    assert 'cut 3 line(s) (1–3) into register "fn"' in out
    s.motion("G")
    s.edit('"fn p')
    s.write()
    assert f.read_text() == "def b():\n    pass\ndef a():\n    pass\n\n"


def test_session_error_string_for_unknown_register(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    s = Session(roots=[tmp_path])
    s.open("a.py")
    out = s.edit('"nope p')
    assert out.startswith("error: ")
    assert "no registers set" in out
