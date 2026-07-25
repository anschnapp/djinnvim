import asyncio
import textwrap

import pytest

from djinnvim import server
from djinnvim.buffer import Buffer
from djinnvim.session import Session
from djinnvim.viewport import render


def tool(coro):
    """The MCP tools are async (lazy client-roots fetch); run one to completion."""
    return asyncio.run(coro)

SAMPLE = textwrap.dedent("""\
    def parse_config(path):
        opts = {}
        for line in open(path):
            key, val = line.split("=")
            opts[key.strip()] = val
    """)


@pytest.fixture
def sample(tmp_path, monkeypatch):
    f = tmp_path / "config.py"
    f.write_text(SAMPLE)
    monkeypatch.setattr(server, "session", Session(roots=[tmp_path]))
    return f


def test_open_shows_metadata_and_viewport_not_content(sample):
    out = tool(server.open("config.py"))
    assert "5 lines" in out
    assert "python" in out
    assert "def parse_config" in out       # line 1 in viewport
    assert "opts[key.strip()]" not in out  # line 5 not in viewport


def test_open_missing_file(sample):
    assert tool(server.open("nope.py")).startswith("error: no such file")


def test_open_outside_root(sample):
    assert "outside the sandbox root" in tool(server.open("/etc/hostname"))


def test_motion_and_viewport(sample):
    tool(server.open("config.py"))
    out = tool(server.motion("/split"))
    assert out.startswith("match 1 of 1")
    assert "→" in out
    assert "^" in out  # column marker after a search


def test_motion_error_is_loud(sample):
    tool(server.open("config.py"))
    assert tool(server.motion("/zzz")) == "error: no match: zzz"


def test_edit_echoes_post_edit_viewport(sample):
    tool(server.open("config.py"))
    out = tool(server.edit("at /opts = /2nd ciw"))
    assert out.startswith("error:")  # malformed on purpose: never guess
    out = tool(server.edit("at /path/ ciw fname"))
    # "path" also matches on line 3 — the summary must surface the ambiguity
    assert out.splitlines()[0] == "changed line 1 (match 1 of 2)"
    assert "def parse_config(fname):" in out


def test_edit_requires_open(sample):
    assert tool(server.edit("dd")).startswith("error: no active buffer")


def test_staleness_blocks_edit(sample):
    tool(server.open("config.py"))
    # simulate another writer
    import os
    sample.write_text(SAMPLE + "# more\n")
    os.utime(sample, (0, 0))
    out = tool(server.edit("dd"))
    assert "changed on disk" in out


def test_substitute_round_trip(sample):
    tool(server.open("config.py"))
    out = tool(server.substitute(":%s/path/fname/g"))
    lines = out.splitlines()
    assert lines[0] == "2 substitution(s) on 2 line(s)"
    assert "- 1  def parse_config(path):" in out
    assert "+ 1  def parse_config(fname):" in out
    out = tool(server.write())
    assert "2 line(s) changed" in out
    assert "def parse_config(fname):" in sample.read_text()


def test_substitute_zero_matches_is_loud(sample):
    tool(server.open("config.py"))
    out = tool(server.substitute(":%s/zzz/y/g"))
    assert out.startswith("error: pattern matched 0 times")


def test_substitute_requires_open(sample):
    assert tool(server.substitute(":%s/a/b/")).startswith("error: no active buffer")


def test_substitute_staleness_blocks(sample):
    tool(server.open("config.py"))
    import os
    sample.write_text(SAMPLE + "# more\n")
    os.utime(sample, (0, 0))
    assert "changed on disk" in tool(server.substitute(":%s/path/x/g"))


def test_matches_listing_and_cap(sample):
    tool(server.open("config.py"))
    out = tool(server.matches("path"))
    lines = out.splitlines()
    assert lines[0] == "2 match(es) on 2 line(s)"
    assert lines[1].startswith("1:")
    assert lines[2].startswith("3:")


def test_matches_no_match(sample):
    tool(server.open("config.py"))
    assert tool(server.matches("zzz")) == "no match: zzz"


def test_matches_cap(sample, tmp_path):
    big = tmp_path / "big.txt"
    big.write_text("hit\n" * 60)
    tool(server.open("big.txt"))
    out = tool(server.matches("hit"))
    assert "60 match(es) on 60 line(s)" in out
    assert "... and 10 more lines" in out


def test_write_reports_changed_lines(sample):
    tool(server.open("config.py"))
    tool(server.edit("at /opts = /ciw options"))
    out = tool(server.write())
    assert "1 line(s) changed" in out
    assert "def parse_config" in sample.read_text()
    assert "options = {}" in sample.read_text()


def test_write_changed_count_exact_on_repetitive_files(tmp_path, monkeypatch):
    # dogfood #4, bug 3: difflib autojunk treats popular lines (blanks) as
    # junk on 200+-line files, wrecking the alignment — the live probe's
    # 41-line deletion was reported as "769 line(s) changed". Exact repro:
    # the same generated purge-blocks start/target pair.
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "benchmark"))
    from gen import generate
    doc = generate("purge-blocks", 500, 99)
    f = tmp_path / doc.filename
    f.write_text(doc.start)
    monkeypatch.setattr(server, "session", Session(roots=[tmp_path]))
    tool(server.open(doc.filename))
    server.session.active.lines = doc.target.splitlines()
    server.session.active.dirty = True
    out = tool(server.write())
    assert "41 line(s) changed" in out


def test_write_preview_shows_diff_and_writes_nothing(sample):
    tool(server.open("config.py"))
    tool(server.edit("at /opts = /ciw options"))
    before = sample.read_text()
    out = tool(server.write(preview=True))
    assert "1 line(s) differ from disk" in out
    assert "nothing written" in out
    assert "- 2      opts = {}" in out
    assert "+ 2      options = {}" in out
    assert sample.read_text() == before          # disk untouched
    assert server.session.active.dirty           # still pending
    # the real write afterwards reports the same count
    assert "1 line(s) changed" in tool(server.write())


def test_write_preview_clean_buffer(sample):
    tool(server.open("config.py"))
    out = tool(server.write(preview=True))
    assert out.startswith("no unwritten changes")


def test_write_preview_covers_insertions_and_deletions(sample):
    tool(server.open("config.py"))
    tool(server.edit("at /def parse_config/ O # header"))
    tool(server.edit('at /key, val/ dd'))
    out = tool(server.write(preview=True))
    assert "2 line(s) differ from disk" in out
    assert "+ 1  # header" in out                # pure insertion: + only
    assert '- 4          key, val = line.split("=")' in out  # pure deletion: - only


def test_full_session_flow(sample):
    """The design.md example session shape: open, motion, edit, write."""
    tool(server.open("config.py"))
    tool(server.motion("/key, val"))
    out = tool(server.edit('at /"="/ ci" :'))
    assert "key, val = line.split(\":\")" in out
    out = tool(server.write())
    assert "wrote" in out


def test_viewport_render_format():
    buf = Buffer(path=None, lines=["a", "b", "c", "d", "e"])
    buf.cursor.line = 2
    buf.cursor.col = 0
    out = render(buf)
    assert out.splitlines() == [
        "  1  a",
        "  2  b",
        "→ 3  c",
        "  4  d",
        "  5  e",
    ]


def test_viewport_column_marker():
    buf = Buffer(path=None, lines=["hello world"])
    buf.cursor.col = 6
    out = render(buf, show_column=True)
    assert out.splitlines() == [
        "→ 1  hello world",
        '           ^ on "w" of "world"',
    ]


def test_viewport_bare_caret_style(monkeypatch):
    monkeypatch.setattr("djinnvim.viewport.CURSOR_STYLE", "caret")
    buf = Buffer(path=None, lines=["hello world"])
    buf.cursor.col = 6
    out = render(buf, show_column=True)
    assert out.splitlines() == [
        "→ 1  hello world",
        "           ^",
    ]


def test_caret_label_mid_word():
    # the label names the exact ciw span, not the word boundary vim's w uses
    buf = Buffer(path=None, lines=["    retries=15)"])
    buf.cursor.col = 6
    out = render(buf, show_column=True)
    assert out.splitlines()[-1].strip() == '^ on "t" of "retries"'


def test_caret_label_punctuation():
    buf = Buffer(path=None, lines=["    retries=15)"])
    buf.cursor.col = 14
    out = render(buf, show_column=True)
    assert out.splitlines()[-1].strip() == '^ on ")"'


def test_caret_label_end_of_line():
    buf = Buffer(path=None, lines=["ab"])
    buf.cursor.col = 2
    out = render(buf, show_column=True)
    assert out.splitlines()[-1].strip() == "^ at end of line"


def test_caret_label_empty_line():
    buf = Buffer(path=None, lines=[""])
    buf.cursor.col = 0
    out = render(buf, show_column=True)
    assert out.splitlines()[-1].strip() == "^ at end of line"


def test_caret_label_single_char_word():
    buf = Buffer(path=None, lines=["x = 1"])
    buf.cursor.col = 0
    out = render(buf, show_column=True)
    assert out.splitlines()[-1].strip() == '^ on "x" of "x"'


def test_caret_label_space():
    buf = Buffer(path=None, lines=["a b"])
    buf.cursor.col = 1
    out = render(buf, show_column=True)
    assert out.splitlines()[-1].strip() == '^ on " "'
