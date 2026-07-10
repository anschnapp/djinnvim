from pathlib import Path

import pytest

from djinnvim.buffer import Buffer
from djinnvim.motion import MotionError, execute


def make(lines):
    return Buffer(path=Path("test.txt"), lines=list(lines))


LINES = [
    "def parse(x):",       # 1
    "    return x",        # 2
    "",                    # 3
    "def render(y):",      # 4
    "    return parse(y)", # 5
]


def test_search_forward_moves_to_first_match_after_cursor():
    buf = make(LINES)
    status, show_col = execute(buf, "/parse")
    assert status == "match 1 of 2"
    assert (buf.cursor.line, buf.cursor.col) == (0, 4)
    assert show_col is True


def test_search_skips_match_at_cursor_and_wraps():
    buf = make(LINES)
    execute(buf, "/parse")
    status, _ = execute(buf, "/parse")
    assert status == "match 2 of 2"
    assert buf.cursor.line == 4
    status, _ = execute(buf, "/parse")
    assert status == "match 1 of 2 (wrapped)"
    assert buf.cursor.line == 0


def test_search_backward():
    buf = make(LINES)
    buf.cursor.line = 4
    status, _ = execute(buf, "?def")
    assert status == "match 2 of 2"
    assert buf.cursor.line == 3


def test_backward_wraps():
    buf = make(LINES)
    status, _ = execute(buf, "?def")
    assert status.endswith("(wrapped)")
    assert buf.cursor.line == 3


def test_n_and_N_repeat_last_search():
    buf = make(LINES)
    execute(buf, "/return")
    status, _ = execute(buf, "n")
    assert status == "match 2 of 2"
    status, _ = execute(buf, "N")
    assert status == "match 1 of 2"


def test_n_without_search_errors():
    buf = make(LINES)
    with pytest.raises(MotionError, match="no previous search"):
        execute(buf, "n")


def test_no_match_is_loud_and_cursor_unchanged():
    buf = make(LINES)
    buf.cursor.line = 2
    with pytest.raises(MotionError, match="no match: zzz"):
        execute(buf, "/zzz")
    assert buf.cursor.line == 2


def test_bad_regex():
    buf = make(LINES)
    with pytest.raises(MotionError, match="bad regex"):
        execute(buf, "/f(oo")


def test_goto_line():
    buf = make(LINES)
    status, show_col = execute(buf, ":4")
    assert status == "line 4"
    assert (buf.cursor.line, buf.cursor.col) == (3, 0)
    assert show_col is False


def test_goto_line_out_of_range():
    buf = make(LINES)
    with pytest.raises(MotionError, match="line 99 out of range .file has 5 lines."):
        execute(buf, ":99")


def test_gg_and_G():
    buf = make(LINES)
    buf.cursor.line = 3
    assert execute(buf, "gg")[0] == "line 1"
    assert buf.cursor.line == 0
    assert execute(buf, "G")[0] == "line 5 (last)"
    assert buf.cursor.line == 4


def test_unknown_motion():
    buf = make(LINES)
    with pytest.raises(MotionError, match="unknown motion"):
        execute(buf, "7j")


def test_f_moves_to_next_char_on_line():
    buf = make(['x = "hello"'])
    buf.cursor.col = 0
    status, show_col = execute(buf, 'f"')
    assert status == "column 5"
    assert (buf.cursor.line, buf.cursor.col) == (0, 4)
    assert show_col is True


def test_f_skips_char_at_cursor():
    buf = make(['x = "hello"'])
    buf.cursor.col = 4  # on the first "
    execute(buf, 'f"')
    assert buf.cursor.col == 10


def test_F_moves_backward_on_line():
    buf = make(['x = "hello"'])
    buf.cursor.col = 10  # on the closing "
    status, _ = execute(buf, 'F"')
    assert status == "column 5"
    assert buf.cursor.col == 4


def test_f_stays_on_cursor_line():
    buf = make(["no target", "z here"])
    with pytest.raises(MotionError, match="no 'z' after cursor on line 1"):
        execute(buf, "fz")
    assert buf.cursor.col == 0


def test_f_without_char_is_loud():
    buf = make(["abc"])
    with pytest.raises(MotionError, match="f needs a target character"):
        execute(buf, "f")


def test_regex_search_skips_match_at_cursor():
    # vim semantics: / finds the first match strictly AFTER the cursor,
    # so a match at (line 1, col 1) is skipped when the cursor sits there
    buf = make(LINES)
    status, _ = execute(buf, r"/def \w+\(")
    assert status == "match 2 of 2"
    assert buf.cursor.line == 3
