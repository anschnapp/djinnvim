"""Results-file handling: the JSONL parser must survive glued and corrupt
lines (interrupted appends), and abort detection must keep environment
failures (session limit, timeout) out of the aggregates and resumable."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "benchmark"))
from report import is_aborted, iter_records  # noqa: E402


def rec(**kw):
    base = {"task": "rename", "size": 100, "model": "opus",
            "condition": "keyhole", "trial": 0, "exact_match": True,
            "subtype": "success", "agent_result": "Done."}
    base.update(kw)
    return base


def test_iter_records_plain_lines(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps(rec(trial=0)) + "\n" + json.dumps(rec(trial=1)) + "\n")
    assert [r["trial"] for r in iter_records(p)] == [0, 1]


def test_iter_records_glued_line(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps(rec(trial=0)) + json.dumps(rec(trial=1)) + "\n"
                 + json.dumps(rec(trial=2)) + "\n")
    assert [r["trial"] for r in iter_records(p)] == [0, 1, 2]


def test_iter_records_skips_corrupt_line(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps(rec(trial=0)) + "\n"
                 + '{"task": "rename", "size":' + "\n"
                 + json.dumps(rec(trial=2)) + "\n")
    assert [r["trial"] for r in iter_records(p)] == [0, 2]


def test_is_aborted():
    assert not is_aborted(rec())
    assert is_aborted(rec(subtype="timeout"))
    assert is_aborted(rec(aborted=True))
    assert is_aborted(rec(
        agent_result="You've hit your session limit · resets 8:10pm"))
    assert is_aborted(rec(agent_result="Usage limit reached"))
