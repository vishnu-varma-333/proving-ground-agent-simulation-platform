"""The recording half of record-and-replay (Milestone 3). Every
non-deterministic input an agent depends on - what the model said, what a
tool returned, what time it was - gets a sequence number and a
content-addressed reference, in order, so Milestone 4's replay can feed
the exact same tape back.

Deliberately NOT provider-specific: a model/tool request and response are
plain JSON-compatible dicts here. Converting a provider's own objects
(google-genai's types.Content, an MCP CallToolResult, ...) to and from
those dicts is the integration's job (see agents/reference_agent), not
the SDK's - this is the part any agent "plugs into" without the SDK
needing to know what model or tools that agent uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pg_sdk.hashing import hash_json
from pg_sdk.storage import BlobStore

StepKind = Literal["model", "tool", "clock", "user"]


@dataclass(frozen=True)
class StepRecord:
    seq: int
    kind: StepKind
    name: str  # model name, tool name, or "clock" for a clock read
    input_hash: str
    output_hash: str
    recorded_at: str


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Recorder:
    store: BlobStore
    run_id: str
    agent_name: str
    _seq: int = field(default=0, init=False)
    _steps: list[StepRecord] = field(default_factory=list, init=False)
    _started_at: str = field(default_factory=_utcnow_iso, init=False)

    def _record(self, kind: StepKind, name: str, request: Any, response: Any) -> StepRecord:
        seq = self._seq
        self._seq += 1

        input_hash, input_bytes = hash_json(request)
        output_hash, output_bytes = hash_json(response)
        self.store.put_blob(input_bytes)
        self.store.put_blob(output_bytes)

        step = StepRecord(
            seq=seq,
            kind=kind,
            name=name,
            input_hash=input_hash,
            output_hash=output_hash,
            recorded_at=_utcnow_iso(),
        )
        self.store.put_step(self.run_id, seq, step.__dict__)
        self._steps.append(step)
        return step

    def record_model_call(self, model: str, request: dict, response: dict) -> StepRecord:
        return self._record("model", model, request, response)

    def record_tool_call(self, tool_name: str, args: dict, result: dict) -> StepRecord:
        return self._record("tool", tool_name, args, result)

    def record_clock_read(self, value: str) -> StepRecord:
        return self._record("clock", "clock", {}, {"value": value})

    def record_user_turn(self, message: str) -> StepRecord:
        """A simulated_user-generated message (Milestone 8) is itself a
        non-deterministic input the agent's own request hash depends on -
        unlike a scenario's fixed user_message (already versioned in
        Postgres, not generated at record time), it only exists here on
        this tape, so replay needs it recorded too (the spec's own Step
        data model already names "user" as one of its four kinds - this
        was a gap until Milestone 10's replay work noticed Recorder's
        StepKind only had three)."""
        return self._record("user", "user", {}, {"message": message})

    def finalize(self) -> dict:
        manifest = {
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "started_at": self._started_at,
            "finished_at": _utcnow_iso(),
            "step_count": len(self._steps),
            "steps": [s.__dict__ for s in self._steps],
        }
        self.store.put_manifest(self.run_id, manifest)
        return manifest
