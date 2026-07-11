"""E2E over MCP stdio: address offsets (v0.5) — the dogfood #3 regression.
The old doc idiom `:/def a/,/^def /d fn` over-grabs (inclusive second
address swallows the next def line); shown live, reverted with u, then the
fixed recipe: `:/def a/,/^def /-1d fn` cut → cross-file `"fn P` paste above
the destination def, spacing correct on both sides, exact target diffs."""

import asyncio
import sys
import tempfile
import textwrap
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PIPELINE = textwrap.dedent("""\
    \"\"\"Pipeline helpers.\"\"\"


    def normalize(row):
        return row


    def validate_row(row):
        \"\"\"Check required fields.\"\"\"
        missing = []
        for field in ("id", "sku"):
            if not row.get(field):
                missing.append(field)

        if missing:
            return False, missing
        return True, []


    def summarize(rows):
        return len(rows)
""")

REPORT = textwrap.dedent("""\
    \"\"\"Report helpers.\"\"\"


    def render_summary(rows):
        return f"{rows} rows"


    def render_failures(failures):
        return len(failures)
""")

PIPELINE_TARGET = textwrap.dedent("""\
    \"\"\"Pipeline helpers.\"\"\"


    def normalize(row):
        return row


    def summarize(rows):
        return len(rows)
""")

REPORT_TARGET = textwrap.dedent("""\
    \"\"\"Report helpers.\"\"\"


    def render_summary(rows):
        return f"{rows} rows"


    def validate_row(row):
        \"\"\"Check required fields.\"\"\"
        missing = []
        for field in ("id", "sku"):
            if not row.get(field):
                missing.append(field)

        if missing:
            return False, missing
        return True, []


    def render_failures(failures):
        return len(failures)
""")


async def main() -> None:
    root = Path(tempfile.mkdtemp())
    (root / "pipeline.py").write_text(PIPELINE)
    (root / "report.py").write_text(REPORT)

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

        # the pre-v0.5 doc idiom: inclusive end address swallows the next def
        out = await call("substitute", command=":/def validate_row/,/^def /d tmp")
        assert "def summarize" in out, "expected the over-grab to be visible"
        out = await call("edit", command="u")
        assert "def summarize" in out  # restored region shows it back

        # the fixed recipe: -1 keeps the next def out of the cut
        out = await call("substitute", command=":/def validate_row/,/^def /-1d fn")
        assert "def summarize" not in out
        assert "cut 12 line(s) (8–19)" in out
        await call("write")

        # cross-file paste ABOVE the destination def: function carries its
        # trailing blanks, existing blanks stay above — spacing right
        await call("open", path="report.py")
        out = await call("edit", command='at /def render_failures/ "fn P')
        assert "pasted 12 line(s)" in out
        await call("write")

    got_pipeline = (root / "pipeline.py").read_text()
    got_report = (root / "report.py").read_text()
    assert got_pipeline == PIPELINE_TARGET, (
        f"pipeline.py mismatch:\n{got_pipeline!r}\nvs\n{PIPELINE_TARGET!r}"
    )
    assert got_report == REPORT_TARGET, (
        f"report.py mismatch:\n{got_report!r}\nvs\n{REPORT_TARGET!r}"
    )
    print("\nE2E OFFSETS PASSED — exact target match on both files")


if __name__ == "__main__":
    asyncio.run(main())
