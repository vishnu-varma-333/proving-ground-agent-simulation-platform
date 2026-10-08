"""Clock reads are the third source of non-determinism the SDK intercepts
(alongside model and tool calls). This is real-time only - Milestone 5
replaces it with a simulated clock that can jump forward instantly; for
now the job is just to record every reading so a later replay sees the
exact same timestamps the original run saw."""

from __future__ import annotations

from datetime import UTC, datetime

from pg_sdk.recorder import Recorder


class RecordingClock:
    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder

    def now(self) -> str:
        value = datetime.now(UTC).isoformat()
        self._recorder.record_clock_read(value)
        return value
