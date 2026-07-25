"""E2E over the real console script: the CLI + daemon path (2026-07-25).
Every verb is a fresh `djinnvim` process (exactly the shell-agent shape);
state must persist across them via the auto-spawned daemon: open → matches
pre-check → anchored ciw → substitute over-match caught in the diff → u
reverts it whole → scoped redo → write, exact target diff → status shows
the daemon → shutdown removes it. Also: the unquoted-command loud error,
and an isolated XDG_RUNTIME_DIR + DJINNVIM_SESSION so nothing touches the
user's real daemons."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / ".venv" / "bin" / "djinnvim"

START = """\
retries = 3

def fetch(url, retries=retries):
    return get(url, retries)

def fetch_cached(url):
    return fetch(url)
"""

TARGET = """\
retries = 5

def fetch_records(url, retries=retries):
    return get(url, retries)

def fetch_cached(url):
    return fetch_records(url)
"""


def main() -> None:
    base = Path(tempfile.mkdtemp())
    root = base / "proj"
    root.mkdir()
    (root / "app.py").write_text(START)

    env = dict(os.environ)
    env["XDG_RUNTIME_DIR"] = str(base / "rt")
    env["DJINNVIM_ROOTS"] = str(root)
    env.pop("DJINNVIM_ROOT", None)
    env["DJINNVIM_SESSION"] = "e2e-cli"
    env["DJINNVIM_IDLE_SECONDS"] = "60"

    def run(*args: str, code: int = 0) -> str:
        proc = subprocess.run(
            [str(BIN), *args], env=env, capture_output=True, text=True, timeout=30
        )
        out = (proc.stdout + proc.stderr).strip()
        print(f"\n$ djinnvim {' '.join(args)}\n{out}")
        assert proc.returncode == code, f"exit {proc.returncode}, wanted {code}: {out}"
        return out

    out = run("open", "app.py")
    assert "7 lines" in out

    # the unquoted-command trap fails loudly, buffer untouched
    out = run("edit", "at", "/fetch/", "ciw", "fetch_records", code=2)
    assert "ONE shell argument" in out

    # matches pre-check shows the decoy before any rename
    out = run("matches", r"\bfetch\b")
    assert "2 match" in out and "fetch_cached" not in out

    # over-matching substitute: the diff shows fetch_cached hit too
    out = run("substitute", ":%s/fetch/fetch_records/g")
    assert "fetch_records_cached" in out

    # u reverts the whole substitute; then the scoped redo
    out = run("edit", "u")
    assert "undid" in out or "undo" in out.lower()
    out = run("substitute", r":%s/\bfetch\b/fetch_records/g")
    assert "fetch_records_cached" not in out and "fetch_records" in out

    # tool-level error (loud, buffer untouched) sets exit 1
    out = run("edit", "at /no_such_pattern_xyz/ ciw q", code=1)
    assert out.startswith("error:")
    # anchored edit on the constant
    out = run("edit", "at /3$/ ciw 5")
    assert "retries = 5" in out

    out = run("write")
    assert "3 line" in out
    got = (root / "app.py").read_text()
    assert got == TARGET, f"diff:\n{got!r}\nvs\n{TARGET!r}"

    out = run("status")
    assert "this session" in out and "app.py" in out

    out = run("shutdown")
    assert "shut down" in out
    out = run("status")
    assert "no djinnvim daemon running" in out

    print("\ne2e_cli: all assertions passed")


if __name__ == "__main__":
    main()
