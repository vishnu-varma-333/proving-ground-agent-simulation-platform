"""Runs one simulation job: claims it, forks an isolated environment
from a persistent template (Milestone 7 - replaces Milestone 6's
reseed-from-scratch stand-in), drives the reference agent through the
scenario's message with a real Recorder (and fault injection if the
scenario specifies any), records the result, acks or nacks the NATS
message.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from nats.aio.msg import Msg
from pg_sdk import (
    BlobStore,
    FaultInjectingToolbox,
    FaultSpec,
    MetadataStore,
    Recorder,
    SimulationJob,
    fork_environment,
)
from reference_agent.agent import ReferenceAgent
from reference_agent.mcp_tools import MockServiceToolbox

logger = logging.getLogger("pg_worker")

MAX_DELIVER = 5  # must match pg_sdk.queue.ensure_run_consumer's max_deliver
TEMPLATES_DIR = Path(os.environ.get("PG_ENV_TEMPLATES_DIR", "data_templates"))


def new_worker_lease() -> str:
    return f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"


async def ensure_template(template_id: str) -> Path:
    """Seeds a template directory once, the first time it's needed.

    Each mock service's SQLite file is created (and, for orders/
    payments, seeded) lazily *inside* its first tool call, not at MCP
    connect time - just connecting and disconnecting, as the first
    version of this function did, starts the subprocesses and leaves
    with an empty directory, no db files at all (found live: the log
    said "seeded" twice for the same template id, and the directory was
    genuinely empty on disk). One real, read-only tool call per service
    is what actually triggers creation - the lookup itself doesn't need
    to succeed, only to run."""
    template_dir = TEMPLATES_DIR / template_id
    if (template_dir / "orders.db").exists():
        return template_dir

    template_dir.mkdir(parents=True, exist_ok=True)
    async with MockServiceToolbox() as seeding_toolbox:
        await seeding_toolbox.connect(template_dir)
        await seeding_toolbox.call("get_order", {"order_id": "ord_1001"})
        await seeding_toolbox.call("get_payment", {"order_id": "ord_1001"})
        await seeding_toolbox.call("list_emails", {"to_address": "seed@example.com"})
    logger.info("seeded new environment template %s at %s", template_id, template_dir)
    return template_dir


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

        template_dir = await ensure_template(scenario["env_template_id"])
        fork_environment(template_dir, data_dir)

        faults_raw = scenario.get("faults")
        faults = [FaultSpec.from_dict(f) for f in json.loads(faults_raw)] if faults_raw else []

        blob_store = BlobStore()
        recorder = Recorder(store=blob_store, run_id=job.sim_id, agent_name="reference_agent")

        async with MockServiceToolbox() as real_toolbox:
            await real_toolbox.connect(data_dir)
            toolbox = FaultInjectingToolbox(inner=real_toolbox, faults=faults) if faults else real_toolbox
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
