from pathlib import Path

import pytest

from keyhole.buffer import Buffer
from keyhole.substitute import DIFF_CAP, SubstituteError, execute


def make(lines, line=0, col=0):
    buf = Buffer(path=Path("test.txt"), lines=list(lines))
    buf.cursor.line, buf.cursor.col = line, col
    return buf


LINES = [
    "def parse(x):",        # 1
    "    y = x + x",        # 2
    "    return y",         # 3
    "",                     # 4
    "def render(x):",       # 5
    "    return parse(x)",  # 6
]


# --- whole file ---

def test_percent_s_global():
    buf = make(LINES)
    out = execute(buf, ":%s/x/z/g")
    assert buf.lines[0] == "def parse(z):"
    assert buf.lines[1] == "    y = z + z"
    assert out.splitlines()[0] == "5 substitution(s) on 4 line(s)"
    assert buf.dirty


def test_without_g_first_occurrence_per_line():
    buf = make(LINES)
    execute(buf, ":%s/x/z/")
    assert buf.lines[1] == "    y = z + x"


def test_leading_colon_optional():
    buf = make(["aaa"])
    execute(buf, "%s/a/b/g")
    assert buf.lines == ["bbb"]


def test_diff_shows_old_and_new_lines():
    buf = make(LINES)
    out = execute(buf, ":%s/parse/load/g")
    assert "- 1  def parse(x):" in out
    assert "+ 1  def load(x):" in out
    assert "- 6      return parse(x)" in out


def test_cursor_moves_to_last_changed_line():
    buf = make(LINES)
    execute(buf, ":%s/parse/load/g")
    assert (buf.cursor.line, buf.cursor.col) == (5, 0)


# --- ranges ---

def test_bare_s_is_cursor_line_only():
    buf = make(LINES, line=1)
    execute(buf, ":s/x/z/g")
    assert buf.lines[0] == "def parse(x):"
    assert buf.lines[1] == "    y = z + z"


def test_numeric_range_inclusive():
    buf = make(LINES)
    execute(buf, ":1,2s/x/z/g")
    assert buf.lines[0] == "def parse(z):"
    assert buf.lines[1] == "    y = z + z"
    assert buf.lines[4] == "def render(x):"


def test_dollar_addr():
    buf = make(LINES)
    execute(buf, ":5,$s/x/z/")
    assert buf.lines[4] == "def render(z):"


def test_pattern_range():
    buf = make([
        "def parse(x):",
        "    return x",
        "",
        "def render(x):",
        "    return parse(x)",
        "",
        "END = x",
    ])
    out = execute(buf, ":/def render/,/^$/s/x/z/g")
    assert buf.lines[0] == "def parse(x):"     # before range: untouched
    assert buf.lines[3] == "def render(z):"
    assert buf.lines[4] == "    return parse(z)"
    assert buf.lines[6] == "END = x"           # after range: untouched
    assert "2 substitution(s)" in out


def test_pattern_range_end_only_before_start_is_backwards():
    # /^$/ exists only above the start line: wrap finds it, range is loud
    buf = make(LINES)
    with pytest.raises(SubstituteError, match="backwards range"):
        execute(buf, ":/def render/,/^$/s/x/z/g")
    assert buf.lines == LINES


def test_pattern_addr_no_match_is_loud():
    buf = make(LINES)
    with pytest.raises(SubstituteError, match="no line matches address"):
        execute(buf, ":/zzz/,/^$/s/x/z/")
    assert buf.lines == LINES


def test_out_of_range_line():
    buf = make(LINES)
    with pytest.raises(SubstituteError, match="line 99 out of range"):
        execute(buf, ":99s/x/z/")


# --- :g/pat/d ---

def test_global_delete():
    buf = make(["keep", "print('DEBUG 1')", "keep2", "print('DEBUG 2')"])
    out = execute(buf, ":g/DEBUG/d")
    assert buf.lines == ["keep", "keep2"]
    assert out.splitlines()[0] == "deleted 2 line(s)"
    assert "- 2  print('DEBUG 1')" in out
    assert buf.dirty


def test_global_delete_all_lines_leaves_empty_buffer_line():
    buf = make(["a", "a"])
    execute(buf, ":g/a/d")
    assert buf.lines == [""]


def test_global_delete_zero_matches_is_loud():
    buf = make(["keep"])
    with pytest.raises(SubstituteError, match="pattern matched 0 lines"):
        execute(buf, ":g/zzz/d")


# --- failures never touch state ---

def test_zero_matches_is_loud_and_state_untouched():
    buf = make(LINES, line=2, col=4)
    with pytest.raises(SubstituteError, match="pattern matched 0 times in file"):
        execute(buf, ":%s/zzz/y/g")
    assert buf.lines == LINES
    assert (buf.cursor.line, buf.cursor.col) == (2, 4)
    assert not buf.dirty


def test_zero_matches_in_range_names_the_range():
    buf = make(LINES)
    with pytest.raises(SubstituteError, match="in lines 3–4"):
        execute(buf, ":3,4s/x/z/")


def test_bad_regex_is_loud():
    buf = make(LINES)
    with pytest.raises(SubstituteError, match="bad regex"):
        execute(buf, ":%s/f(oo/x/")


def test_unparseable_command_is_loud():
    buf = make(LINES)
    with pytest.raises(SubstituteError, match="cannot parse"):
        execute(buf, ":wq")


# --- regex features ---

def test_group_references():
    buf = make(["name = value"])
    execute(buf, r":%s/(\w+) = (\w+)/\2 = \1/")
    assert buf.lines == ["value = name"]


def test_ignore_case_flag():
    buf = make(["Foo foo FOO"])
    execute(buf, ":%s/foo/bar/gi")
    assert buf.lines == ["bar bar bar"]


def test_escaped_slash_in_pattern_and_replacement():
    buf = make(["path = a/b"])
    execute(buf, r":%s/a\/b/c\/d/")
    assert buf.lines == ["path = c/d"]


# --- diff cap ---

def test_diff_capped_with_elision():
    buf = make([f"hit {i}" for i in range(DIFF_CAP + 20)])
    out = execute(buf, ":%s/hit/HIT/")
    assert f"{DIFF_CAP + 20} substitution(s)" in out
    assert "more changed line(s)" in out
    assert "-  1  hit 0" in out                     # first edge shown (2-wide gutter)
    assert f"HIT {DIFF_CAP + 19}" in out            # last edge shown
    assert "hit 40" not in out                      # middle elided
