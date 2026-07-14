"""E2E over MCP stdio: labeled caret (v0.7) — the anchor-at-match-START
mistake becomes self-announcing BEFORE the edit. A search for /retries=15/
lands on the "r"; the caret label says so in prose (`on "r" of "retries"`),
so a model that meant to change the 15 re-anchors on the value instead of
issuing a ciw that would clobber the name. Verifies the label arrives as
plain multi-line text over the real protocol."""

import asyncio
import sys
import tempfile
import textwrap
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CONFIG = textwrap.dedent("""\
    def connect(host, port):
        return open_channel(host, port)


    def fetch(url,
              retries=15)
        return get(url)
""")


async def main() -> None:
    root = Path(tempfile.mkdtemp())
    (root / "config.py").write_text(CONFIG)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "djinnvim.server"],
        env={"DJINNVIM_ROOT": str(root)},
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()

        async def call(tool, **kw):
            res = await s.call_tool(tool, kw)
            assert res.structuredContent is None, "results must be plain text"
            text = res.content[0].text
            print(f"\n>>> {tool} {kw}\n{text}")
            return text

        await call("open", path="config.py")

        # anchor on the assignment: cursor lands at match START, and the
        # label SAYS so — this is the self-announcing moment
        out = await call("motion", command="/retries=15")
        assert '^ on "r" of "retries"' in out
        assert "\n" in out, "viewport must arrive as real multi-line text"

        # re-anchor on the value; the label confirms the cursor is on the 15
        out = await call("motion", command="/15")
        assert '^ on "1" of "15"' in out

        # the label named exactly what ciw changes — the safety property
        out = await call("edit", command="ciw 60")
        assert "retries=60" in out

        # punctuation + end-of-line label shapes over the wire
        out = await call("motion", command="f)")
        assert '^ on ")"' in out
        out = await call("motion", command="/$")
        assert "^ at end of line" in out

        await call("write")

    got = (root / "config.py").read_text()
    assert "retries=60" in got and "retries=15" not in got
    print("\nE2E LABELED CARET PASSED — label matched the ciw span exactly")


if __name__ == "__main__":
    asyncio.run(main())
