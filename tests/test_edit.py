from pathlib import Path

import pytest

from djinnvim.buffer import Buffer
from djinnvim.edit import EditError, execute, find_object


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


def test_o_trailing_newline_is_literal():
    # v0.15: every `\n` is literal (vim-exact, no terminator stripping) —
    # one trailing `\n` is one Enter press, leaving one blank line.
    buf = make(["one"], line=0)
    execute(buf, "o added\n")
    assert buf.lines == ["one", "added", ""]


def test_o_extra_trailing_newlines_are_blank_lines():
    buf = make(["one"], line=0)
    execute(buf, "o added\n\n")
    assert buf.lines == ["one", "added", "", ""]
    assert buf.cursor.line == 3


def test_O_trailing_blank_kept():
    buf = make(["target"], line=0)
    execute(buf, "O block\n\n")
    assert buf.lines == ["block", "", "", "target"]


def test_O_inserts_above():
    buf = make(["one", "two"], line=1)
    execute(buf, "O middle")
    assert buf.lines == ["one", "middle", "two"]
    assert buf.cursor.line == 1


def test_o_preserves_indentation_after_separator():
    buf = make(["def f():"], line=0)
    execute(buf, "o     return 1")
    assert buf.lines == ["def f():", "    return 1"]


# --- v0.15: o/O indent-inherit + bang opt-out ---


def test_o_inherits_reference_indent():
    buf = make(["def foo():", "    pass"], line=1)
    execute(buf, "o return 2")
    assert buf.lines == ["def foo():", "    pass", "    return 2"]


def test_o_own_leading_space_is_relative():
    buf = make(["def foo():", "    pass"], line=1)
    execute(buf, "o   return 2")
    assert buf.lines == ["def foo():", "    pass", "      return 2"]


def test_O_inherits_reference_indent():
    buf = make(["    pass"], line=0)
    execute(buf, "O x = 1")
    assert buf.lines == ["    x = 1", "    pass"]


def test_o_bang_opts_out_of_indent():
    buf = make(["    pass"], line=0)
    execute(buf, "o! return 2")
    assert buf.lines == ["    pass", "return 2"]


def test_O_bang_opts_out_of_indent():
    buf = make(["    pass"], line=0)
    execute(buf, "O! x = 1")
    assert buf.lines == ["x = 1", "    pass"]


def test_o_indent_walks_up_past_blank_line():
    buf = make(["    def foo():", "        pass", ""], line=2)
    execute(buf, "o next")
    assert buf.lines == ["    def foo():", "        pass", "", "        next"]


def test_o_blank_lines_in_text_stay_unindented():
    buf = make(["    pass"], line=0)
    execute(buf, "o one\n\ntwo")
    assert buf.lines == ["    pass", "    one", "", "    two"]


# --- v0.15: blank-run fact on o/O ---


def test_o_blank_run_note():
    buf = make(["a", "", "b"], line=0)
    summary, _, _ = execute(buf, "o x")
    assert "0 blank line(s) above insertion point, 1 below" in summary


def test_O_blank_run_note():
    buf = make(["a", "", "b"], line=2)
    summary, _, _ = execute(buf, "O x")
    assert "1 blank line(s) above insertion point, 0 below" in summary


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


def test_i_inserts_before_cursor_char():
    buf = make(["retries(15)"], col=8)  # cursor on the 1
    execute(buf, "i limit=")
    assert buf.lines == ["retries(limit=15)"]


def test_i_anchored_inserts_before_match():
    buf = make(["def f(x):", "    call(x)"])
    execute(buf, "at /x\\)$/ i logger, ")
    assert buf.lines == ["def f(x):", "    call(logger, x)"]


def test_a_appends_after_cursor_char():
    # vim semantics: after the cursor char — anchored, after the match's FIRST char
    buf = make(["f(x)"], col=2)  # cursor on x
    execute(buf, "a , y")
    assert buf.lines == ["f(x, y)"]


def test_a_on_empty_line():
    buf = make([""], line=0)
    execute(buf, "a text")
    assert buf.lines == ["text"]


def test_i_and_a_need_text():
    buf = make(["x"], line=0)
    with pytest.raises(EditError, match="i needs TEXT"):
        execute(buf, "i")
    with pytest.raises(EditError, match="a needs TEXT"):
        execute(buf, "a")


def test_i_text_is_verbatim_after_separator():
    buf = make(["xy"], col=1)
    execute(buf, "i   ")  # inserts two spaces (first space is the separator)
    assert buf.lines == ["x  y"]


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


# --- surround ---

def test_cs_quote_to_quote():
    buf = make(['x = "hello"'], col=6)
    summary, first, last = execute(buf, "cs\"'")
    assert buf.lines == ["x = 'hello'"]
    assert summary == "changed surround \" → ' on line 1"
    assert (first, last) == (0, 0)


def test_cs_quote_to_open_bracket_pads():
    buf = make(['x = "hello"'], col=6)
    execute(buf, 'cs"(')
    assert buf.lines == ["x = ( hello )"]


def test_cs_quote_to_close_bracket_no_pad():
    buf = make(['x = "hello"'], col=6)
    execute(buf, 'cs")')
    assert buf.lines == ["x = (hello)"]


def test_cs_open_bracket_target_trims_inner_space():
    buf = make(["x = ( hello )"], col=7)
    execute(buf, 'cs("')
    assert buf.lines == ['x = "hello"']


def test_cs_no_pair_is_loud():
    buf = make(["plain"], col=0)
    with pytest.raises(EditError, match="no \"...\" pair"):
        execute(buf, "cs\"'")
    assert buf.lines == ["plain"]


def test_cs_bad_target_is_loud():
    buf = make(["plain"], col=0)
    with pytest.raises(EditError, match="unsupported surround target"):
        execute(buf, "csx'")


def test_ds_quote():
    buf = make(['x = "hello" + y'], col=6)
    summary, _, _ = execute(buf, 'ds"')
    assert buf.lines == ["x = hello + y"]
    assert summary == 'deleted surround " on line 1'


def test_ds_open_bracket_trims_inner_space():
    buf = make(["f( x )"], col=3)
    execute(buf, "ds(")
    assert buf.lines == ["fx"]


def test_ysiw_quote():
    buf = make(["say hello now"], col=5)
    summary, _, _ = execute(buf, 'ysiw"')
    assert buf.lines == ['say "hello" now']
    assert summary == 'surrounded word with " on line 1'
    assert buf.cursor.col == 4


def test_ysiw_open_bracket_pads():
    buf = make(["say hello now"], col=5)
    execute(buf, "ysiw(")
    assert buf.lines == ["say ( hello ) now"]


def test_ysiw_needs_word_under_cursor():
    buf = make(["a  b"], col=1)
    with pytest.raises(EditError, match="no word under cursor"):
        execute(buf, 'ysiw"')


# --- anchored form ---

def test_anchored_edit():
    buf = make(["aaa", "old = 1", "bbb"])
    summary, first, last = execute(buf, "at /old/ ciw new")
    assert buf.lines == ["aaa", "new = 1", "bbb"]
    assert buf.cursor.line == 1
    assert summary == "changed line 2 (match 1 of 1)"


def test_anchored_summary_reports_ambiguity():
    buf = make(["x", "foo = 1", "bar = foo", "baz = foo"])
    summary, _, _ = execute(buf, "at /foo/ ciw qux")
    assert buf.lines == ["x", "qux = 1", "bar = foo", "baz = foo"]
    assert summary == "changed line 2 (match 1 of 3)"


def test_anchored_ordinal_summary_counts_in_file_order():
    buf = make(["x", "foo = 1", "bar = foo", "baz = foo"])
    summary, _, _ = execute(buf, "at 3rd /foo/ ciw qux")
    assert buf.lines == ["x", "foo = 1", "bar = foo", "baz = qux"]
    assert summary == "changed line 4 (match 3 of 3)"


def test_unanchored_summary_has_no_match_count():
    buf = make(["word"])
    summary, _, _ = execute(buf, "ciw x")
    assert summary == "changed line 1"


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


# --- anchor offsets (v0.14) ---

BANNER = ["def run():", "    pass", "", "# ---", "# Merge logic", "# ---", "x = 1"]


def test_anchored_offset_minus_inserts_above_banner():
    buf = make(list(BANNER))
    summary, first, last = execute(buf, "at /# Merge logic/-1 O NEW")
    assert buf.lines[3] == "NEW"          # above the banner's top # ---
    assert buf.lines[4] == "# ---"
    assert "(match 1 of 1, offset -1)" in summary


def test_anchored_offset_plus():
    buf = make(list(BANNER))
    execute(buf, "at /# Merge logic/+1 o NEW")   # below the closing # ---
    assert buf.lines[6] == "NEW"
    assert buf.lines[7] == "x = 1"


def test_anchored_offset_is_linewise_column_zero():
    buf = make(["alpha beta", "gamma delta"])
    # match lands mid-line; the offset line's cursor must be at col 0
    summary, _, _ = execute(buf, "at /delta/-1 ciw X")
    assert buf.lines[0] == "X beta"       # ciw at col 0 of the offset line


def test_anchored_offset_composes_with_ordinal():
    buf = make(["a", "foo", "b", "foo", "c"])
    summary, _, _ = execute(buf, "at 2nd /foo/+1 cc END")
    assert buf.lines[4] == "END"
    assert "(match 2 of 2, offset +1)" in summary


def test_anchored_offset_out_of_range_is_loud_and_restores():
    buf = make(["one", "two"], line=1, col=2)
    with pytest.raises(EditError, match="lands outside the file"):
        execute(buf, "at /one/-3 dd")
    assert (buf.cursor.line, buf.cursor.col) == (1, 2)
    assert buf.lines == ["one", "two"]
    assert not buf.dirty


def test_anchor_without_offset_keeps_match_column():
    buf = make(["say hello there"])
    summary, _, _ = execute(buf, "at /hello/ ciw hi")
    assert buf.lines == ["say hi there"]
    assert "offset" not in summary


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
