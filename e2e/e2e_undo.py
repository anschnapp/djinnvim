"""E2E over MCP stdio: undo as the recovery path — an over-matching
substitute reverted whole with u, then a scoped redo of the change, and an
undo that crosses a write boundary."""

import asyncio
import sys
import tempfile
import textwrap
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CODE = textwrap.dedent("""\
    timeout = 30
    retry = 2
    msg = "timeout exceeded"

    def wait(timeout):
        return timeout + retry

    # debug marker
""")

TARGET = textwrap.dedent("""\
    delay = 30
    retry = 2
    msg = "timeout exceeded"

    def wait(delay):
        return delay + retry

    # debug marker
""")


async def main() -> None:
    root = Path(tempfile.mkdtemp())
    (root / "a.py").write_text(CODE)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "djinnvim.server"],
        env={"DJINNVIM_ROOT": str(root)},
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()

        async def call(tool, **kw):
            res = await s.call_tool(tool, kw)
            text = res.content[0].text
            print(f"\n>>> {tool} {kw}\n{text}")
            return text

        await call("open", path="a.py")

        # nothing to undo yet: loud error
        out = await call("edit", command="u")
        assert "error: nothing to undo" in out

        # over-matching rename: the diff shows the string literal got hit too
        out = await call("substitute", command=":%s/timeout/delay/g")
        assert "4 substitution(s) on 4 line(s)" in out
        assert '"delay exceeded"' in out  # the over-match, visible in the diff

        # one u reverts the whole substitute
        out = await call("edit", command="u")
        assert "undid: :%s/timeout/delay/g" in out
        assert '"timeout exceeded"' in out  # viewport shows the string restored

        # redo it scoped: the assignment by anchor, the function by range
        out = await call("edit", command="at /timeout = 30/ ciw delay")
        assert "changed line 1" in out
        out = await call("substitute", command=":/def wait/,$s/timeout/delay/g")
        assert "2 substitution(s) on 2 line(s)" in out

        # undo across a write boundary
        out = await call("edit", command="at /# debug marker/ dd")
        assert "deleted line 8" in out
        await call("write")
        out = await call("edit", command="u")
        assert "undid: at /# debug marker/ dd" in out
        assert "# debug marker" in out
        assert "2 more undo step(s)" in out
        await call("write")

    assert (root / "a.py").read_text() == TARGET, (root / "a.py").read_text()
    print("\nE2E OK — file matches target exactly")


asyncio.run(main())
