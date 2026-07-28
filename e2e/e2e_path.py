"""E2E over MCP stdio: v0.19 — the optional `path` on every op but motion.

The problem it answers is tool *selection*, not capability: used through a
third-party harness (Copilot, Opus 4.8) djinnvim was never picked, because a
one-line change cost open + edit + write against a native editor's single
stateless call. `path` removes the setup call and makes each tool read as
self-contained in the schema.

Checked here on the wire: the schema really advertises `path`, one call
edits a file that was never opened, the buffer switch is announced rather
than silent, and the implicit switch refuses to discard unwritten changes.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LINES = [
    "def parse_config(path):",
    "    opts = {}",
    "    for line in open(path):",
    "        key, val = line.split('=')",
    "        opts[key.strip()] = val",
    "    return opts",
]

OTHER = ["import json", "", "TIMEOUT = 15"]


async def main() -> None:
    root = Path(tempfile.mkdtemp())
    f = root / "config.py"
    f.write_text("\n".join(LINES) + "\n")
    g = root / "settings.py"
    g.write_text("\n".join(OTHER) + "\n")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "djinnvim.server"],
        env={"DJINNVIM_ROOT": str(root)},
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()

        # --- the schema is what a model selects on ---
        tools = {t.name: t for t in (await s.list_tools()).tools}
        for name in ("edit", "substitute", "print", "matches", "write"):
            props = tools[name].inputSchema["properties"]
            assert "path" in props, f"{name} does not advertise path"
            assert "path" not in (tools[name].inputSchema.get("required") or [])
        assert "path" not in tools["motion"].inputSchema["properties"]
        print(">>> path advertised on all five ops, optional, absent on motion")

        async def call(tool, **kw):
            res = await s.call_tool(tool, kw)
            text = res.content[0].text
            print(f"\n>>> {tool} {kw}\n{text}")
            return text

        # --- one call, no open: find the sites, then change one ---
        out = await call("matches", pattern="opts", path="config.py")
        assert "now on" in out and "3 match" in out

        out = await call("edit", command="at /parse_config/ ciw load_config",
                         path="config.py")
        assert "error:" not in out and "load_config" in out
        assert "now on" not in out, "same buffer: the note must stay quiet"

        # --- switching files mid-session announces itself ---
        out = await call("edit", command="at /15/ ciw 30", path="settings.py")
        assert "now on" in out and "settings.py" in out and "TIMEOUT = 30" in out

        # --- write picks its buffer too, so neither edit is lost ---
        out = await call("write", path="config.py")
        assert "wrote" in out and "config.py" in out
        out = await call("write", path="settings.py")
        assert "wrote" in out and "settings.py" in out

        # --- the carve-out: an implicit switch never discards unwritten work ---
        await call("edit", command="at /load_config/ ciw parse_config",
                   path="config.py")
        f.write_text("\n".join(LINES) + "\n# touched by someone else\n")
        out = await call("edit", command="at /return opts/ dd", path="config.py")
        assert out.startswith("error:") and "changed on disk" in out
        out = await call("print", command="p", path="config.py")
        assert out.startswith("error:"), "a stale dirty buffer stays loud"

    # config.py was deliberately clobbered from outside above; the point is
    # that djinnvim refused to write over it, so the foreign edit survives.
    assert f.read_text().endswith("# touched by someone else\n"), f.read_text()
    assert "TIMEOUT = 30" in g.read_text(), g.read_text()
    print("\ne2e_path OK")


asyncio.run(main())
