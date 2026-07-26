"""E2E over MCP stdio: v0.18 — what the client actually receives.

The bug this guards is invisible in normal use: Claude Code silently
truncates every MCP-supplied string at 2048 chars, and `edit` had shipped at
3944 since 2026-07-14, so half its guidance (the indent rule, registers,
undo, every example) never reached a model. Unit tests measure the source;
this measures the wire, and also checks the instructions channel is really
advertised in initialize, since that is where the cross-cutting contracts
now live.

Also exercises the v0.18 semantics themselves: cc autoindents like o/O, cc!
opts out, cip is gone with a signpost to dip.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Claude Code 2.1.220: LB=2048, applied to tool descriptions, server
# instructions and prompt bodies alike.
LIMIT = 2048

LINES = [
    "class Report:",
    "    def rows(self, raw):",
    "        members = old_call(raw)",
    "        return members",
    "",
    "    def total(self):",
    "        return 0",
]


async def main() -> None:
    root = Path(tempfile.mkdtemp())
    f = root / "report.py"
    f.write_text("\n".join(LINES) + "\n")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "djinnvim.server"],
        env={"DJINNVIM_ROOT": str(root)},
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        init = await s.initialize()

        # --- the channel that was never used ---
        instructions = init.instructions
        assert instructions, "server advertises no instructions"
        assert len(instructions) <= LIMIT, f"instructions {len(instructions)} > {LIMIT}"
        for contract in ("autoindent", "cc!", "backslash-n", "not the disk"):
            assert contract in instructions, f"missing cross-cutting rule: {contract}"
        print(f">>> instructions: {len(instructions)} chars, all contracts present")

        # --- the channel that was overflowing ---
        tools = (await s.list_tools()).tools
        assert len(tools) == 7, [t.name for t in tools]
        for t in tools:
            n = len(t.description or "")
            print(f"    {t.name:12} {n:5} chars")
            assert n <= LIMIT, f"{t.name} would be truncated: {n} > {LIMIT}"
            assert "[truncated]" not in (t.description or "")

        async def call(tool, **kw):
            res = await s.call_tool(tool, kw)
            text = res.content[0].text
            print(f"\n>>> {tool} {kw}\n{text}")
            return text

        await call("open", path="report.py")

        # cc now inherits the replaced line's own indent (vim autoindent).
        # Pre-v0.18 this landed at column 0 and broke the class body.
        out = await call("edit", command="at /members = old_call/ cc members = sorted(raw)")
        assert "        members = sorted(raw)" in out

        # the bang opts out, for text that is already absolutely indented
        out = await call("edit", command="at /return members/ cc!         return members")
        assert "error:" not in out

        # cip is gone and says where to go instead
        out = await call("edit", command="at /def total/ cip pass")
        assert out.startswith("error:") and "dip" in out

        # dap still works: it is the load-bearing paragraph form
        out = await call("edit", command="at /def total/ dap")
        assert "deleted lines" in out

        out = await call("write")
        assert "wrote" in out or "saved" in out.lower()

    saved = f.read_text().splitlines()
    assert saved[2] == "        members = sorted(raw)", saved
    assert saved[3] == "        return members", saved
    assert not any("def total" in line for line in saved), saved
    print("\ne2e_budget OK")


asyncio.run(main())
