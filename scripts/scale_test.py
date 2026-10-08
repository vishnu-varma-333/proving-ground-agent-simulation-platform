"""Real measurement for docs/BENCHMARKS.md: the spec's own "Throughput"
metric - simulations per minute at 1, 4, 16 and 64 workers, reporting
the scaling curve and where it flattens.

Measures the platform's own queue/worker/Kubernetes throughput ceiling
by replaying an already-recorded tape repeatedly through the real
pipeline (real NATS JetStream, real Kubernetes pods, real
claim/ack/redeliver semantics) rather than running live scenarios -
see pg_scheduler.replay_bench's own docstring for why: live Gemini
calls hit free-tier rate limits well before this platform's own
scaling does, which would measure Gemini's throttling, not this
platform's.

Requires infra/k8s/local/platform/replay-bench-worker.yaml already
applied (0 replicas) and a real sim-id with a recorded tape to replay
(any fixed-message simulation already run through `pg run` works).

    uv run python scripts/scale_test.py --sim-id sim_630bbb390c7f0b72 --workers 1,4,16,64 --count 40
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time

from nats.js.api import AckPolicy, ConsumerConfig, StreamConfig
from nats.js.errors import APIError
from pg_sdk.queue import connect_js

NAMESPACE = "proving-ground"
DEPLOYMENT = "replay-bench-worker"
STREAM_NAME = "SCALE_TEST"
SUBJECT = "scale_test.replay"
CONSUMER_NAME = "scale-test-workers"


def kubectl(*args: str) -> None:
    subprocess.run(["kubectl", "-n", NAMESPACE, *args], check=True, capture_output=True)


def scale_workers(count: int) -> None:
    kubectl("scale", f"deployment/{DEPLOYMENT}", f"--replicas={count}")
    if count > 0:
        kubectl("wait", f"deployment/{DEPLOYMENT}", "--for=condition=available", "--timeout=120s")
    else:
        # scaling to 0 has nothing to "become available" - just give the
        # pods a moment to actually terminate before the next round starts.
        time.sleep(3)


async def reset_stream(js) -> None:
    for attempt in (
        lambda: js.delete_consumer(STREAM_NAME, CONSUMER_NAME),
        lambda: js.delete_stream(STREAM_NAME),
    ):
        try:
            await attempt()
        except APIError:
            pass
    await js.add_stream(StreamConfig(name=STREAM_NAME, subjects=[SUBJECT]))
    await js.add_consumer(
        STREAM_NAME,
        ConsumerConfig(
            durable_name=CONSUMER_NAME,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=30,
            max_deliver=3,
        ),
    )


async def run_round(js, sim_id: str, count: int, worker_count: int) -> float:
    await reset_stream(js)
    scale_workers(worker_count)

    start = time.perf_counter()
    for _ in range(count):
        await js.publish(SUBJECT, json.dumps({"sim_id": sim_id}).encode())

    while True:
        info = await js.consumer_info(STREAM_NAME, CONSUMER_NAME)
        if info.num_pending == 0 and info.num_ack_pending == 0:
            break
        await asyncio.sleep(0.25)
    elapsed = time.perf_counter() - start

    scale_workers(0)
    return elapsed


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sim-id", required=True, help="an already-recorded sim-id to replay repeatedly")
    parser.add_argument("--workers", default="1,4,16,64", help="comma-separated worker counts to test")
    parser.add_argument("--count", type=int, default=40, help="replay operations per round")
    args = parser.parse_args()

    worker_counts = [int(w) for w in args.workers.split(",")]
    nc, js = await connect_js()
    results: list[tuple[int, float]] = []
    try:
        for worker_count in worker_counts:
            print(f"--- {worker_count} worker(s), {args.count} replays ---")
            elapsed = await run_round(js, args.sim_id, args.count, worker_count)
            per_minute = args.count / (elapsed / 60)
            results.append((worker_count, per_minute))
            print(f"{args.count} replays in {elapsed:.1f}s -> {per_minute:.1f} simulations/minute")
    finally:
        await nc.close()

    print("\n=== Scaling curve ===")
    for worker_count, per_minute in results:
        print(f"{worker_count:>3} workers: {per_minute:7.1f} simulations/minute")


if __name__ == "__main__":
    asyncio.run(main())
