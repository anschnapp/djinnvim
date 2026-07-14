"""E2E over MCP stdio: the global anchored edit (v0.8). A purge-blocks-shaped
task: matches pre-check → the vim reflex `:g/pat/normal` fails loudly and
signposts `at each` → `at each /# DEPRECATED/ dap` removes both marked blocks
in one call with a plain-text ±diff echo → `u` reverts the whole batch in one
step → redo → write, exact target diff. Also the transactional rollback:
a command that fails at one site leaves the file untouched."""

import asyncio
import sys
import tempfile
import textwrap
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PIPELINE = textwrap.dedent("""\
    \"\"\"Pipeline helpers.\"\"\"


    # DEPRECATED: use merge_totals instead
    def scale_totals(rows):
        return [r * 2 for r in rows]


    def merge_totals(rows):
        return sum(rows)


    # DEPRECATED: use render_rows instead
    def print_rows(rows):
        for row in rows:
            print(row)


    def render_rows(rows):
        return "\\n".join(str(r) for r in rows)
""")

TARGET = textwrap.dedent("""\
    \"\"\"Pipeline helpers.\"\"\"


    def merge_totals(rows):
        return sum(rows)


    def render_rows(rows):
        return "\\n".join(str(r) for r in rows)
""")


async def main() -> None:
    root = Path(tempfile.mkdtemp())
    (root / "pipeline.py").write_text(PIPELINE)

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

        await call("open", path="pipeline.py")

        # plan: see every marked site first (principle #4)
        out = await call("matches", pattern="# DEPRECATED")
        assert "2 match(es) on 2 line(s)" in out

        # the vim reflex fails loudly and names the supported form
        out = await call("substitute", command=":g/# DEPRECATED/normal dap")
        assert "at each /# DEPRECATED/ <cmd>" in out

        # transactional: ci( fails at these sites — nothing changes
        out = await call("edit", command="at each /# DEPRECATED/ ci( x")
        assert "no changes applied" in out

        # the batch: both marker+function blocks gone in one call, diff echo
        out = await call("edit", command="at each /# DEPRECATED/ dap")
        assert "edited 2 match(es)" in out
        assert "\n" in out and "\\n" not in out.replace('"\\n"', "")  # plain text
        assert "- " in out and "def scale_totals" in out

        # one undo step reverts the whole batch
        out = await call("edit", command="u")
        assert "at each /# DEPRECATED/ dap" in out
        out = await call("matches", pattern="# DEPRECATED")
        assert "2 match(es)" in out

        # redo and write
        await call("edit", command="at each /# DEPRECATED/ dap")
        await call("write")

    got = (root / "pipeline.py").read_text()
    assert got == TARGET, f"pipeline.py mismatch:\n{got!r}\nvs\n{TARGET!r}"
    print("\nE2E EACH PASSED — exact target match")


if __name__ == "__main__":
    asyncio.run(main())
