"""Fault injection (Milestone 7): a layer between the agent and its mock
tools that adds latency, errors, timeouts or partial responses per the
scenario's own spec.

Implemented as a wrapping layer around any object with an async
`call(tool_name, args) -> dict` method, not a separate OS process - the
mock services talk to the agent over stdio subprocesses, not network
sockets, so there's no socket to put a traditional proxy in front of.
Wrapping the same call boundary the SDK's own Recorder/Player already
use achieves the same effect (every tool call passes through here
first) without inventing a second transport just to interpose on it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

FaultKind = Literal["latency", "error", "timeout", "partial"]


class FaultInjectedTimeout(Exception):
    """Raised instead of returning a result, for a 'timeout' fault."""


@dataclass(frozen=True)
class FaultSpec:
    tool: str
    kind: FaultKind
    latency_ms: int = 0
    message: str = "injected fault"
    drop_keys: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FaultSpec:
        return cls(
            tool=data["tool"],
            kind=data["kind"],
            latency_ms=data.get("latency_ms", 0),
            message=data.get("message", "injected fault"),
            drop_keys=tuple(data.get("drop_keys", [])),
        )


class ToolCaller(Protocol):
    async def call(self, tool_name: str, args: dict) -> dict: ...


@dataclass
class FaultInjectingToolbox:
    """Wraps a real toolbox (anything with `.call()` and
    `.function_declarations`) and applies at most one configured fault
    per tool name - a scenario that wants two different failure modes on
    the same tool across a conversation isn't a case this milestone
    needs to cover."""

    inner: ToolCaller
    faults: list[FaultSpec] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._by_tool = {f.tool: f for f in self.faults}

    @property
    def function_declarations(self):
        return self.inner.function_declarations

    async def call(self, tool_name: str, args: dict) -> dict:
        fault = self._by_tool.get(tool_name)
        if fault is None:
            return await self.inner.call(tool_name, args)

        if fault.kind == "latency":
            await asyncio.sleep(fault.latency_ms / 1000)
            return await self.inner.call(tool_name, args)

        if fault.kind == "error":
            return {"error": fault.message}

        if fault.kind == "timeout":
            await asyncio.sleep(fault.latency_ms / 1000)
            raise FaultInjectedTimeout(f"{tool_name} timed out (injected fault)")

        if fault.kind == "partial":
            result = await self.inner.call(tool_name, args)
            return {k: v for k, v in result.items() if k not in fault.drop_keys}

        raise ValueError(f"unknown fault kind {fault.kind!r}")
