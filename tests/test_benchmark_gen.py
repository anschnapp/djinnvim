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


def test_move_func_same_content():
    doc = generate("move-func", 500, seed=0)
    assert sorted(doc.start.splitlines()) == sorted(doc.target.splitlines())
    t = doc.target
    assert t.index("def validate_row") < t.index("def write_output")
    between = t[t.index("    return True", t.index("def validate_row")):
                t.index("def write_output")]
    assert between.endswith("\n\n\n")  # directly above, two blank lines
