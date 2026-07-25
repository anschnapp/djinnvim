"""Daemon + thin client: socket keying, auto-spawn, cross-call state,
version handshake, idle exit, shutdown. These spawn real daemon
subprocesses (the auto-spawn path is the thing under test) inside a
tmp XDG_RUNTIME_DIR, so nothing leaks into the user's runtime dir."""

import json
import time

import pytest

from djinnvim import __version__, daemon


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "f.py").write_text("alpha = 1\nbeta = 2\ngamma = 3\n")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("DJINNVIM_ROOTS", str(root))
    monkeypatch.delenv("DJINNVIM_ROOT", raising=False)
    monkeypatch.setenv("DJINNVIM_SESSION", "test-session")
    monkeypatch.setenv("DJINNVIM_IDLE_SECONDS", "30")
    yield root
    for sock in (tmp_path / "rt" / "djinnvim").glob("*.sock"):
        try:
            daemon._send(sock, {"v": __version__, "op": "shutdown", "args": {}})
        except Exception:
            pass


def _wait_gone(path, timeout=5.0):
    deadline = time.monotonic() + timeout
    while path.exists():
        if time.monotonic() > deadline:
            raise AssertionError(f"{path} still exists after {timeout}s")
        time.sleep(0.05)


def test_socket_path_keys_on_roots_and_session(env, monkeypatch):
    p1 = daemon.socket_path()
    assert p1 == daemon.socket_path()  # deterministic
    monkeypatch.setenv("DJINNVIM_SESSION", "other-session")
    p2 = daemon.socket_path()
    other = env.parent / "other-root"
    other.mkdir()
    monkeypatch.setenv("DJINNVIM_SESSION", "test-session")
    monkeypatch.setenv("DJINNVIM_ROOTS", str(other))
    p3 = daemon.socket_path()
    assert len({p1, p2, p3}) == 3
    assert p1.parent.name == "djinnvim"


def test_autospawn_and_state_persists_across_requests(env):
    out = daemon.request("open", {"path": "f.py"})
    assert "3 lines" in out
    out = daemon.request("edit", {"command": "at /alpha/ ciw omega"})
    assert "omega" in out
    out = daemon.request("write", {})
    assert "1 line" in out
    assert (env / "f.py").read_text().startswith("omega = 1")


def test_tool_level_errors_are_results_not_failures(env):
    out = daemon.request("motion", {"command": "gg"})
    assert out.startswith("error:")  # no active buffer — loud, not an exception


def test_unknown_op_is_a_daemon_error(env):
    daemon.request("status", {})
    with pytest.raises(daemon.DaemonError, match="unknown op"):
        daemon.request("frobnicate", {})


def test_status_reports_buffers_and_session(env):
    daemon.request("open", {"path": "f.py"})
    daemon.request("edit", {"command": "at /beta/ ciw delta"})
    out = daemon.request("status", {})
    assert f"version {__version__}" in out
    assert "test-session" in out
    assert "f.py (unwritten changes) [active]" in out


def test_shutdown_removes_socket_and_daemon(env):
    daemon.request("status", {})
    path = daemon.socket_path()
    assert path.exists()
    out = daemon.request("shutdown", {})
    assert "shut down" in out
    _wait_gone(path)


def test_version_mismatch_restarts_daemon(env):
    daemon.request("open", {"path": "f.py"})
    path = daemon.socket_path()
    with pytest.raises(daemon._Restart):
        daemon._send(path, {"v": "0-bogus", "op": "open", "args": {"path": "f.py"}})
    _wait_gone(path)  # stale daemon unlinked its socket and exited
    # next request auto-spawns a fresh daemon: state is gone, loudly
    out = daemon.request("motion", {"command": "gg"})
    assert out.startswith("error:")


def test_status_and_shutdown_survive_version_mismatch(env):
    daemon.request("status", {})
    path = daemon.socket_path()
    out = daemon._send(path, {"v": "0-bogus", "op": "status", "args": {}})
    assert f"version {__version__}" in out  # ping must not kill the daemon
    assert path.exists()
    out = daemon._send(path, {"v": "0-bogus", "op": "shutdown", "args": {}})
    assert "shut down" in out
    _wait_gone(path)


def test_idle_exit(env, monkeypatch):
    monkeypatch.setenv("DJINNVIM_IDLE_SECONDS", "0.3")
    daemon.request("status", {})
    path = daemon.socket_path()
    _wait_gone(path, timeout=5.0)


def test_malformed_request_gets_error_reply(env):
    daemon.request("status", {})
    import socket as socket_mod

    with socket_mod.socket(socket_mod.AF_UNIX) as s:
        s.connect(str(daemon.socket_path()))
        s.sendall(b"not json\n")
        resp = json.loads(s.makefile("rb").readline())
    assert resp["ok"] is False
    assert "malformed" in resp["error"]
    # and the daemon survived
    assert "version" in daemon.request("status", {})
