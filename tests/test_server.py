import textwrap

import pytest

from keyhole import server
from keyhole.buffer import Buffer
from keyhole.viewport import render

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
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "_buffers", {})
    monkeypatch.setattr(server, "_active", None)
    return f


def test_open_shows_metadata_and_viewport_not_content(sample):
    out = server.open("config.py")
    assert "5 lines" in out
    assert "python" in out
    assert "def parse_config" in out       # line 1 in viewport
    assert "opts[key.strip()]" not in out  # line 5 not in viewport


def test_open_missing_file(sample):
    assert server.open("nope.py").startswith("error: no such file")


def test_open_outside_root(sample):
    assert "outside the allowed root" in server.open("/etc/hostname")


def test_motion_and_viewport(sample):
    server.open("config.py")
    out = server.motion("/split")
    assert out.startswith("match 1 of 1")
    assert "→" in out
    assert "^" in out  # column marker after a search


def test_motion_error_is_loud(sample):
    server.open("config.py")
    assert server.motion("/zzz") == "error: no match: zzz"


def test_edit_echoes_post_edit_viewport(sample):
    server.open("config.py")
    out = server.edit("at /opts = /2nd ciw")
    assert out.startswith("error:")  # malformed on purpose: never guess
    out = server.edit("at /path/ ciw fname")
    # "path" also matches on line 3 — the summary must surface the ambiguity
    assert out.splitlines()[0] == "changed line 1 (match 1 of 2)"
    assert "def parse_config(fname):" in out


def test_edit_requires_open(sample):
    assert server.edit("dd").startswith("error: no active buffer")


def test_staleness_blocks_edit(sample):
    server.open("config.py")
    # simulate another writer
    import os
    sample.write_text(SAMPLE + "# more\n")
    os.utime(sample, (0, 0))
    out = server.edit("dd")
    assert "changed on disk" in out


def test_substitute_round_trip(sample):
    server.open("config.py")
    out = server.substitute(":%s/path/fname/g")
    lines = out.splitlines()
    assert lines[0] == "2 substitution(s) on 2 line(s)"
    assert "- 1  def parse_config(path):" in out
    assert "+ 1  def parse_config(fname):" in out
    out = server.write()
    assert "2 line(s) changed" in out
    assert "def parse_config(fname):" in sample.read_text()


def test_substitute_zero_matches_is_loud(sample):
    server.open("config.py")
    out = server.substitute(":%s/zzz/y/g")
    assert out.startswith("error: pattern matched 0 times")


def test_substitute_requires_open(sample):
    assert server.substitute(":%s/a/b/").startswith("error: no active buffer")


def test_substitute_staleness_blocks(sample):
    server.open("config.py")
    import os
    sample.write_text(SAMPLE + "# more\n")
    os.utime(sample, (0, 0))
    assert "changed on disk" in server.substitute(":%s/path/x/g")


def test_matches_listing_and_cap(sample):
    server.open("config.py")
    out = server.matches("path")
    lines = out.splitlines()
    assert lines[0] == "2 match(es) on 2 line(s)"
    assert lines[1].startswith("1:")
    assert lines[2].startswith("3:")


def test_matches_no_match(sample):
    server.open("config.py")
    assert server.matches("zzz") == "no match: zzz"


def test_matches_cap(sample, tmp_path):
    big = tmp_path / "big.txt"
    big.write_text("hit\n" * 60)
    server.open("big.txt")
    out = server.matches("hit")
    assert "60 match(es) on 60 line(s)" in out
    assert "... and 10 more lines" in out


def test_write_reports_changed_lines(sample):
    server.open("config.py")
    server.edit("at /opts = /ciw options")
    out = server.write()
    assert "1 line(s) changed" in out
    assert "def parse_config" in sample.read_text()
    assert "options = {}" in sample.read_text()


def test_full_session_flow(sample):
    """The design.md example session shape: open, motion, edit, write."""
    server.open("config.py")
    server.motion("/key, val")
    out = server.edit('at /"="/ ci" :')
    assert "key, val = line.split(\":\")" in out
    out = server.write()
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
        "           ^",
    ]
