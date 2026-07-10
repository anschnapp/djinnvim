"""djinnvim — vim-inspired, pattern-anchored keyhole editing for AI agents.

See design.md for the full design. Tool surface: open, motion, edit,
substitute, matches, write — exposed over MCP (server.py) and, later, a CLI;
both are thin wrappers around session.Session.
"""
