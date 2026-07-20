"""Multi-root sandbox (v0.11, decided 2026-07-20): traversal/symlink
containment, multi-root peers, the relative-path rule, per-source `/` and
$HOME refusals, env parsing, write-time revalidation, and the server's
lazy resolution chain."""

import asyncio
import os
from pathlib import Path

import pytest

from djinnvim import roots, server
from djinnvim.session import Session


@pytest.fixture
def tree(tmp_path):
    a = tmp_path / "roota"
    b = tmp_path / "rootb"
    outside = tmp_path / "outside"
    for d in (a, b, outside):
        d.mkdir()
    (a / "ina.py").write_text("a = 1\n")
    (b / "inb.py").write_text("b = 2\n")
    (outside / "secret.txt").write_text("nope\n")
    return a.resolve(), b.resolve(), outside.resolve()


# --- containment at open ---------------------------------------------------

def test_dotdot_traversal_rejected(tree):
    a, _, outside = tree
    s = Session(roots=[a])
    out = s.open("../outside/secret.txt")
    assert "outside the sandbox root" in out


def test_absolute_path_outside_rejected(tree):
    a, _, outside = tree
    s = Session(roots=[a])
    out = s.open(str(outside / "secret.txt"))
    assert "outside the sandbox root" in out


def test_symlink_inside_pointing_out_rejected(tree):
    a, _, outside = tree
    (a / "link.txt").symlink_to(outside / "secret.txt")
    s = Session(roots=[a])
    out = s.open("link.txt")
    # resolves to the true target BEFORE the check, and the error names it
    assert "outside the sandbox root" in out
    assert str(outside / "secret.txt") in out


def test_multi_root_accepts_all_peers_rejects_outside(tree):
    a, b, outside = tree
    s = Session(roots=[a, b])
    assert "1 lines" in s.open(str(a / "ina.py"))
    assert "1 lines" in s.open(str(b / "inb.py"))
    assert "outside the sandbox root" in s.open(str(outside / "secret.txt"))


def test_relative_path_with_multiple_roots_is_loud(tree):
    a, b, _ = tree
    s = Session(roots=[a, b])
    out = s.open("ina.py")
    assert out.startswith("error:")
    assert "use an absolute path" in out
    assert str(a) in out and str(b) in out  # doubles as the sandbox announcement


def test_relative_path_with_single_root_resolves_against_it(tree):
    a, _, _ = tree
    s = Session(roots=[a])
    assert "1 lines" in s.open("ina.py")


def test_no_roots_is_loud(tree):
    s = Session()
    assert "no sandbox roots" in s.open("ina.py")


# --- write-time revalidation ----------------------------------------------

def test_write_fails_after_root_revoked(tree):
    a, b, _ = tree
    s = Session(roots=[a, b])
    s.open(str(a / "ina.py"))
    s.edit("at /a/ ciw c")
    s.roots = [b]  # client roots/list shrank
    out = s.write()
    assert "no longer inside the sandbox root" in out
    assert (a / "ina.py").read_text() == "a = 1\n"  # not written


# --- env parsing (explicit sources) ----------------------------------------

def test_env_roots_pathsep_list(tree, monkeypatch):
    a, b, _ = tree
    monkeypatch.setenv("DJINNVIM_ROOTS", f"{a}{os.pathsep}{b}")
    assert roots.env_roots() == [a, b]


def test_env_root_singular_alias(tree, monkeypatch):
    a, _, _ = tree
    monkeypatch.delenv("DJINNVIM_ROOTS", raising=False)
    monkeypatch.setenv("DJINNVIM_ROOT", str(a))
    assert roots.env_roots() == [a]


def test_env_roots_wins_over_singular(tree, monkeypatch):
    a, b, _ = tree
    monkeypatch.setenv("DJINNVIM_ROOTS", str(b))
    monkeypatch.setenv("DJINNVIM_ROOT", str(a))
    assert roots.env_roots() == [b]


def test_env_roots_set_but_empty_is_loud(monkeypatch):
    monkeypatch.setenv("DJINNVIM_ROOTS", "")
    with pytest.raises(roots.RootsError):
        roots.env_roots()


def test_env_neither_set_returns_none(monkeypatch):
    monkeypatch.delenv("DJINNVIM_ROOTS", raising=False)
    monkeypatch.delenv("DJINNVIM_ROOT", raising=False)
    assert roots.env_roots() is None


def test_explicit_env_accepts_slash_and_home(monkeypatch):
    # explicit = deliberate: no sanity refusal on the env path
    monkeypatch.setenv("DJINNVIM_ROOTS", f"/{os.pathsep}{Path.home()}")
    assert roots.env_roots() == [Path("/"), Path.home().resolve()]


# --- sanity refusal per non-explicit source --------------------------------

@pytest.mark.parametrize("bad", [Path("/"), Path.home()])
@pytest.mark.parametrize(
    "source", ["client roots/list", "CLAUDE_PROJECT_DIR", "server working directory"]
)
def test_check_sane_refuses_slash_and_home(bad, source):
    with pytest.raises(roots.RootsError) as exc:
        roots.check_sane(bad, source)
    assert source in str(exc.value)
    assert "DJINNVIM_ROOTS" in str(exc.value)


def test_check_sane_passes_ordinary_dir(tree):
    a, _, _ = tree
    assert roots.check_sane(a, "client roots/list") == a


def test_fallback_prefers_claude_project_dir(tree, monkeypatch):
    a, _, _ = tree
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(a))
    assert roots.fallback_roots() == [a]


def test_fallback_refuses_home_project_dir(monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(Path.home()))
    with pytest.raises(roots.RootsError):
        roots.fallback_roots()


def test_fallback_uses_cwd(tree, monkeypatch):
    a, _, _ = tree
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(a)
    assert roots.fallback_roots() == [a]


def test_fallback_refuses_home_cwd(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(Path.home())
    with pytest.raises(roots.RootsError):
        roots.fallback_roots()


# --- the server's lazy resolution ------------------------------------------

def test_ensure_roots_falls_back_without_client(tree, monkeypatch):
    a, _, _ = tree
    monkeypatch.setattr(server, "_ENV_ROOTS", None)
    monkeypatch.setattr(server, "session", Session())
    monkeypatch.setattr(server, "_roots_stale", False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(a))
    assert asyncio.run(server._ensure_roots(None)) is None
    assert server.session.roots == [a]


def test_ensure_roots_refusal_surfaces_as_error_string(monkeypatch):
    monkeypatch.setattr(server, "_ENV_ROOTS", None)
    monkeypatch.setattr(server, "session", Session())
    monkeypatch.setattr(server, "_roots_stale", False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(Path.home()))
    out = asyncio.run(server._ensure_roots(None))
    assert out.startswith("error: refusing")
    assert server.session.roots is None  # nothing granted


def test_ensure_roots_env_is_pinned(tree, monkeypatch):
    # DJINNVIM_ROOTS present: no refetch even when flagged stale
    a, b, _ = tree
    monkeypatch.setattr(server, "_ENV_ROOTS", [a])
    monkeypatch.setattr(server, "session", Session(roots=[a]))
    monkeypatch.setattr(server, "_roots_stale", True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(b))
    assert asyncio.run(server._ensure_roots(None)) is None
    assert server.session.roots == [a]


def test_ensure_roots_stale_triggers_refetch(tree, monkeypatch):
    a, b, _ = tree
    monkeypatch.setattr(server, "_ENV_ROOTS", None)
    monkeypatch.setattr(server, "session", Session(roots=[a]))
    monkeypatch.setattr(server, "_roots_stale", True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(b))
    assert asyncio.run(server._ensure_roots(None)) is None
    assert server.session.roots == [b]
