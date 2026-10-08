import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pg_sdk.clock import RealClock, RecordingClock, SimulatedClock
from pg_sdk.recorder import Recorder


def test_real_clock_now_is_a_real_iso_timestamp():
    before = datetime.now(UTC)
    value = RealClock().now()
    parsed = datetime.fromisoformat(value)
    after = datetime.now(UTC)
    assert before <= parsed <= after


def test_simulated_clock_does_not_move_on_its_own():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = SimulatedClock(start=start)
    assert clock.now() == start.isoformat()
    assert clock.now() == start.isoformat(), "time must not advance just from reading it"


def test_simulated_clock_advance_moves_now():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = SimulatedClock(start=start)
    clock.advance(3600)
    assert clock.now() == (start + timedelta(hours=1)).isoformat()


@pytest.mark.asyncio
async def test_sleep_resolves_only_after_advance_past_its_deadline():
    clock = SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC))
    done = False

    async def waiter():
        nonlocal done
        await clock.sleep(3600)
        done = True

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0)  # let the waiter register its sleep
    assert not done
    assert clock.pending_count == 1

    clock.advance(1800)  # halfway there - must not release yet
    await asyncio.sleep(0)
    assert not done

    clock.advance(1800)  # now past the 3600s deadline
    await asyncio.sleep(0)
    assert done
    await task


@pytest.mark.asyncio
async def test_a_72_hour_wait_resolves_in_real_milliseconds_not_72_hours():
    """The actual claim this milestone exists to prove: a multi-day wait
    against the simulated clock costs real wall-clock time proportional
    to how fast advance() runs, not to the simulated duration."""
    import time

    clock = SimulatedClock()
    wall_start = time.monotonic()

    async def wait_three_days():
        await clock.sleep(72 * 3600)

    task = asyncio.create_task(wait_three_days())
    await asyncio.sleep(0)
    clock.advance(72 * 3600)
    await task

    wall_elapsed = time.monotonic() - wall_start
    assert wall_elapsed < 1.0, f"a 72h simulated wait took {wall_elapsed}s of real time"


@pytest.mark.asyncio
async def test_timers_released_in_wake_time_order_not_registration_order():
    """Timer ordering (the design decision this milestone calls out
    explicitly): register a LATER-waking timer first, an EARLIER-waking
    one second, then advance past both at once - they must fire in
    deadline order, not the order sleep() was called."""
    clock = SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC))
    release_order: list[str] = []

    async def waiter(name: str, delay: float):
        await clock.sleep(delay)
        release_order.append(name)

    task_late = asyncio.create_task(waiter("wakes-later", 7200))
    await asyncio.sleep(0)
    task_early = asyncio.create_task(waiter("wakes-earlier", 3600))
    await asyncio.sleep(0)

    clock.advance(7200)  # past both deadlines in one jump
    await asyncio.gather(task_late, task_early)

    assert release_order == ["wakes-earlier", "wakes-later"]


@pytest.mark.asyncio
async def test_same_deadline_releases_in_registration_order():
    clock = SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC))
    release_order: list[str] = []

    async def waiter(name: str):
        await clock.sleep(60)
        release_order.append(name)

    task_a = asyncio.create_task(waiter("first-registered"))
    await asyncio.sleep(0)
    task_b = asyncio.create_task(waiter("second-registered"))
    await asyncio.sleep(0)

    clock.advance(60)
    await asyncio.gather(task_a, task_b)

    assert release_order == ["first-registered", "second-registered"]


class FakeBlobStore:
    def put_blob(self, data: bytes) -> str:
        return "irrelevant-for-this-test"

    def put_step(self, run_id: str, seq: int, step: dict) -> None:
        pass

    def put_manifest(self, run_id: str, manifest: dict) -> None:
        pass


def test_recording_clock_records_whatever_its_underlying_clock_says():
    store = FakeBlobStore()
    recorder = Recorder(store=store, run_id="run-1", agent_name="test")
    sim = SimulatedClock(start=datetime(2026, 6, 1, tzinfo=UTC))
    sim.advance(86400)  # one simulated day forward
    recording_clock = RecordingClock(recorder, clock=sim)

    value = recording_clock.now()

    assert value == datetime(2026, 6, 2, tzinfo=UTC).isoformat()
    assert recorder._steps[0].kind == "clock"
