"""Per-session daemon + thin client for the CLI (built 2026-07-25).

The daemon is conceptually the MCP server's Session kept alive for shell
users: each CLI verb runs as a fresh process, so something long-running must
hold the live Session (buffers, cursor, registers, undo). Parity with the
MCP path comes from sharing the exact in-memory Session class — zero
serialization, zero drift.

Protocol (settled 2026-07-25): one newline-delimited JSON request per
connection over a Unix socket — `{"v": VERSION, "op": ..., "args": {...}}`
answered by `{"ok": true, "result": str}` or `{"ok": false, "error": str}`
(plus `"restart": true` on a version mismatch). MCP framing over the socket
was considered and rejected: the client would need a full MCP client for six
string-in/string-out calls, and parity lives in the shared Session, not the
wire format. Tool-level errors ("error: no match") are ok results — loud
errors are content; `ok: false` means the daemon itself failed.

Lifecycle (ssh-agent-shaped): auto-spawn on first client call, idle
self-exit (default 1800 s, DJINNVIM_IDLE_SECONDS; unwritten buffers die
with the daemon — stateless by design, matching MCP-server-exit semantics,
and the next command fails loudly with "no active buffer" instead of
operating on ghost state), version handshake on every request (a stale
daemon replies restart + exits; the client respawns the new binary).
Socket keyed by resolved sandbox roots + a session discriminator
(DJINNVIM_SESSION → CLAUDE_CODE_SESSION_ID → parent shell PID), under
$XDG_RUNTIME_DIR/djinnvim/. Concurrent-spawn races resolve by bind
exclusivity: the loser exits, the client retries the connect.
"""

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from . import guard
from . import roots as roots_mod
from .session import Session

IDLE_DEFAULT = 1800.0
SESSION_OPS = ("open", "motion", "edit", "substitute", "print", "matches", "write")


class DaemonError(Exception):
    pass


class _Restart(Exception):
    """Daemon is a stale version and is exiting; respawn and retry."""


def resolve_roots() -> list[Path]:
    roots = roots_mod.env_roots()
    if roots is None:
        roots = roots_mod.fallback_roots()
    return roots


def session_discriminator() -> str:
    """Session key so concurrent agent sessions never share a Session
    (cursor, registers, undo) — that would silently break MCP parity."""
    return (
        os.environ.get("DJINNVIM_SESSION")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or f"ppid-{os.getppid()}"
    )


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        d = Path(base) / "djinnvim"
    else:
        d = Path(tempfile.gettempdir()) / f"djinnvim-{os.getuid()}"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def socket_path(roots: list[Path] | None = None, disc: str | None = None) -> Path:
    roots = resolve_roots() if roots is None else roots
    disc = session_discriminator() if disc is None else disc
    key = json.dumps([sorted(str(r) for r in roots), disc])
    return runtime_dir() / (hashlib.sha256(key.encode()).hexdigest()[:16] + ".sock")


# ---------------------------------------------------------------- client


def _send(path: Path, payload: dict) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(30)
        s.connect(str(path))
        f = s.makefile("rwb")
        f.write(json.dumps(payload).encode() + b"\n")
        f.flush()
        line = f.readline()
    if not line:
        raise ConnectionResetError("daemon closed the connection without replying")
    resp = json.loads(line)
    if resp.get("restart"):
        raise _Restart
    if not resp.get("ok"):
        raise DaemonError(resp.get("error", "daemon error"))
    return resp["result"]


def _spawn(roots: list[Path], disc: str) -> None:
    """Detach a daemon for this key. Env pins roots + discriminator so the
    daemon derives the identical socket path regardless of its own cwd/ppid."""
    env = dict(os.environ)
    env["DJINNVIM_ROOTS"] = os.pathsep.join(str(r) for r in roots)
    env.pop("DJINNVIM_ROOT", None)
    env["DJINNVIM_SESSION"] = disc
    log = socket_path(roots, disc).with_suffix(".log")
    with open(log, "ab") as lf:
        subprocess.Popen(
            [sys.executable, "-m", "djinnvim", "daemon"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=lf,
            stderr=lf,
            start_new_session=True,
        )


def request(op: str, args: dict, spawn: bool = True) -> str:
    """Send one op to this session's daemon, auto-spawning it if needed."""
    roots = resolve_roots()
    disc = session_discriminator()
    path = socket_path(roots, disc)
    payload = {"v": __version__, "op": op, "args": args}
    spawned = False
    deadline = time.monotonic() + 10.0
    while True:
        try:
            return _send(path, payload)
        except _Restart:
            spawned = False  # old version is unlinking + exiting; respawn below
            time.sleep(0.05)
        except (FileNotFoundError, ConnectionRefusedError, ConnectionResetError) as e:
            if not spawn:
                raise DaemonError(f"no daemon running for this session ({path})") from e
            if not spawned:
                if path.exists():
                    path.unlink(missing_ok=True)  # stale socket from a dead daemon
                _spawn(roots, disc)
                spawned = True
                deadline = time.monotonic() + 10.0
            if time.monotonic() > deadline:
                raise DaemonError(
                    f"daemon did not come up at {path} — see {path.with_suffix('.log')}"
                ) from e
            time.sleep(0.05)


# ---------------------------------------------------------------- daemon


def _status(session: Session, disc: str) -> str:
    lines = [
        f"djinnvim daemon — pid {os.getpid()}, version {__version__}",
        f"session: {disc}",
        f"roots: {', '.join(str(r) for r in (session.roots or []))}",
    ]
    if session.buffers:
        for p, b in session.buffers.items():
            mark = " (unwritten changes)" if b.dirty else ""
            active = " [active]" if b is session.active else ""
            lines.append(f"buffer: {p}{mark}{active}")
    else:
        lines.append("buffers: none open")
    idle = os.environ.get("DJINNVIM_IDLE_SECONDS", str(int(IDLE_DEFAULT)))
    lines.append(f"idle exit after {idle}s without a command")
    return "\n".join(lines)


def _handle(conn: socket.socket, session: Session, disc: str) -> bool:
    """Serve one request. Returns True when the daemon should exit."""
    f = conn.makefile("rwb")

    def reply(obj: dict) -> None:
        f.write(json.dumps(obj).encode() + b"\n")
        f.flush()

    line = f.readline()
    if not line:
        return False
    try:
        req = json.loads(line)
    except json.JSONDecodeError:
        reply({"ok": False, "error": "malformed request (not JSON)"})
        return False
    op, args = req.get("op"), req.get("args") or {}
    # status/shutdown work across versions: pinging a stale daemon must not
    # kill it, and shutdown must always be able to.
    if req.get("v") != __version__ and op not in ("status", "shutdown"):
        reply(
            {
                "ok": False,
                "restart": True,
                "error": f"daemon is version {__version__}, client {req.get('v')} — restarting",
            }
        )
        return True
    try:
        if op == "shutdown":
            reply({"ok": True, "result": f"daemon (pid {os.getpid()}) shut down"})
            return True
        if op == "status":
            reply({"ok": True, "result": _status(session, disc)})
            return False
        if op not in SESSION_OPS:
            reply({"ok": False, "error": f"unknown op: {op!r}"})
            return False
        try:
            result = guard.run_guarded(op, getattr(session, op), **args)
        except guard.OpTimeout as e:
            result = f"error: {e}"
        reply({"ok": True, "result": result})
    except Exception as e:  # a Session bug must not take the daemon down
        reply({"ok": False, "error": f"{type(e).__name__}: {e}"})
    return False


def daemon_main() -> int:
    try:
        roots = resolve_roots()
    except roots_mod.RootsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    disc = session_discriminator()
    path = socket_path(roots, disc)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(path))
    except OSError:
        return 0  # loser of a concurrent-spawn race; a daemon is already bound
    os.chmod(path, 0o600)
    sock.listen(8)
    idle = float(os.environ.get("DJINNVIM_IDLE_SECONDS", str(IDLE_DEFAULT)))
    session = Session(roots=roots)
    stop = False
    try:
        while not stop:
            sock.settimeout(idle if idle > 0 else None)
            try:
                conn, _ = sock.accept()
            except TimeoutError:
                break  # idle self-exit
            with conn:
                stop = _handle(conn, session, disc)
    finally:
        sock.close()
        path.unlink(missing_ok=True)
    return 0
