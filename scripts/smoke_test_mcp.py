"""Live smoke test: spawn each mock service as a real subprocess over the
real MCP stdio transport (not just calling the Python functions directly)
and exercise one real tool call against each. Run with:

    uv run --all-packages python scripts/smoke_test_mcp.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def check_service(name: str, module: str, db_env: str, db_path: Path, call) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        env={db_env: str(db_path)},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        tool_names = sorted(t.name for t in tools.tools)
        print(f"[{name}] tools: {tool_names}")
        result = await call(session)
        print(f"[{name}] sample call result: {result.content[0].text[:200]}")


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        await check_service(
            "orders",
            "orders_service",
            "ORDERS_DB_PATH",
            tmp_path / "orders.db",
            lambda s: s.call_tool("get_order", {"order_id": "ord_1001"}),
        )
        await check_service(
            "payments",
            "payments_service",
            "PAYMENTS_DB_PATH",
            tmp_path / "payments.db",
            lambda s: s.call_tool("get_payment", {"order_id": "ord_1001"}),
        )
        await check_service(
            "email",
            "email_service",
            "EMAIL_DB_PATH",
            tmp_path / "email.db",
            lambda s: s.call_tool(
                "send_email",
                {"to_address": "test@example.com", "subject": "hi", "body": "it works"},
            ),
        )
    print("\nAll three MCP servers started, listed tools, and answered a real call.")


if __name__ == "__main__":
    asyncio.run(main())
