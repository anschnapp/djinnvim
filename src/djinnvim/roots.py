"""Sandbox root resolution (multi-root, decided 2026-07-20).

Resolution chain: DJINNVIM_ROOTS (explicit, exclusive — client roots are
ignored entirely when it is set) → DJINNVIM_ROOT (one-entry alias) → MCP
roots/list from the client → CLAUDE_PROJECT_DIR → server cwd. `/` and $HOME
are refused as roots from every non-explicit source; via the env vars they
are accepted (explicit = deliberate). All roots are peers — no primary.

The sandbox confines the agent (model-generated paths, prompt injection),
not a hostile local user: TOCTOU races and hardlinks into a root are out of
scope, matching the exposure of native editing tools.
"""

import os
from pathlib import Path


class RootsError(Exception):
    pass


def env_roots() -> list[Path] | None:
    """Explicit roots from DJINNVIM_ROOTS / DJINNVIM_ROOT, or None.

    DJINNVIM_ROOTS is os.pathsep-separated (the PATH convention, so `C:\\`
    survives on Windows); DJINNVIM_ROOT is a single path, kept as an alias.
    No sanity refusal here: an env var is the deliberate, pinned boundary.
    """
    joined = os.environ.get("DJINNVIM_ROOTS")
    if joined is not None:
        parts = [p for p in joined.split(os.pathsep) if p.strip()]
        if not parts:
            raise RootsError("DJINNVIM_ROOTS is set but contains no paths")
        return [Path(p).resolve() for p in parts]
    single = os.environ.get("DJINNVIM_ROOT")
    if single:
        return [Path(single).resolve()]
    return None


def check_sane(path: Path, source: str) -> Path:
    """Resolve a non-explicit root, refusing `/` and $HOME loudly."""
    p = path.resolve()
    if p == Path(p.anchor) or p == Path.home().resolve():
        raise RootsError(
            f"refusing {p} as sandbox root (from {source}) — "
            "set DJINNVIM_ROOTS explicitly if you mean this"
        )
    return p


def fallback_roots() -> list[Path]:
    """Roots when the client offers none: CLAUDE_PROJECT_DIR, then cwd."""
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if project:
        return [check_sane(Path(project), "CLAUDE_PROJECT_DIR")]
    return [check_sane(Path.cwd(), "server working directory")]
