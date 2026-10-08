"""Real measurement for docs/BENCHMARKS.md: how long a 72-hour simulated
wait actually takes in wall-clock time against pg_sdk.SimulatedClock, as
opposed to the 72 real hours it would take against a real clock. This is
the spec's own "Virtual-time speedup" metric (Milestone 1's benchmarks
table), measured directly rather than estimated.

    uv run python scripts/benchmark_virtual_time.py
"""

from __future__ import annotations

import asyncio
import time

from pg_sdk import SimulatedClock


async def run_scenario(clock: SimulatedClock, hours: int) -> None:
    """Models a scenario that waits `hours` hours for something to
    happen (e.g. "check back on this order in 3 days") - the thing a
    real agent would do with asyncio.sleep() against a real clock."""
    await clock.sleep(hours * 3600)


async def main() -> None:
    hours = 72
    clock = SimulatedClock()

    wall_start = time.perf_counter()
    task = asyncio.create_task(run_scenario(clock, hours))
    await asyncio.sleep(0)  # let the scenario register its wait
    clock.advance(hours * 3600)  # the simulation jumps straight to it
    await task
    wall_elapsed = time.perf_counter() - wall_start

    print(f"Simulated wait: {hours} hours ({hours * 3600}s virtual)")
    print(f"Real wall-clock time elapsed: {wall_elapsed * 1000:.3f}ms")
    print(f"Speedup vs. a real {hours}h wait: {(hours * 3600) / wall_elapsed:,.0f}x")


if __name__ == "__main__":
    asyncio.run(main())
