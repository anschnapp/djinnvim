"""E2E over MCP stdio: v0.14 — anchor offsets on the anchored form and the
write preview. Dogfood #7's two friction points replayed as the intended
one-call idioms: insert above a comment banner with `at /pat/-1 O` (was 3
calls), then review EVERYTHING pending with write(preview=True) before a
single byte reaches disk."""

import asyncio
import sys
import tempfile
import textwrap
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

APP = textwrap.dedent("""\
    def run(orbs):
        return [o for o in orbs if o.alive]


    # ---
    # Merge logic
    # ---
    def merge(a, b):
        return a + b
""")


async def main() -> None:
    root = Path(tempfile.mkdtemp())
    f = root / "app.py"
    f.write_text(APP)

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

        # dogfood #7: landing ABOVE the banner took motion + motion + O.
        # The offset form is one call — anchor on the banner's unique line,
        # -1 puts the cursor on its top `# ---`, O inserts above the block.
        # (no trailing \n: since v0.15 every \n in TEXT is literal — one
        # Enter each — so it would add a blank line besides the constant)
        out = await call("edit", command="at /# Merge logic/-1 O MERGE_LIMIT = 4")
        assert "offset -1" in out
        assert "MERGE_LIMIT = 4" in out

        # an out-of-range offset is loud and touches nothing
        out = await call("edit", command="at /def run/-5 dd")
        assert out.startswith("error:")
        assert "lands outside the file" in out

        # a second pending change, then the full review: buffer vs disk
        await call("edit", command="at /o.alive/ A  and o.group is None")
        out = await call("write", preview=True)
        assert "2 line(s) differ from disk" in out
        assert "nothing written" in out
        assert "+ 5  MERGE_LIMIT = 4" in out  # pure insertion, + line only
        assert "and o.group is None" in out
        assert f.read_text() == APP, "preview must not write"

        # commit; the count matches what the preview showed
        out = await call("write", preview=False)
        assert "2 line(s) changed" in out
        assert "MERGE_LIMIT = 4" in f.read_text()
        assert "and o.group is None" in f.read_text()

        # after the write the preview is clean
        out = await call("write", preview=True)
        assert out.startswith("no unwritten changes")

    print("\nE2E v0.14 (anchor offsets + write preview): all assertions passed")


if __name__ == "__main__":
    asyncio.run(main())
