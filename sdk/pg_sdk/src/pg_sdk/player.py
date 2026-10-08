"""The replay half of record-and-replay (Milestone 4). Feeds a recorded
tape back to an agent in place of live model calls, tool calls and clock
reads - so a failed run reproduces step for step, without touching a
real model API or real mock services again.

Playback isn't just "serve the next recorded output" - it recomputes
each step's request the same way the recorder did and checks that hash
against what was recorded. A mismatch means the surrounding agent code
isn't actually deterministic given the same model/tool/clock answers
(e.g. non-deterministic ordering, an untracked source of randomness),
which is the real thing a "determinism test suite" needs to catch. The
LLM's own output is expected to vary between live runs; the orchestration
around it is not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pg_sdk.hashing import hash_json
from pg_sdk.storage import BlobStore


class TapeExhausted(Exception):
    """The agent asked for another step but the tape has none left."""


class TapeOrderMismatch(Exception):
    """The agent asked for a different kind/name of step than the tape has
    next - the two runs took different paths, not just different data."""

    def __init__(self, seq: int, expected: tuple[str, str], actual: tuple[str, str]) -> None:
        self.seq = seq
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"tape mismatch at seq {seq}: recorded {expected[0]}/{expected[1]}, "
            f"replay asked for {actual[0]}/{actual[1]}"
        )


@dataclass
class ReplayMismatch(Exception):
    """The request recomputed during replay doesn't hash the same as what
    was recorded for this step - the real determinism violation this
    whole class exists to catch."""

    seq: int
    kind: str
    name: str
    expected_hash: str
    actual_hash: str

    def __str__(self) -> str:
        return (
            f"determinism violation at seq {self.seq} ({self.kind}/{self.name}): "
            f"recorded input hash {self.expected_hash[:12]}... but replay recomputed "
            f"{self.actual_hash[:12]}..."
        )


class Player:
    def __init__(self, store: BlobStore, run_id: str) -> None:
        self.store = store
        self.run_id = run_id
        self.manifest = store.get_manifest(run_id)
        self._steps: list[dict[str, Any]] = self.manifest["steps"]
        self._cursor = 0

    @property
    def finished(self) -> bool:
        return self._cursor >= len(self._steps)

    @property
    def steps_consumed(self) -> int:
        return self._cursor

    @property
    def steps_total(self) -> int:
        return len(self._steps)

    def _next(self, kind: str, name: str, request: Any) -> Any:
        if self.finished:
            raise TapeExhausted(
                f"replay ran out of tape at seq {self._cursor} "
                f"(run {self.run_id!r} recorded {len(self._steps)} steps)"
            )
        step = self._steps[self._cursor]
        if step["kind"] != kind or step["name"] != name:
            raise TapeOrderMismatch(self._cursor, (step["kind"], step["name"]), (kind, name))

        actual_hash, _ = hash_json(request)
        if actual_hash != step["input_hash"]:
            raise ReplayMismatch(
                seq=self._cursor,
                kind=kind,
                name=name,
                expected_hash=step["input_hash"],
                actual_hash=actual_hash,
            )

        output = json.loads(self.store.get_blob(step["output_hash"]))
        self._cursor += 1
        return output

    def replay_model_call(self, model: str, request: dict) -> dict:
        return self._next("model", model, request)

    def replay_tool_call(self, tool_name: str, args: dict) -> dict:
        return self._next("tool", tool_name, args)

    def replay_clock_read(self) -> str:
        return self._next("clock", "clock", {})["value"]

    @property
    def next_step_kind(self) -> str | None:
        """None once the tape is exhausted. Lets a caller driving a
        multi-turn conversation (Milestone 8's simulated_user) ask
        "is there another user turn recorded?" without consuming it -
        the tape itself is the only record of how many turns a replayed
        conversation had, since that was the live persona's own call at
        record time, not a scenario parameter."""
        return None if self.finished else self._steps[self._cursor]["kind"]

    def replay_user_turn(self) -> str:
        """Unlike the other replay_* methods, there's no request to
        recompute and hash-check here - a recorded user turn IS the
        input, not a response to one, so this only enforces step order
        (TapeOrderMismatch), not a ReplayMismatch."""
        if self.finished:
            raise TapeExhausted(
                f"replay ran out of tape at seq {self._cursor} "
                f"(run {self.run_id!r} recorded {len(self._steps)} steps)"
            )
        step = self._steps[self._cursor]
        if step["kind"] != "user" or step["name"] != "user":
            raise TapeOrderMismatch(self._cursor, (step["kind"], step["name"]), ("user", "user"))
        output = json.loads(self.store.get_blob(step["output_hash"]))
        self._cursor += 1
        return output["message"]
