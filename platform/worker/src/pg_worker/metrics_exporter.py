"""Exposes queue-depth metrics for Prometheus to scrape, which is what
KEDA's ScaledJob actually watches to decide worker replica count
(decision 22, DECISIONS.md): KEDA's native nats-jetstream scaler needs
one statically-named consumer per trigger, but pg_sdk.FairDispatcher
creates one durable consumer per *run*, dynamically, as runs come and
go - there is no single consumer name KEDA could point at that reflects
total backlog across every active run. Postgres (not NATS) is this
project's actual source of truth for "how much work is pending" anyway,
so that's what gets exported.

This also directly satisfies a named requirement from the spec's own
production-readiness section: "Metrics: queue depth, ...".

    uv run --package pg-worker python -m pg_worker.metrics_exporter
"""

from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv
from pg_sdk import apply_schema, connect_pool
from prometheus_client import Gauge, start_http_server

logger = logging.getLogger("pg_worker.metrics_exporter")

PENDING_GAUGE = Gauge("pg_pending_simulations", "Simulations currently in state=pending")
RUNNING_GAUGE = Gauge("pg_running_simulations", "Simulations currently in state=running")
POLL_INTERVAL_SECONDS = 5.0
METRICS_PORT = 9108


async def poll_loop(pool) -> None:
    while True:
        async with pool.acquire() as conn:
            pending = await conn.fetchval("SELECT COUNT(*) FROM simulations WHERE state = 'pending'")
            running = await conn.fetchval("SELECT COUNT(*) FROM simulations WHERE state = 'running'")
        PENDING_GAUGE.set(pending)
        RUNNING_GAUGE.set(running)
        logger.info("pending=%d running=%d", pending, running)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    load_dotenv(".env.local")
    pool = await connect_pool()
    await apply_schema(pool)
    start_http_server(METRICS_PORT)
    logger.info("metrics exporter listening on :%d", METRICS_PORT)
    await poll_loop(pool)


if __name__ == "__main__":
    asyncio.run(main())
