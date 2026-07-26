"""E2E over MCP stdio: v0.16 — the print tool. Read a window around a
pattern (cursor moves there), peek without moving (bare p), page with an
explicit range, and hit the span cap loudly. The file is never modified
and never read whole."""

import asyncio
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

N = 400
LINES = [f"x{i + 1} = {i + 1}" for i in range(N)]
LINES[199] = "def load_config(path):"


async def main() -> None:
    root = Path(tempfile.mkdtemp())
    f = root / "app.py"
    f.write_text("\n".join(LINES) + "\n")

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

        await call("open", path="app.py")

        # jump-and-read: pattern address moves the cursor, window widens
        out = await call("print", command=":/def load_config/ p around tiny")
        head = out.splitlines()[0]
        assert head == "lines 192–208 of 400", head
        assert "→ 200  def load_config(path):" in out

        # bare p: current line only, from wherever the cursor now is
        out = await call("print", command="p")
        assert out.splitlines()[0] == "line 200 of 400"
        assert out.count("\n") == 1  # header + one line

        # paging: pick a gutter number from the previous window, range-print
        out = await call("print", command=":150,192 p")
        assert out.splitlines()[0] == "lines 150–192 of 400"
        assert "→ 192" in out  # cursor at the last printed line

        # the cap is loud — print never becomes a whole-file read
        out = await call("print", command=":1,400 p")
        assert out.startswith("error:") and "pages" in out

        # read-only: nothing pending, disk untouched
        out = await call("write", preview=True)
        assert out.startswith("no unwritten changes")
        assert f.read_text() == "\n".join(LINES) + "\n"

    print("\ne2e_print: all assertions passed")


if __name__ == "__main__":
    asyncio.run(main())
