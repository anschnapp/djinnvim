"""E2E over MCP stdio: the op time budget (2026-08-01).

The wedge this guards is invisible to unit tests, because it is a property
of the *server process*, not of a function: every tool is `async def`, so a
catastrophic regex blocked the event loop and no further tool call could be
served. `re` releases neither signals nor the GIL while backtracking, so
nothing in-process could recover it.

So this measures the thing that actually matters to a client: after a
runaway pattern, is the server still answering, and did the buffer survive
with its unwritten changes intact? A guard that killed the server would
pass a unit test and fail here.
"""

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EVIL = r"(a+)+$b"
BUDGET = "3"


async def main() -> None:
    root = Path(tempfile.mkdtemp())
    victim = root / "app.py"
    victim.write_text("x = 1\ny = 2\n")
    (root / "evil.txt").write_text("a" * 60 + "\n")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "djinnvim.server"],
        env={"DJINNVIM_ROOT": str(root), "DJINNVIM_OP_BUDGET_SECONDS": BUDGET},
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()

        async def call(tool: str, **kw) -> str:
            res = await s.call_tool(tool, kw)
            return res.content[0].text

        # An unwritten change that must outlive the runaway pattern.
        out = await call("edit", command="at /x = 1/ A   # keep me", path=str(victim))
        assert "keep me" in out, out

        # The wedge: this used to block the event loop forever.
        started = time.monotonic()
        out = await call("matches", pattern=EVIL, path=str(root / "evil.txt"))
        elapsed = time.monotonic() - started
        assert "error:" in out, f"expected a loud error, got: {out}"
        assert "runaway pattern" in out, out
        assert elapsed < float(BUDGET) + 10, f"took {elapsed:.1f}s"
        print(f"runaway pattern refused in {elapsed:.1f}s: {out.splitlines()[0][:80]}")

        # The server must still be serving. This is the whole point.
        out = await call("matches", pattern="y", path=str(victim))
        assert "1 match" in out, out

        # ... and the buffer must still hold its unwritten change.
        out = await call("write", preview=True, path=str(victim))
        assert "keep me" in out, f"unwritten change lost to the timeout: {out}"

        out = await call("write", path=str(victim))
        assert "wrote" in out, out
        assert "keep me" in victim.read_text()

        # A legitimate slow-looking pattern must not be refused.
        out = await call("matches", pattern=r"^\s*\w+\s*=\s*\d+$", path=str(victim))
        assert "match" in out and "error:" not in out, out

    print("e2e_guard: OK")


asyncio.run(main())
