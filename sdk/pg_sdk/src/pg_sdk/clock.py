"""Clock reads are the third source of non-determinism the SDK
intercepts (alongside model and tool calls).

Two clock sources, same interface (`now() -> str`, ISO 8601 UTC):

- `RealClock`: real wall time. What Milestones 3-4 used directly.
- `SimulatedClock`: virtual time that only moves when something calls
  `advance()` - nothing sleeps against the real clock at all, so a
  72-hour wait resolves in however long `advance()` itself takes to run
  (microseconds), not 72 hours. This is the mechanism behind "multi-day
  scenarios run in seconds" (Milestone 1's own pitch).

Design decision (see DECISIONS.md): clock injection through the SDK, not
OS-level time faking (no monkeypatching `time.time`, no libfaketime). An
agent that wants virtual time asks *this* clock for the time and awaits
*this* clock's sleep - code that reads the real OS clock directly is, by
construction, outside what the platform can simulate for it.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pg_sdk.recorder import Recorder


class Clock(Protocol):
    def now(self) -> str: ...


class RealClock:
    def now(self) -> str:
        return datetime.now(UTC).isoformat()


class SimulatedClock:
    """Virtual time. Starts at `start` (default: real now, captured once,
    never read again) and only moves when `advance()` is called.

    Timer ordering: pending `sleep()` calls are kept in a min-heap keyed
    by (wake_time, insertion_sequence). `advance()` releases every waiter
    whose wake_time has been reached, strictly in that order - two
    waiters with the same wake_time resolve in the order they called
    `sleep()`, not arbitrarily (Python's `heapq` would otherwise compare
    the asyncio.Event objects directly on a tie, which doesn't even
    support ordering - the sequence counter is what makes the heap work
    at all, not just what makes the order predictable).
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)
        self._pending: list[tuple[datetime, int, asyncio.Event]] = []
        self._seq = itertools.count()

    def now(self) -> str:
        return self._now.isoformat()

    async def sleep(self, seconds: float) -> None:
        wake_at = self._now + timedelta(seconds=seconds)
        event = asyncio.Event()
        heapq.heappush(self._pending, (wake_at, next(self._seq), event))
        await event.wait()

    def advance(self, seconds: float) -> int:
        """Moves virtual time forward and releases every waiter whose
        deadline has now been reached, in wake-time order. Returns how
        many waiters were released."""
        self._now += timedelta(seconds=seconds)
        released = 0
        while self._pending and self._pending[0][0] <= self._now:
            _, _, event = heapq.heappop(self._pending)
            event.set()
            released += 1
        return released

    @property
    def pending_count(self) -> int:
        return len(self._pending)


class RecordingClock:
    def __init__(self, recorder: Recorder, clock: Clock | None = None) -> None:
        self._recorder = recorder
        self._clock = clock or RealClock()

    def now(self) -> str:
        value = self._clock.now()
        self._recorder.record_clock_read(value)
        return value
