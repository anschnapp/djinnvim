"""The print tool (v0.16): addressing, window words, cursor semantics,
the span cap, and read-only guarantees."""

from pathlib import Path

import pytest

from djinnvim.buffer import Buffer
from djinnvim.printcmd import SPAN_CAP, PrintError, execute


def make(n=200, line=0, col=0):
    buf = Buffer(path=Path("test.txt"), lines=[f"line {i + 1}" for i in range(n)])
    buf.cursor.line, buf.cursor.col = line, col
    return buf


# --- bare p ---

def test_bare_p_prints_current_line_cursor_unchanged():
    buf = make(line=49, col=3)
    head, first, last = execute(buf, "p")
    assert (first, last) == (49, 49)
    assert head == "line 50 of 200"
    assert (buf.cursor.line, buf.cursor.col) == (49, 3)


def test_leading_colon_and_dot_address():
    buf = make(line=49)
    assert execute(buf, ":p")[1:] == (49, 49)
    assert execute(buf, ".p")[1:] == (49, 49)


# --- addresses move the cursor ---

def test_line_address_moves_cursor():
    buf = make(line=0)
    head, first, last = execute(buf, ":80 p")
    assert (first, last) == (79, 79)
    assert (buf.cursor.line, buf.cursor.col) == (79, 0)


def test_pattern_address_with_offset():
    buf = make(line=0)
    head, first, last = execute(buf, ":/line 120/-1 p")
    assert (first, last) == (118, 118)
    assert buf.cursor.line == 118


def test_two_address_range_cursor_to_last_line():
    buf = make(line=0)
    head, first, last = execute(buf, ":10,25 p")
    assert (first, last) == (9, 24)
    assert head == "lines 10–25 of 200"
    assert buf.cursor.line == 24


# --- window words ---

def test_above_includes_cursor_line_plus_n():
    buf = make(line=99)
    _, first, last = execute(buf, "p above tiny")
    assert (first, last) == (91, 99)  # 8 above + cursor


def test_below_numeric_count():
    buf = make(line=99)
    _, first, last = execute(buf, "p below 12")
    assert (first, last) == (99, 111)


def test_around_counts_each_side():
    buf = make(line=99)
    _, first, last = execute(buf, "p around middle")
    assert (first, last) == (74, 124)  # 25 each side


def test_category_values():
    buf = make(n=300, line=150)
    assert execute(buf, "p above tiny")[1] == 142
    assert execute(buf, "p above middle")[1] == 125
    assert execute(buf, "p above long")[1] == 100


def test_window_clamps_at_file_edges():
    buf = make(line=2)
    _, first, last = execute(buf, "p around long")
    assert first == 0
    buf.cursor.line = 197
    _, first, last = execute(buf, "p below long")
    assert last == 199


def test_address_combines_with_window():
    buf = make(line=0)
    _, first, last = execute(buf, ":/line 100/ p around tiny")
    assert (first, last) == (91, 107)
    assert buf.cursor.line == 99


# --- loud errors ---

def test_range_plus_window_rejected():
    buf = make()
    with pytest.raises(PrintError, match="two-address range"):
        execute(buf, ":10,25 p around tiny")


def test_span_cap_on_explicit_range():
    buf = make(n=300)
    with pytest.raises(PrintError, match="pages"):
        execute(buf, ":1,200 p")
    assert buf.cursor.line == 0  # untouched on failure


def test_span_cap_allows_exactly_101():
    buf = make(n=300, line=150)
    _, first, last = execute(buf, ":50,150 p")
    assert last - first + 1 == SPAN_CAP


def test_percent_range_capped_on_big_file():
    buf = make(n=300)
    with pytest.raises(PrintError, match="pages"):
        execute(buf, "%p")


def test_percent_range_ok_on_small_file():
    buf = make(n=5)
    _, first, last = execute(buf, "%p")
    assert (first, last) == (0, 4)


def test_bad_count_word():
    buf = make()
    with pytest.raises(PrintError, match="tiny/middle/long"):
        execute(buf, "p above huge")


def test_unparseable_command():
    buf = make()
    with pytest.raises(PrintError, match="supported"):
        execute(buf, "print it all")


def test_no_match_address_is_loud():
    buf = make()
    with pytest.raises(PrintError, match="no line matches"):
        execute(buf, ":/nonexistent pattern/ p")


# --- read-only guarantees, session surface ---

def test_never_dirties_or_pushes_undo():
    buf = make(line=10)
    execute(buf, ":80 p")
    execute(buf, "p around middle")
    assert not buf.dirty
    assert buf.undo_stack == []


def test_session_print_renders_viewport(tmp_path):
    from djinnvim.session import Session

    f = tmp_path / "f.py"
    f.write_text("\n".join(f"line {i + 1}" for i in range(50)) + "\n")
    s = Session(roots=[tmp_path])
    s.open(str(f))
    out = s.print(":20 p around 2")
    lines = out.splitlines()
    assert lines[0] == "lines 18–22 of 50"
    assert lines[1].endswith("18  line 18")
    assert lines[3].startswith("→")
    assert "20  line 20" in lines[3]
    assert len(lines) == 6  # header + 5 lines, context 0, no caret


def test_session_print_no_buffer():
    from djinnvim.session import Session

    s = Session(roots=[Path("/tmp")])
    assert s.print("p").startswith("error: no active buffer")
