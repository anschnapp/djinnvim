from pathlib import Path

import pytest

from keyhole.buffer import Buffer
from keyhole.edit import EditError, execute, find_object


def make(lines, line=0, col=0):
    buf = Buffer(path=Path("test.txt"), lines=list(lines))
    buf.cursor.line, buf.cursor.col = line, col
    return buf


# --- word objects ---

def test_ciw():
    buf = make(["old_name = 1"], col=2)
    summary, first, last = execute(buf, "ciw new_name")
    assert buf.lines == ["new_name = 1"]
    assert summary == "changed line 1"
    assert (first, last) == (0, 0)
    assert buf.cursor.col == 0
    assert buf.dirty


def test_caw_takes_trailing_space():
    buf = make(["foo bar baz"], col=4)
    execute(buf, "caw x")
    assert buf.lines == ["foo xbaz"]


def test_diw():
    buf = make(["foo bar baz"], col=4)
    execute(buf, "diw")
    assert buf.lines == ["foo  baz"]


def test_word_object_needs_word_under_cursor():
    buf = make(["foo bar"], col=3)  # on the space
    with pytest.raises(EditError, match="no word under cursor"):
        execute(buf, "ciw x")
    assert buf.lines == ["foo bar"]


# --- bracket objects ---

def test_ci_paren_innermost_enclosing():
    buf = make(["f(g(x), y)"], col=4)
    execute(buf, "ci( z")
    assert buf.lines == ["f(g(z), y)"]


def test_ci_paren_cursor_on_open_bracket():
    buf = make(["f(g(x), y)"], col=3)  # on the inner (
    execute(buf, "ci( z")
    assert buf.lines == ["f(g(z), y)"]


def test_ci_paren_outer_when_cursor_outside_inner_pair():
    buf = make(["f(g(x), y)"], col=8)  # on y
    execute(buf, "ci( z")
    assert buf.lines == ["f(z)"]


def test_da_bracket():
    buf = make(["a = [1, 2, 3] + b"], col=6)
    execute(buf, "da[")
    assert buf.lines == ["a =  + b"]


def test_ci_close_alias():
    buf = make(["f(x)"], col=2)
    execute(buf, "ci) y")
    assert buf.lines == ["f(y)"]


def test_no_enclosing_bracket_is_loud():
    buf = make(["plain line"], col=0)
    with pytest.raises(EditError, match=r"no enclosing \( on line"):
        execute(buf, "ci( x")


# --- quote objects ---

def test_ci_quote_enclosing():
    buf = make(['say("hello", "world")'], col=6)
    execute(buf, 'ci" bye')
    assert buf.lines == ['say("bye", "world")']


def test_ci_quote_next_pair_when_not_inside():
    buf = make(['x = 1  # then "quoted"'], col=0)
    execute(buf, 'ci" q')
    assert buf.lines == ['x = 1  # then "q"']


def test_quote_respects_escapes():
    buf = make([r'a = "he said \"hi\" ok"'], col=6)
    execute(buf, 'di"')
    assert buf.lines == ['a = ""']


def test_no_quote_pair_is_loud():
    buf = make(["no quotes here"], col=0)
    with pytest.raises(EditError, match="no \"...\" pair"):
        execute(buf, 'ci" x')


# --- line commands ---

def test_dd():
    buf = make(["one", "two", "three"], line=1)
    summary, first, last = execute(buf, "dd")
    assert buf.lines == ["one", "three"]
    assert summary == "deleted line 2"
    assert buf.cursor.line == 1


def test_dd_last_line_clamps_cursor():
    buf = make(["one", "two"], line=1)
    execute(buf, "dd")
    assert buf.lines == ["one"]
    assert buf.cursor.line == 0


def test_dd_only_line_leaves_empty_buffer_line():
    buf = make(["only"])
    execute(buf, "dd")
    assert buf.lines == [""]


def test_cc():
    buf = make(["one", "two", "three"], line=1)
    execute(buf, "cc TWO")
    assert buf.lines == ["one", "TWO", "three"]


def test_cc_multiline():
    buf = make(["a", "b"], line=0)
    summary, first, last = execute(buf, "cc x\ny")
    assert buf.lines == ["x", "y", "b"]
    assert (first, last) == (0, 1)


def test_o_inserts_below_and_moves_cursor():
    buf = make(["one", "two"], line=0)
    summary, first, last = execute(buf, "o added")
    assert buf.lines == ["one", "added", "two"]
    assert buf.cursor.line == 1
    assert (first, last) == (1, 1)


def test_o_multiline():
    buf = make(["one"], line=0)
    execute(buf, "o a\nb")
    assert buf.lines == ["one", "a", "b"]
    assert buf.cursor.line == 2


def test_o_bare_inserts_blank_line():
    buf = make(["one"], line=0)
    execute(buf, "o")
    assert buf.lines == ["one", ""]


def test_O_inserts_above():
    buf = make(["one", "two"], line=1)
    execute(buf, "O middle")
    assert buf.lines == ["one", "middle", "two"]
    assert buf.cursor.line == 1


def test_o_preserves_indentation_after_separator():
    buf = make(["def f():"], line=0)
    execute(buf, "o     return 1")
    assert buf.lines == ["def f():", "    return 1"]


def test_A_appends():
    # one space separates the command from TEXT; the rest is verbatim
    buf = make(["x = 1"], line=0)
    execute(buf, "A  # comment")
    assert buf.lines == ["x = 1 # comment"]


def test_I_inserts_at_first_non_blank():
    buf = make(["    return x"], line=0)
    execute(buf, "I # ")
    assert buf.lines == ["    # return x"]


def test_A_needs_text():
    buf = make(["x"], line=0)
    with pytest.raises(EditError, match="A needs TEXT"):
        execute(buf, "A")


def test_D_deletes_to_eol():
    buf = make(["keep this DELETE"], col=10)
    execute(buf, "D")
    assert buf.lines == ["keep this "]


def test_C_changes_to_eol():
    buf = make(["x = old_value"], col=4)
    execute(buf, "C 42")
    assert buf.lines == ["x = 42"]


# --- char commands ---

def test_x():
    buf = make(["abc"], col=1)
    execute(buf, "x")
    assert buf.lines == ["ac"]


def test_x_on_empty_line_is_loud():
    buf = make([""], col=0)
    with pytest.raises(EditError, match="no character under cursor"):
        execute(buf, "x")


def test_r():
    buf = make(["abc"], col=1)
    execute(buf, "rX")
    assert buf.lines == ["aXc"]


# --- anchored form ---

def test_anchored_edit():
    buf = make(["aaa", "old = 1", "bbb"])
    summary, first, last = execute(buf, "at /old/ ciw new")
    assert buf.lines == ["aaa", "new = 1", "bbb"]
    assert buf.cursor.line == 1


def test_anchored_ordinal():
    buf = make(["x = foo(foo)", "foo = 2"])
    execute(buf, "at 2nd /foo/ ciw bar")
    assert buf.lines == ["x = foo(bar)", "foo = 2"]


def test_anchored_no_match_restores_cursor():
    buf = make(["one", "two"], line=1, col=2)
    with pytest.raises(EditError, match="no match: zzz"):
        execute(buf, "at /zzz/ dd")
    assert (buf.cursor.line, buf.cursor.col) == (1, 2)
    assert buf.lines == ["one", "two"]
    assert not buf.dirty


def test_anchored_needs_command():
    buf = make(["one"])
    with pytest.raises(EditError, match="anchored form needs a command"):
        execute(buf, "at /one/")


def test_failed_object_after_anchor_restores_cursor():
    buf = make(["target here"], col=0)
    with pytest.raises(EditError, match="no enclosing"):
        execute(buf, "at /here/ ci( x")
    assert buf.cursor.col == 0


# --- parse errors ---

def test_change_without_text_is_loud():
    buf = make(["word"])
    with pytest.raises(EditError, match="needs TEXT"):
        execute(buf, "ciw")


def test_delete_with_text_is_loud():
    buf = make(["word"])
    with pytest.raises(EditError, match="takes no TEXT"):
        execute(buf, "diw oops")


def test_unknown_command():
    buf = make(["word"])
    with pytest.raises(EditError, match="unknown edit command"):
        execute(buf, "5dd")


# --- find_object unit ---

def test_find_object_inner_vs_around_quote():
    line = 'x = "abc"'
    assert find_object(line, 5, '"', around=False) == (5, 8)
    assert find_object(line, 5, '"', around=True) == (4, 9)
