"""CLI surface: dispatch, the one-quoted-argument rule, exit codes.
Daemon traffic is monkeypatched — the real socket path is covered by
test_daemon.py and e2e/e2e_cli.py."""

from pathlib import Path

import pytest

import djinnvim.server
from djinnvim import cli, daemon


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_request(op, args, spawn=True):
        seen.append((op, args))
        return "ok-result"

    monkeypatch.setattr(daemon, "request", fake_request)
    return seen


def test_no_args_runs_mcp_server(monkeypatch):
    ran = []
    monkeypatch.setattr(djinnvim.server, "main", lambda: ran.append(True))
    assert cli.main([]) == 0
    assert ran == [True]


def test_mcp_subcommand_runs_server(monkeypatch):
    ran = []
    monkeypatch.setattr(djinnvim.server, "main", lambda: ran.append(True))
    assert cli.main(["mcp"]) == 0
    assert ran == [True]


def test_verbs_map_to_ops(calls, capsys):
    assert cli.main(["open", "f.py"]) == 0
    assert cli.main(["motion", "/def parse"]) == 0
    assert cli.main(["edit", "at /old/ ciw new"]) == 0
    assert cli.main(["substitute", ":%s/a/b/g"]) == 0
    assert cli.main(["matches", "parse", "-C", "1"]) == 0
    assert cli.main(["write"]) == 0
    assert calls == [
        ("open", {"path": "f.py"}),
        ("motion", {"command": "/def parse"}),
        ("edit", {"command": "at /old/ ciw new"}),
        ("substitute", {"command": ":%s/a/b/g"}),
        ("matches", {"pattern": "parse", "context": 1}),
        ("write", {"preview": False}),
    ]
    assert capsys.readouterr().out == "ok-result\n" * 6


def test_print_verb(calls, capsys):
    assert cli.main(["print"]) == 0  # bare: defaults to 'p'
    assert cli.main(["print", ":80 p around middle"]) == 0
    assert calls == [
        ("print", {"command": "p"}),
        ("print", {"command": ":80 p around middle"}),
    ]
    assert cli.main(["print", ":80", "p"]) == 2  # one-argument rule
    assert "ONE shell argument" in capsys.readouterr().err


def test_write_preview_flag(calls, capsys):
    assert cli.main(["write", "--preview"]) == 0
    assert calls == [("write", {"preview": True})]


def test_unquoted_command_is_a_loud_error(calls, capsys):
    assert cli.main(["edit", "at", "/old/", "ciw", "new"]) == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "ONE shell argument" in err
    assert "quote" in err


def test_error_result_sets_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "request", lambda op, args, spawn=True: "error: no match")
    assert cli.main(["motion", "/nope"]) == 1
    assert capsys.readouterr().out == "error: no match\n"


def test_install_skill_user_and_project(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.main(["install-skill"]) == 0
    dest = tmp_path / ".claude" / "skills" / "djinnvim" / "SKILL.md"
    assert dest.exists()
    text = dest.read_text()
    assert text.startswith("---\nname: djinnvim\n")
    assert "at each /pattern/" in text
    assert cli.main(["install-skill"]) == 0  # idempotent, reports update
    out = capsys.readouterr().out
    assert "installed" in out and "updated" in out

    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    assert cli.main(["install-skill", "--project"]) == 0
    assert (proj / ".claude" / "skills" / "djinnvim" / "SKILL.md").exists()


def test_daemon_failure_is_exit_2(monkeypatch, capsys):
    def boom(op, args, spawn=True):
        raise daemon.DaemonError("daemon did not come up")

    monkeypatch.setattr(daemon, "request", boom)
    assert cli.main(["write"]) == 2
    assert "daemon did not come up" in capsys.readouterr().err


# --- v0.18: the skill mirrors the MCP guidance by hand, so pin the parts
# that drift. The MCP path gets the same rules via server instructions; the
# CLI has no schema channel at all, so SKILL.md is the only copy it sees.

def test_skill_carries_the_same_contracts_as_the_server_instructions():
    from djinnvim import server

    text = (Path(cli.__file__).parent / "skill" / "SKILL.md").read_text()
    for contract in ("autoindent", "cc!", "o!", "backslash-n"):
        assert contract in text, f"SKILL.md missing: {contract}"
        assert contract in server.INSTRUCTIONS, f"instructions missing: {contract}"
    # removed commands must not survive in either copy
    for gone in ("cip", "cap`"):
        assert gone not in text, f"SKILL.md still advertises {gone}"
