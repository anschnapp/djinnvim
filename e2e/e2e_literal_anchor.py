"""E2E over MCP stdio: v0.17 — the literal anchor plus the dogfood #9
guidance fixes. Anchor on a line full of regex punctuation without escaping
anything, delete a line by pattern (the ex-address reflex gets signposted),
insert a blank line with bare O, and insert multi-line TEXT with real
newlines. The file is never read whole."""

import asyncio
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LINES = [
    "import sys",
    "",
    "# merge (skip blocks...)",
    "def merge(a, b):",
    "    print(sys.argv)",
    "    return a + b",
    "debug_line = 1",
    "",
    "def done():",
    "    return 0",
]


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

        # the regex form needs escaping on this anchor: unescaped, the parens
        # are a group and the dots are wildcards, so it silently misses
        out = await call("edit", command="at /# merge (skip blocks...)/ O above")
        assert out.startswith("error:") and "no match" in out

        # the literal form takes the line exactly as it reads on screen
        out = await call(
            "edit", command='at "# merge (skip blocks...)" O # section: merge'
        )
        assert "match 1 of 1" in out
        assert "blank line(s) above insertion point" in out

        # an ex address in edit is redirected, not just rejected
        out = await call("edit", command=":9 dd")
        assert out.startswith("error:") and "address by pattern instead" in out

        # ...to the pattern-addressed line delete, which stays valid as the
        # file shifts underneath it
        out = await call("edit", command="at /^debug_line/ dd")
        assert "deleted line 8" in out

        # bare O is how you add a blank line: one call, no substitute
        out = await call("edit", command="at /^def done/ O")
        assert "inserted 1 line(s) above line 9" in out

        # real newlines in TEXT open real lines; a backslash-n stays content
        # (o inherits the anchor line's 4-space indent for both lines)
        out = await call(
            "edit",
            command='at "    return a + b" o print("done\\nhere")\n# tail',
        )
        assert "inserted 2 line(s) below line 7" in out

        # every match found by the literal form, batched
        out = await call("edit", command='at each "a + b" ciw total')
        assert "1 match" in out or "1 of 1" in out or "edited 1" in out

        await call("write")

    target = [
        "import sys",
        "",
        "# section: merge",
        "# merge (skip blocks...)",
        "def merge(a, b):",
        "    print(sys.argv)",
        "    return total + b",
        '    print("done\\nhere")',
        "    # tail",
        "",
        "",
        "def done():",
        "    return 0",
    ]
    got = f.read_text().splitlines()
    assert got == target, "\n".join(f"{a!r} != {b!r}" for a, b in zip(got, target))
    print("\ne2e_literal_anchor: exact target match")


if __name__ == "__main__":
    asyncio.run(main())
