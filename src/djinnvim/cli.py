"""Command-line entry point (subcommand surface, decided 2026-07-25).

`djinnvim mcp` runs the stdio MCP server. The editing verbs mirror the six
tool names (open, motion, edit, substitute, matches, write) and talk to a
per-session daemon holding the live Session (see daemon.py). `status` /
`shutdown` make the daemon discoverable and killable — "hidden" means
"auto-managed", never "unkillable". Bare `djinnvim` (no arguments) still
runs the MCP server: the pre-subcommand entry point, kept working until
MCP configs and the benchmark runner have flipped to `djinnvim mcp`.

Verb commands must arrive as ONE shell argument (`djinnvim edit 'at /pat/
ciw new'`): re-joining split argv on spaces would silently collapse the
whitespace that TEXT preserves verbatim (`o     x = 1`), so multiple
arguments are a loud error instead.
"""

import argparse
import sys

from . import __version__


def _run_mcp(_args: argparse.Namespace) -> int:
    from .server import main as server_main

    server_main()
    return 0


def _run_daemon(_args: argparse.Namespace) -> int:
    from .daemon import daemon_main

    return daemon_main()


def _print_result(result: str) -> int:
    print(result)
    return 1 if result.startswith("error:") else 0


def _request(op: str, args: dict, spawn: bool = True) -> int:
    from . import daemon
    from .roots import RootsError

    try:
        return _print_result(daemon.request(op, args, spawn=spawn))
    except (daemon.DaemonError, RootsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _one_command(op: str, parts: list[str]) -> str | None:
    if len(parts) == 1:
        return parts[0]
    print(
        f"error: pass the {op} command as ONE shell argument — quote it, "
        f"e.g. djinnvim {op} 'at /pattern/ ciw new_name'",
        file=sys.stderr,
    )
    return None


def _run_open(args: argparse.Namespace) -> int:
    return _request("open", {"path": args.path})


def _make_verb(op: str):
    def run(args: argparse.Namespace) -> int:
        command = _one_command(op, args.command)
        if command is None:
            return 2
        return _request(op, {"command": command})

    return run


def _run_matches(args: argparse.Namespace) -> int:
    return _request("matches", {"pattern": args.pattern, "context": args.context})


def _run_write(_args: argparse.Namespace) -> int:
    return _request("write", {})


def _run_install_skill(args: argparse.Namespace) -> int:
    from importlib.resources import files
    from pathlib import Path

    content = (files("djinnvim") / "skill" / "SKILL.md").read_text()
    base = Path.cwd() if args.project else Path.home()
    dest = base / ".claude" / "skills" / "djinnvim" / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    existed = dest.exists()
    dest.write_text(content)
    print(f"{'updated' if existed else 'installed'} {dest}")
    return 0


def _run_status(_args: argparse.Namespace) -> int:
    from . import daemon

    rt = daemon.runtime_dir()
    socks = sorted(rt.glob("*.sock"))
    if not socks:
        print("no djinnvim daemon running")
        return 0
    try:
        current = daemon.socket_path()
    except Exception:
        current = None
    for s in socks:
        marker = "  (this session)" if s == current else ""
        try:
            out = daemon._send(s, {"v": __version__, "op": "status", "args": {}})
        except Exception as e:
            out = f"unreachable ({e}) — stale socket?"
        body = "\n".join("  " + line for line in out.splitlines())
        print(f"{s.name}{marker}\n{body}")
    return 0


def _run_shutdown(args: argparse.Namespace) -> int:
    from . import daemon

    if args.all:
        targets = sorted(daemon.runtime_dir().glob("*.sock"))
        if not targets:
            print("no djinnvim daemon running")
            return 0
    else:
        targets = [daemon.socket_path()]
    code = 0
    for t in targets:
        try:
            print(daemon._send(t, {"v": __version__, "op": "shutdown", "args": {}}))
        except FileNotFoundError:
            print("no daemon running for this session")
        except Exception as e:
            print(f"error: {t.name}: {e}", file=sys.stderr)
            code = 2
    return code


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="djinnvim",
        description="Vim-inspired keyhole editing for AI agents: "
        "MCP server (djinnvim mcp) and CLI verbs backed by a session daemon.",
    )
    p.add_argument("--version", action="version", version=f"djinnvim {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("mcp", help="run the stdio MCP server")
    sp.set_defaults(func=_run_mcp)

    sp = sub.add_parser(
        "daemon", help="run the session daemon in the foreground (normally auto-spawned)"
    )
    sp.set_defaults(func=_run_daemon)

    sp = sub.add_parser("open", help="open a file as the active buffer")
    sp.add_argument("path")
    sp.set_defaults(func=_run_open)

    for op, doc in (
        ("motion", "move the cursor: '/pattern', ':80', 'n', 'gg', 'G', 'fx'"),
        ("edit", "vim normal-mode edit: 'at /pattern/ ciw new', 'dd', 'u'"),
        ("substitute", "ex command: ':%s/old/new/g', ':g/pat/d'"),
    ):
        sp = sub.add_parser(op, help=doc)
        sp.add_argument(
            "command",
            nargs="+",
            help="the whole command as ONE quoted argument",
        )
        sp.set_defaults(func=_make_verb(op))

    sp = sub.add_parser("matches", help="grep-style listing of all matches")
    sp.add_argument("pattern")
    sp.add_argument("-C", "--context", type=int, choices=(0, 1), default=0)
    sp.set_defaults(func=_run_matches)

    sp = sub.add_parser("write", help="save the active buffer to disk")
    sp.set_defaults(func=_run_write)

    sp = sub.add_parser(
        "install-skill",
        help="install the agent skill (SKILL.md) into ~/.claude/skills",
    )
    sp.add_argument(
        "--project",
        action="store_true",
        help="install into ./.claude/skills instead of the user-level directory",
    )
    sp.set_defaults(func=_run_install_skill)

    sp = sub.add_parser("status", help="show running session daemons")
    sp.set_defaults(func=_run_status)

    sp = sub.add_parser("shutdown", help="stop this session's daemon")
    sp.add_argument("--all", action="store_true", help="stop every daemon")
    sp.set_defaults(func=_run_shutdown)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if not argv:
        return _run_mcp(argparse.Namespace())
    args = build_parser().parse_args(argv)
    return args.func(args)
