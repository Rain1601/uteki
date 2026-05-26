"""Entry point: ``python -m uteki_api.mcp``.

Runs the MCP server over stdio (the JSON-RPC transport ``claude mcp add``
uses by default). Logs go to stderr — stdout is reserved for the
JSON-RPC stream and any non-protocol bytes there will break the client.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

from mcp.server.stdio import stdio_server

from uteki_api.mcp.server import build_server


async def _run() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        # ``initialization_options`` is required by the spec; an empty
        # dict-like is fine for servers that don't need to negotiate.
        await server.run(
            read,
            write,
            server.create_initialization_options(),
        )


def main() -> None:
    # stdout MUST stay clean (JSON-RPC frames); send everything to stderr.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    # Client disconnect or Ctrl-C is the normal shutdown path; both
    # surface as KeyboardInterrupt / EOFError out of asyncio.run.
    with contextlib.suppress(KeyboardInterrupt, EOFError):
        asyncio.run(_run())


if __name__ == "__main__":
    main()
