"""djinnvim — vim-inspired, pattern-anchored keyhole editing for AI agents.

See design.md for the full design. Tool surface: open, motion, edit,
substitute, matches, write — exposed over MCP (server.py) and as CLI verbs
(cli.py, talking to a per-session daemon: daemon.py); both are thin wrappers
around session.Session.
"""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("djinnvim")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0+unknown"
