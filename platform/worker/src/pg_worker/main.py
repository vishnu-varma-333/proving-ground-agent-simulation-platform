"""Worker entrypoint.

    uv run --package pg-worker python -m pg_worker          # persistent loop (local dev)
    uv run --package pg-worker python -m pg_worker --once   # process one job and exit (the K8s Job container)

--once is what runs inside a Kubernetes Job pod, one pod per simulation
(the spec's own "each worker pod runs one simulation in isolation") -
KEDA's ScaledJob creates a pod when the queue has work, the pod does
exactly one job, and exits. The persistent loop is for running a worker
locally without needing a Job to be created per attempt.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from dotenv import load_dotenv
from pg_sdk import (
    ClickHouseClient,
    FairDispatcher,
    MetadataStore,
    SimulationJob,
    apply_schema,
    connect_js,
    connect_pool,
)

from pg_worker.runner import process_job

logger = logging.getLogger("pg_worker")


async def main_loop(once: bool, once_timeout: float = 10.0) -> None:
    # No-op in a real K8s pod (env vars are already set via the Job spec,
    # and load_dotenv never overrides an existing var) - needed for local
    # dev, same as the reference-agent CLI already does. Missing this
    # caused a real failure during Milestone 6's own live testing: the
    # worker ran with GEMINI_API_KEY unset even though .env.local had it.
    load_dotenv(".env.local")
    pool = await connect_pool()
    await apply_schema(pool)
    store = MetadataStore(pool)
    nc, js = await connect_js()
    dispatcher = FairDispatcher(js)

    clickhouse = ClickHouseClient()
    await asyncio.to_thread(clickhouse.apply_schema)

    logger.info("worker started (once=%s)", once)
    try:
        elapsed = 0.0
        while True:
            active_runs = await store.list_active_runs()
            await dispatcher.refresh(active_runs)
            msg = await dispatcher.fetch_one(timeout=1.0)

            if msg is None:
                if once:
                    elapsed += 1.0
                    if elapsed >= once_timeout:
                        logger.info("no work within %.0fs, exiting (--once)", once_timeout)
                        return
                    continue
                await asyncio.sleep(0.5)
                continue

            job = SimulationJob.from_json(msg.data)
            await process_job(store, job, msg, clickhouse)
            if once:
                return
    finally:
        await nc.close()
        await pool.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="pg_worker")
    parser.add_argument("--once", action="store_true", help="process one job then exit")
    parser.add_argument("--once-timeout", type=float, default=10.0)
    args = parser.parse_args()
    asyncio.run(main_loop(once=args.once, once_timeout=args.once_timeout))


if __name__ == "__main__":
    main()
