"""The global anchored edit (v0.8): `at each /pattern/ <cmd>` — one edit
command at every match, bottom-up, transactional, diff echo, one undo step —
plus the :g/pat/normal signpost error in substitute."""

from pathlib import Path

import pytest

from djinnvim import substitute
from djinnvim.buffer import Buffer
from djinnvim.edit import EditError, execute
from djinnvim.substitute import SubstituteError


def make(lines, line=0, col=0):
    buf = Buffer(path=Path("test.txt"), lines=list(lines))
    buf.cursor.line, buf.cursor.col = line, col
    return buf


# --- the happy path ---

def test_each_ciw_changes_every_match_including_two_on_one_line():
    buf = make(["foo = 1", "x = foo + foo", "bar = 2"])
    summary, first, last = execute(buf, "at each /foo/ ciw baz")
    assert buf.lines == ["baz = 1", "x = baz + baz", "bar = 2"]
    assert (first, last) == (None, None)  # the diff is the echo
    assert "edited 3 match(es)" in summary
    assert "- 1  foo = 1" in summary
    assert "+ 1  baz = 1" in summary
    assert buf.dirty


def test_each_dd_deletes_every_matching_line():
    buf = make(["keep", "log('a')", "keep2", "log('b')"])
    summary, *_ = execute(buf, "at each /log/ dd")
    assert buf.lines == ["keep", "keep2"]
    assert "edited 2 match(es)" in summary
    assert "- 2  log('a')" in summary
    assert "- 4  log('b')" in summary


def test_each_append_A_with_verbatim_text():
    buf = make(["a()", "b()", "a()"])
    execute(buf, "at each /a\\(\\)/ A  # deprecated")  # one sep + verbatim " # ..."
    assert buf.lines == ["a() # deprecated", "b()", "a() # deprecated"]


def test_each_o_insertion_diff_has_plus_lines_only():
    buf = make(["a", "b a"])
    summary, *_ = execute(buf, "at each /a/ o X")
    assert buf.lines == ["a", "X", "b a", "X"]
    assert "+" in summary
    assert "\n-" not in summary  # pure insertions: no - lines


def test_each_column_precise_not_per_line():
    # the cursor lands at each match start, so r hits the matched char
    buf = make(["ab ab", "ab"])
    execute(buf, "at each /b/ rX")
    assert buf.lines == ["aX aX", "aX"]


# --- failures are loud and total ---

def test_each_zero_matches_is_loud():
    buf = make(["nothing here"])
    with pytest.raises(EditError, match="no match"):
        execute(buf, "at each /absent/ dd")
    assert buf.lines == ["nothing here"]


def test_each_needs_a_command():
    buf = make(["x"])
    with pytest.raises(EditError, match="needs a command"):
        execute(buf, "at each /x/")


@pytest.mark.parametrize("cmd", [
    "at each /a/ yy",
    "at each /a/ yiw",
    "at each /a/ p",
    "at each /a/ u",
    'at each /a/ "r dd',
])
def test_each_rejects_yank_paste_undo_registers(cmd):
    buf = make(["a b a"])
    with pytest.raises(EditError, match="edit commands only"):
        execute(buf, cmd)
    assert buf.lines == ["a b a"]


def test_each_rejects_register_prefix_before_the_form():
    buf = make(["a b a"])
    with pytest.raises(EditError, match="do not compose"):
        execute(buf, '"r at each /a/ dd')
    assert buf.lines == ["a b a"]


def test_each_transactional_rollback_names_the_site():
    buf = make(["foo", "g(foo)"], line=0, col=0)
    # bottom-up: line 2 succeeds (ci( works), then line 1 fails (no parens)
    with pytest.raises(EditError, match=r"line 1: no enclosing.*no changes applied"):
        execute(buf, "at each /foo/ ci( z")
    assert buf.lines == ["foo", "g(foo)"]  # the successful site rolled back too
    assert (buf.cursor.line, buf.cursor.col) == (0, 0)
    assert not buf.undo_stack


# --- overlap: consumed matches are skipped and reported ---

def test_each_dap_consumes_second_marker_in_same_paragraph():
    buf = make(["# D one", "code", "# D two", "more", "", "tail"])
    summary, *_ = execute(buf, "at each /# D/ dap")
    assert buf.lines == ["tail"]
    assert "edited 1 of 2 match(es)" in summary
    assert "1 consumed by earlier edits" in summary


def test_each_dap_separate_paragraphs_all_edited():
    buf = make([
        "# DEPRECATED", "def old():", "    pass", "", "",
        "def keep():", "    pass", "", "",
        "# DEPRECATED", "def old2():", "    pass",
    ])
    summary, *_ = execute(buf, "at each /# DEPRECATED/ dap")
    assert buf.lines == ["def keep():", "    pass"]
    assert "edited 2 match(es)" in summary


# --- the diff echo names exactly what was edited (dogfood #4, bug 1) ---

def test_each_diff_never_misattributes_repeated_lines():
    # difflib-derived diffs may align a deletion onto identical lines of a
    # SURVIVING function (here: its "    pass"), echoing a truthful-but-
    # misleading diff. The echo must name the removed block itself.
    buf = make([
        "def keep():", "    pass", "", "",
        "# DEPRECATED: x", "def dead():", "    pass", "", "",
        "def keep2():", "    pass",
    ])
    summary, *_ = execute(buf, "at each /# DEPRECATED/ dap")
    assert buf.lines == [
        "def keep():", "    pass", "", "", "def keep2():", "    pass",
    ]
    assert "- 5  # DEPRECATED: x" in summary
    assert "- 6  def dead():" in summary
    assert "- 7      pass" in summary
    assert "- 2      pass" not in summary  # keep()'s pass was NOT deleted


# --- undo: the whole batch is one step ---

def test_each_is_one_undo_step():
    buf = make(["foo", "foo", "foo"])
    execute(buf, "at each /foo/ ciw bar")
    assert buf.lines == ["bar", "bar", "bar"]
    summary, *_ = execute(buf, "u")
    assert buf.lines == ["foo", "foo", "foo"]
    assert "at each /foo/ ciw bar" in summary
    assert not buf.undo_stack


def test_each_undo_echo_is_compact_not_a_span_viewport():
    # Undoing a batch must NOT echo a viewport spanning first-to-last site
    # (dogfood #4, bug 2: ~420 lines live — a full-file read in disguise).
    # It echoes the inverted compact diff instead, symmetric with the batch.
    top = ["# DEPRECATED", "def a():", "    return 0", "", ""]
    mid = []
    for i in range(60):
        mid += [f"def keep{i}():", f"    return {i}", "", ""]
    bot = ["# DEPRECATED", "def z():", "    return 9"]
    buf = make(top + mid + bot)
    execute(buf, "at each /# DEPRECATED/ dap")
    summary, first, last = execute(buf, "u")
    assert buf.lines == top + mid + bot
    assert (first, last) == (None, None)  # the diff is the echo, no viewport
    assert "undid: at each /# DEPRECATED/ dap" in summary
    assert "+   1  # DEPRECATED" in summary  # restored lines, post-undo numbering
    assert "+ 246  # DEPRECATED" in summary
    assert "def keep30" not in summary  # untouched middle stays out of the echo
    assert len(summary.splitlines()) < 20


# --- the ex-side signpost ---

def test_g_normal_signpost_points_at_each():
    buf = make(["foo"])
    with pytest.raises(SubstituteError, match=r"at each /foo/ <cmd>"):
        substitute.execute(buf, ":g/foo/normal dd")
    with pytest.raises(SubstituteError, match=r"at each /foo/ <cmd>"):
        substitute.execute(buf, ":g/foo/norm ciw bar")
    assert buf.lines == ["foo"]
