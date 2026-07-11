"""E2E over MCP stdio: move a block within a file, then across files,
plus the wrong-name recovery path."""

import asyncio
import sys
import tempfile
import textwrap
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

A = textwrap.dedent("""\
    import os

    def helper(x):
        y = x + 1
        return y * 2

    def main():
        print(helper(3))
""")

B = textwrap.dedent("""\
    # utilities live here
    def existing():
        pass
""")

TARGET_A = textwrap.dedent("""\
    import os

    def main():
        print(helper(3))
""")

TARGET_B = textwrap.dedent("""\
    # utilities live here
    def existing():
        pass
    def helper(x):
        y = x + 1
        return y * 2
""")


async def main() -> None:
    root = Path(tempfile.mkdtemp())
    (root / "a.py").write_text(A)
    (root / "b.py").write_text(B)

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

        # cut helper() out of a.py: anchored normal-mode cut, one call
        # (dap takes the trailing blank line)
        await call("open", path="a.py")
        out = await call("edit", command='at /def helper/ "block dap')
        assert 'cut 4 line(s) (3–6) into register "block"' in out
        assert "def helper(x):" in out  # preview echoes the content

        # wrong-name recovery: error lists registers with previews
        out = await call("edit", command='"blok p')
        assert 'error: no register "blok"' in out
        assert '"block": def helper(x): ... (4 lines)' in out

        await call("write")

        # paste into b.py at the end
        await call("open", path="b.py")
        await call("motion", command="G")
        out = await call("edit", command='"block p')
        assert "pasted 4 line(s)" in out and "→" in out
        # trailing blank line came along; drop it
        await call("edit", command="dd")
        await call("write")

    assert (root / "a.py").read_text() == TARGET_A, (root / "a.py").read_text()
    assert (root / "b.py").read_text() == TARGET_B, (root / "b.py").read_text()
    print("\nE2E OK — both files match targets exactly")


asyncio.run(main())
