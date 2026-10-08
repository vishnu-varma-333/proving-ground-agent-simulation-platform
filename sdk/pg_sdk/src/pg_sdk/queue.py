"""The simulation job queue: NATS JetStream, chosen over Kafka or a
PostgreSQL-backed queue for exactly the reasons DECISIONS.md gives -
lightweight, durable, built-in acknowledgements and redelivery.

A worker "lease" on a job isn't anything hand-rolled: it's JetStream's
own ack_wait. A worker that pulls a message holds it until it explicitly
acks (success) or nacks (explicit failure, redeliver sooner) or simply
never acks (crashed - JetStream redelivers once ack_wait elapses, up to
max_deliver). This is also how a kill test proves "0 lost or
double-counted simulations": kill the worker before it acks, and
JetStream's own redelivery - not application code - hands the job to
someone else.

Fair scheduling (one large suite must not starve another, DECISIONS.md)
needs more than a single FIFO subject: JetStream pull consumers deliver
strictly in stream order, so if one run publishes 1000 jobs before a
second run's 3 jobs are even submitted, no amount of consumer-side
batching recovers fairness - the 3 jobs are simply behind the 1000 in
the stream. The fix is one subject *per run* (`simulations.jobs.<run_id>`)
under one wildcard stream, and a dispatcher that holds one filtered pull
consumer per currently-active run, cycling across them in a weighted
round robin (priority = how many turns a run gets per cycle). This moves
fairness to the consumer side, where it doesn't depend on submission
timing or on multiple scheduler processes coordinating with each other.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import nats
from nats.aio.msg import Msg
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, StreamConfig
from nats.js.client import JetStreamContext
from nats.js.errors import APIError

logger = logging.getLogger(__name__)

STREAM_NAME = "SIMULATIONS"
SUBJECT_PREFIX = "simulations.jobs"
SUBJECT_WILDCARD = f"{SUBJECT_PREFIX}.*"


def _nats_url() -> str:
    return os.environ.get("PG_NATS_URL", "nats://127.0.0.1:24222")


def subject_for_run(run_id: str) -> str:
    return f"{SUBJECT_PREFIX}.{run_id}"


def consumer_name_for_run(run_id: str) -> str:
    return f"worker-{run_id}"


async def connect_js() -> tuple[Any, JetStreamContext]:
    nc = await nats.connect(_nats_url())
    js = nc.jetstream()
    return nc, js


async def ensure_stream(js: JetStreamContext) -> None:
    try:
        await js.add_stream(StreamConfig(name=STREAM_NAME, subjects=[SUBJECT_WILDCARD]))
    except APIError as exc:
        logger.debug("add_stream(%s): %s (likely already exists - idempotent setup)", STREAM_NAME, exc)


async def ensure_run_consumer(
    js: JetStreamContext, run_id: str, ack_wait_seconds: float = 15.0, max_deliver: int = 5
) -> None:
    try:
        await js.add_consumer(
            STREAM_NAME,
            ConsumerConfig(
                durable_name=consumer_name_for_run(run_id),
                filter_subject=subject_for_run(run_id),
                ack_policy=AckPolicy.EXPLICIT,
                ack_wait=ack_wait_seconds,
                max_deliver=max_deliver,
                deliver_policy=DeliverPolicy.ALL,
            ),
        )
    except APIError as exc:
        logger.debug("add_consumer(%s): %s (likely already exists)", run_id, exc)


async def delete_run_consumer(js: JetStreamContext, run_id: str) -> None:
    """Called once a run has finished - a durable consumer left behind
    for every run ever submitted is a real (if minor) resource leak
    otherwise; see DECISIONS.md."""
    try:
        await js.delete_consumer(STREAM_NAME, consumer_name_for_run(run_id))
    except APIError as exc:
        logger.debug("delete_consumer(%s): %s (likely already gone)", run_id, exc)


@dataclass(frozen=True)
class SimulationJob:
    sim_id: str
    run_id: str
    scenario_id: str
    seed: int
    agent_version_id: str

    def to_json(self) -> bytes:
        return json.dumps(self.__dict__).encode("utf-8")

    @classmethod
    def from_json(cls, data: bytes) -> SimulationJob:
        return cls(**json.loads(data))


async def publish_job(js: JetStreamContext, job: SimulationJob) -> None:
    await js.publish(subject_for_run(job.run_id), job.to_json())


def build_weighted_cycle(active_runs: list[tuple[str, int]]) -> list[str]:
    """A run with priority N gets N consecutive turns per full cycle.
    Pulled out as its own pure function so the weighting logic is
    testable without a live NATS connection."""
    cycle: list[str] = []
    for run_id, priority in active_runs:
        cycle.extend([run_id] * max(1, priority))
    return cycle


class FairDispatcher:
    """One filtered pull consumer per active run, cycled in a
    priority-weighted round robin: a run with priority N gets N
    consecutive turns per full cycle before moving to the next run.
    Active runs (and their priority) are discovered from Postgres, not
    tracked separately - the scheduler's own `runs` table is the single
    source of truth for what's currently in flight."""

    def __init__(self, js: JetStreamContext) -> None:
        self.js = js
        self._subs: dict[str, JetStreamContext.PullSubscription] = {}
        self._cycle: list[str] = []
        self._cycle_pos = 0

    async def refresh(self, active_runs: list[tuple[str, int]]) -> None:
        active_ids = {run_id for run_id, _ in active_runs}

        for run_id in active_ids - self._subs.keys():
            await ensure_run_consumer(self.js, run_id)
            self._subs[run_id] = await self.js.pull_subscribe(
                subject_for_run(run_id),
                durable=consumer_name_for_run(run_id),
                stream=STREAM_NAME,
            )

        for run_id in list(self._subs.keys() - active_ids):
            del self._subs[run_id]

        new_cycle = build_weighted_cycle(active_runs)
        # The caller refreshes before every single fetch (active runs can
        # change between fetches), so resetting _cycle_pos to 0 here
        # unconditionally would mean every fetch restarts the round robin
        # from the front - the position never actually advances across
        # calls, which defeats the whole mechanism (the first run in
        # Postgres's sort order would dominate forever). Only reset when
        # the cycle's run-id membership actually changed; otherwise keep
        # rotating from where the last fetch left off.
        if set(new_cycle) != set(self._cycle) or self._cycle_pos >= len(new_cycle):
            self._cycle_pos = 0
        self._cycle = new_cycle

    async def fetch_one(self, timeout: float = 0.5) -> Msg | None:
        if not self._cycle:
            return None
        attempts = len(self._cycle)
        for _ in range(attempts):
            run_id = self._cycle[self._cycle_pos]
            self._cycle_pos = (self._cycle_pos + 1) % len(self._cycle)
            sub = self._subs.get(run_id)
            if sub is None:
                continue
            try:
                msgs = await sub.fetch(1, timeout=timeout)
            except TimeoutError:
                continue
            if msgs:
                return msgs[0]
        return None
