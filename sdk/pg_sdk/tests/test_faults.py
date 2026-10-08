import time
from typing import ClassVar

import pytest
from pg_sdk.faults import FaultInjectedTimeout, FaultInjectingToolbox, FaultSpec


class _FakeInner:
    function_declarations: ClassVar = ["fake-decl"]

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool_name: str, args: dict) -> dict:
        self.calls.append((tool_name, args))
        return {"status": "ok", "amount_cents": 2499, "order_id": args.get("order_id")}


async def test_no_fault_configured_passes_through_untouched():
    inner = _FakeInner()
    toolbox = FaultInjectingToolbox(inner=inner, faults=[])

    result = await toolbox.call("get_order", {"order_id": "ord_1"})

    assert result["status"] == "ok"
    assert inner.calls == [("get_order", {"order_id": "ord_1"})]


async def test_error_fault_never_calls_the_real_tool():
    inner = _FakeInner()
    toolbox = FaultInjectingToolbox(
        inner=inner,
        faults=[FaultSpec(tool="issue_refund", kind="error", message="payments service down")],
    )

    result = await toolbox.call("issue_refund", {"order_id": "ord_1"})

    assert result == {"error": "payments service down"}
    assert inner.calls == [], "an error fault must short-circuit before the real tool runs"


async def test_latency_fault_delays_then_calls_the_real_tool():
    inner = _FakeInner()
    toolbox = FaultInjectingToolbox(
        inner=inner, faults=[FaultSpec(tool="get_order", kind="latency", latency_ms=50)]
    )

    start = time.monotonic()
    result = await toolbox.call("get_order", {"order_id": "ord_1"})
    elapsed = time.monotonic() - start

    assert result["status"] == "ok"
    assert elapsed >= 0.05, "the injected latency must actually elapse"
    assert inner.calls == [("get_order", {"order_id": "ord_1"})]


async def test_timeout_fault_raises_without_calling_the_real_tool():
    inner = _FakeInner()
    toolbox = FaultInjectingToolbox(
        inner=inner, faults=[FaultSpec(tool="send_email", kind="timeout", latency_ms=10)]
    )

    with pytest.raises(FaultInjectedTimeout):
        await toolbox.call("send_email", {"to": "x@example.com"})

    assert inner.calls == []


async def test_partial_fault_drops_configured_keys_from_a_real_response():
    inner = _FakeInner()
    toolbox = FaultInjectingToolbox(
        inner=inner,
        faults=[FaultSpec(tool="get_order", kind="partial", drop_keys=("amount_cents",))],
    )

    result = await toolbox.call("get_order", {"order_id": "ord_1"})

    assert "amount_cents" not in result
    assert result["status"] == "ok"
    assert inner.calls == [("get_order", {"order_id": "ord_1"})], "partial still calls the real tool"


async def test_fault_only_applies_to_its_own_tool_name():
    inner = _FakeInner()
    toolbox = FaultInjectingToolbox(
        inner=inner, faults=[FaultSpec(tool="issue_refund", kind="error", message="down")]
    )

    result = await toolbox.call("get_order", {"order_id": "ord_1"})

    assert result["status"] == "ok", "a fault on a different tool must not affect this one"


def test_fault_spec_from_dict_round_trips_with_defaults():
    spec = FaultSpec.from_dict({"tool": "get_order", "kind": "latency", "latency_ms": 500})
    assert spec == FaultSpec(tool="get_order", kind="latency", latency_ms=500)


def test_fault_spec_from_dict_parses_drop_keys():
    spec = FaultSpec.from_dict(
        {"tool": "get_order", "kind": "partial", "drop_keys": ["amount_cents", "status"]}
    )
    assert spec.drop_keys == ("amount_cents", "status")
