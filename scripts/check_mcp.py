"""Start the stdio MCP server as a client would and verify its tool list."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server.server"],
        cwd=ROOT,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()

    print(f"MCP server ready: {len(result.tools)} tools")
    for tool in result.tools:
        print(f"- {tool.name}")


if __name__ == "__main__":
    asyncio.run(main())
