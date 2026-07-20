"""E2E over MCP stdio: the multi-root sandbox (v0.11). No DJINNVIM_ROOT(S)
env — the server takes its roots from the client's roots/list, fetched
lazily on the first tool call: a relative open resolves against the single
granted root → an absolute path outside is rejected → the grant shrinks
(roots/list_changed) and the pending buffer's `write` fails loudly instead
of writing under a revoked root → re-granting both roots makes the same
`write` succeed, and a relative open now fails naming both roots (the
sandbox announcement)."""

import asyncio
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

NOTES = "alpha = 1\n"


async def main() -> None:
    base = Path(tempfile.mkdtemp())
    root_a = base / "roota"
    root_b = base / "rootb"
    outside = base / "outside"
    for d in (root_a, root_b, outside):
        d.mkdir()
    (root_a / "notes.py").write_text(NOTES)
    (outside / "secret.txt").write_text("nope\n")

    granted: list[Path] = [root_a]

    async def list_roots(_context) -> types.ListRootsResult:
        return types.ListRootsResult(
            roots=[types.Root(uri=types.FileUrl(f"file://{p}")) for p in granted]
        )

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "djinnvim.server"],
        env={},  # deliberately no DJINNVIM_ROOT(S): client roots decide
    )
    async with stdio_client(params) as (r, w), ClientSession(
        r, w, list_roots_callback=list_roots
    ) as s:
        await s.initialize()

        async def call(tool, **kw):
            res = await s.call_tool(tool, kw)
            text = res.content[0].text
            print(f"\n>>> {tool} {kw}\n{text}")
            return text

        # lazy fetch on first call; one granted root → relative path resolves
        out = await call("open", path="notes.py")
        assert "1 lines" in out and str(root_a) in out

        # containment against the client-granted root
        out = await call("open", path=str(outside / "secret.txt"))
        assert "outside the sandbox root" in out and str(root_a) in out

        # dirty the buffer, then revoke its root
        out = await call("edit", command="at /1/ ciw 2")
        assert "changed line 1" in out
        granted[:] = [root_b]
        await s.send_roots_list_changed()
        await asyncio.sleep(0.2)  # let the notification land before the call

        out = await call("write")
        assert "no longer inside the sandbox root" in out
        assert (root_a / "notes.py").read_text() == NOTES  # untouched on disk

        # re-grant: same write now lands
        granted[:] = [root_a, root_b]
        await s.send_roots_list_changed()
        await asyncio.sleep(0.2)
        out = await call("write")
        assert "wrote" in out and "1 line(s) changed" in out
        assert (root_a / "notes.py").read_text() == "alpha = 2\n"

        # multiple roots: a relative open is loud and names both (announcement)
        out = await call("open", path="notes.py")
        assert "use an absolute path" in out
        assert str(root_a) in out and str(root_b) in out

        # both peers reachable by absolute path
        (root_b / "other.py").write_text("beta = 3\n")
        out = await call("open", path=str(root_b / "other.py"))
        assert "1 lines" in out

    print("\ne2e_roots: all assertions passed")


if __name__ == "__main__":
    asyncio.run(main())
