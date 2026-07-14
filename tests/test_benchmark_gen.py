"""The benchmark document generator: starts and targets must be valid Python,
deterministic per seed, actually different, and roughly the requested size."""

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "benchmark"))
from gen import TASKS, generate  # noqa: E402


@pytest.mark.parametrize("task", list(TASKS))
@pytest.mark.parametrize("size", [100, 500, 2000])
def test_generate(task, size):
    doc = generate(task, size, seed=0)
    ast.parse(doc.start)
    ast.parse(doc.target)
    assert doc.start != doc.target
    n = doc.start.count("\n")
    assert size * 0.9 <= n <= size * 1.3 + 30
    assert generate(task, size, seed=0).start == doc.start
    assert generate(task, size, seed=1).start != doc.start


def test_rename_decoy_survives():
    doc = generate("rename", 500, seed=0)
    assert doc.start.count("fetch_records_cached") == \
        doc.target.count("fetch_records_cached")
    assert "fetch_records" not in doc.target.replace("fetch_records_cached", "")
    assert "load_records" in doc.target


def test_delete_debug_keeps_definition():
    doc = generate("delete-debug", 500, seed=0)
    assert "def log_debug(msg):" in doc.target
    assert "    log_debug(" not in doc.target


def test_bump_default_single_site():
    doc = generate("bump-default", 500, seed=0)
    assert doc.target.count("timeout=90") == 1
    assert "timeout=30" not in doc.target
    assert "POLL_INTERVAL = 30" in doc.target      # decoys untouched
    assert "range(30)" in doc.target


def test_quote_style_no_singles_left():
    doc = generate("quote-style", 500, seed=0)
    assert "'" not in doc.target


def test_rename_trap_decoy_present_prompt_natural():
    doc = generate("rename-trap", 500, seed=0)
    assert doc.start.count("fetch_records_cached") >= 2  # decoy in play
    assert doc.start.count("fetch_records_cached") == \
        doc.target.count("fetch_records_cached")
    assert "load_records" in doc.target
    assert "fetch_records_cached" not in doc.prompt  # no decoy warning


def test_bump_trap_call_sites_keep_explicit_timeout():
    doc = generate("bump-trap", 500, seed=0)
    explicit = doc.start.count("send_request(url, timeout=30)")
    assert explicit >= 2
    assert doc.target.count("send_request(url, timeout=30)") == explicit
    assert "def send_request(url, timeout=90, retries=3):" in doc.target
    assert "timeout=30" not in doc.target.split("\n\n\n")[
        [i for i, c in enumerate(doc.target.split("\n\n\n"))
         if c.startswith("def send_request")][0]]


def test_delete_trap_summary_collision_survives():
    doc = generate("delete-trap", 500, seed=0)
    n = doc.start.count("log_debug_summary(")
    assert n >= 2  # def + at least one call
    assert doc.target.count("log_debug_summary(") == n
    assert "def log_debug(msg):" in doc.target
    assert "    log_debug(" not in doc.target


def test_quote_trap_comments_keep_apostrophes():
    doc = generate("quote-trap", 500, seed=0)
    start_comments = [l for l in doc.start.splitlines()
                      if l.lstrip().startswith("#")]
    assert any("'" in c for c in start_comments)
    for c in start_comments:
        assert c in doc.target  # comments byte-identical
    code = [l for l in doc.target.splitlines()
            if not l.lstrip().startswith("#")]
    assert all("'" not in l for l in code)


def test_composite_all_six_parts():
    doc = generate("composite", 500, seed=0)
    t = doc.target
    assert "fetch_records" not in t.replace("fetch_records_cached", "")
    assert "def poll_status(job, interval=90):" in t
    assert "    log_debug(" not in t and "def log_debug(msg):" in t
    assert "DEFAULT_REGION = 'us-east'" in t
    assert "MAX_RETRIES = 5\nRETRY_BACKOFF = 2.5" in t
    assert "def send_request(url, logger, timeout=30):" in t
    assert "send_request(endpoint)" not in t
    assert "send_request(endpoint, logger)" in t
    # multi-line call sites gained the logger line
    assert doc.start.count("        endpoint,\n        logger,") == 0
    assert t.count("        endpoint,\n        logger,") >= 2


def test_move_multi_order_and_content():
    doc = generate("move-multi", 500, seed=0)
    assert sorted(doc.start.splitlines()) == sorted(doc.target.splitlines())
    t = doc.target
    pos = [t.index(f"def check_{n}") for n in ("ids", "totals", "names")]
    assert pos == sorted(pos) < [t.index("def run_checks")] * 3
    block = t[t.index("def check_ids"):t.index("def run_checks")]
    assert block.count("\n\n\n") == 3  # the four defs are contiguous


def test_purge_blocks_removal_only_and_dap_safe():
    doc = generate("purge-blocks", 500, seed=0)
    assert doc.start.count("# DEPRECATED") >= 3
    assert "# DEPRECATED" not in doc.target
    start_lines = doc.start.splitlines()
    for line in doc.target.splitlines():
        assert line in start_lines  # pure removal, nothing rewritten
    assert "\n\n\n\n" not in doc.target  # exactly two blanks survive
    # marked blocks are single paragraphs (no internal blanks), so dap
    # grabs exactly the marker + function
    for chunk in doc.start.split("\n\n\n"):
        if chunk.startswith("# DEPRECATED"):
            assert "\n\n" not in chunk


def test_move_func_same_content():
    doc = generate("move-func", 500, seed=0)
    assert sorted(doc.start.splitlines()) == sorted(doc.target.splitlines())
    t = doc.target
    assert t.index("def validate_row") < t.index("def write_output")
    between = t[t.index("    return True", t.index("def validate_row")):
                t.index("def write_output")]
    assert between.endswith("\n\n\n")  # directly above, two blank lines
