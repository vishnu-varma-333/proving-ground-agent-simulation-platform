"""Runs one simulation job: claims it, drives the reference agent
through the scenario's message with a real Recorder, records the
result, acks or nacks the NATS message.

Isolation here is data isolation only - a fresh temp directory per
simulation for the mock services' SQLite files, reseeded from scratch
(services/*/db.py already seeds on first connect). Real environment
*forking* from a shared snapshot (cheap, not "recreate from scratch
every time") is Milestone 7's job; this is the honest, simpler
predecessor that still gives every simulation its own isolated state,
which is all Milestone 6 needs to prove the distribution mechanics.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from nats.aio.msg import Msg
from pg_sdk import BlobStore, MetadataStore, Recorder, SimulationJob
from reference_agent.agent import ReferenceAgent
from reference_agent.mcp_tools import MockServiceToolbox

logger = logging.getLogger("pg_worker")

MAX_DELIVER = 5  # must match pg_sdk.queue.ensure_run_consumer's max_deliver


def new_worker_lease() -> str:
    return f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"


async def process_job(store: MetadataStore, job: SimulationJob, msg: Msg) -> None:
    attempt = msg.metadata.num_delivered
    worker_lease = new_worker_lease()
    await store.claim_simulation(job.sim_id, worker_lease, attempt)
    logger.info(
        "claimed sim=%s run=%s scenario=%s attempt=%d lease=%s",
        job.sim_id,
        job.run_id,
        job.scenario_id,
        attempt,
        worker_lease,
    )

    data_dir = Path(tempfile.mkdtemp(prefix=f"pg-sim-{job.sim_id}-"))
    try:
        scenario = await store.get_scenario(job.scenario_id)
        blob_store = BlobStore()
        recorder = Recorder(store=blob_store, run_id=job.sim_id, agent_name="reference_agent")

        async with MockServiceToolbox() as toolbox:
            await toolbox.connect(data_dir)
            agent = ReferenceAgent(toolbox, recorder=recorder)
            reply = await agent.respond(scenario["user_message"])

        manifest = recorder.finalize()
        await store.finish_simulation(
            job.sim_id,
            "completed",
            job.sim_id,
            {"reply": reply, "step_count": manifest["step_count"]},
        )
        await msg.ack()
        logger.info("completed sim=%s", job.sim_id)

    except Exception as exc:
        logger.exception("sim=%s failed on attempt %d", job.sim_id, attempt)
        if attempt >= MAX_DELIVER:
            await store.finish_simulation(job.sim_id, "failed", None, {"error": str(exc)})
            await msg.ack()  # exhausted - acking stops JetStream retrying a lost cause forever
        else:
            await store.retry_simulation(job.sim_id)
            await msg.nak()
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
