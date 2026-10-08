"""Connects the reference agent to the three mock services as real MCP
servers (subprocesses over stdio), and adapts their tools into Gemini
function declarations.

This is deliberately direct - the agent talks to MCP servers itself. The
platform's SDK (Milestone 3) will sit between an agent and these same
calls to record and replay them; nothing here assumes that yet.
"""

from __future__ import annotations

import json
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from google.genai import types
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    module: str
    db_env_var: str
    db_filename: str


SERVICES = [
    ServiceSpec("orders", "orders_service", "ORDERS_DB_PATH", "orders.db"),
    ServiceSpec("payments", "payments_service", "PAYMENTS_DB_PATH", "payments.db"),
    ServiceSpec("email", "email_service", "EMAIL_DB_PATH", "email.db"),
]


class MockServiceToolbox:
    """Owns the live MCP sessions for every mock service and dispatches
    tool calls to whichever session actually owns that tool name."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._tool_owner: dict[str, str] = {}
        self.function_declarations: list[types.FunctionDeclaration] = []

    async def __aenter__(self) -> Self:
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.__aexit__(*exc_info)

    async def connect(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        for spec in SERVICES:
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", spec.module],
                env={spec.db_env_var: str(data_dir / spec.db_filename)},
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[spec.name] = session

            tools = await session.list_tools()
            for tool in tools.tools:
                if tool.name in self._tool_owner:
                    raise RuntimeError(
                        f"tool name collision: {tool.name!r} exposed by both "
                        f"{self._tool_owner[tool.name]!r} and {spec.name!r}"
                    )
                self._tool_owner[tool.name] = spec.name
                self.function_declarations.append(
                    types.FunctionDeclaration(
                        name=tool.name,
                        description=tool.description or "",
                        parameters_json_schema=tool.input_schema,
                    )
                )

    async def call(self, tool_name: str, args: dict) -> dict:
        owner = self._tool_owner.get(tool_name)
        if owner is None:
            return {"error": f"no mock service exposes a tool named {tool_name!r}"}
        session = self._sessions[owner]
        result = await session.call_tool(tool_name, args)
        text = result.content[0].text if result.content else "{}"
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
