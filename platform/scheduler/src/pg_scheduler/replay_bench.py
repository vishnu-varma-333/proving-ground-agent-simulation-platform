"""Replay-bench worker (Milestone 10's scale test, see
scripts/scale_test.py and docs/BENCHMARKS.md): pulls sim_ids off a
dedicated NATS stream and replays each one from its tape - no live
model API calls at all.

Deliberately separate from pg_worker.runner.process_job rather than a
"replay mode" bolted onto it: the spec's own throughput metric
("simulations per minute at 1, 4, 16 and 64 workers... report the
scaling curve") is about this platform's own scheduling/orchestration
ceiling, not Gemini's free-tier rate limit - at even 4 concurrent
workers making real model calls, Gemini's own throttling would
dominate the number measured, not anything about this platform's
scaling (observed directly, Milestones 8-10: a single worker's calls
already drew real 429s). Replaying an already-recorded tape is real
work for the queue/worker/Kubernetes path to do - claim a message,
spin up a pod, run the agent against a tape, ack - with none of that
external bottleneck, which is exactly what this benchmark needs to
isolate.
"""

from __future__ import annotations

import asyncio
import json
import logging

from pg_sdk import BlobStore, MetadataStore, connect_js, connect_pool

from pg_scheduler.replay import replay_simulation

logger = logging.getLogger("pg_scheduler.replay_bench")

STREAM_NAME = "SCALE_TEST"
SUBJECT = "scale_test.replay"
CONSUMER_NAME = "scale-test-workers"


async def main_loop() -> None:
    pool = await connect_pool()
    store = MetadataStore(pool)
    blob_store = BlobStore()  # one S3 client reused across every replay - see
    # replay_simulation's own docstring for why this isn't just tidiness.
    nc, js = await connect_js()
    sub = await js.pull_subscribe(SUBJECT, durable=CONSUMER_NAME, stream=STREAM_NAME)

    logger.info("replay-bench worker started")
    try:
        while True:
            try:
                msgs = await sub.fetch(1, timeout=5)
            except TimeoutError:
                continue
            for msg in msgs:
                payload = json.loads(msg.data)
                sim_id = payload["sim_id"]
                try:
                    await replay_simulation(store, sim_id, verbose=False, blob_store=blob_store)
                    await msg.ack()
                except Exception:
                    logger.exception("replay failed for sim_id=%s", sim_id)
                    await msg.nak()
    finally:
        await nc.close()
        await pool.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()
