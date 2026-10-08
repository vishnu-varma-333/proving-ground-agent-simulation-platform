"""Runs one simulation job: claims it, forks an isolated environment
from a persistent template (Milestone 7 - replaces Milestone 6's
reseed-from-scratch stand-in), drives the reference agent through the
scenario's conversation (a fixed single message, or a multi-turn
simulated_user persona - Milestone 8) with a real Recorder (and fault
injection if the scenario specifies any), runs the scenario's
deterministic state checks and an AI judge against the finished
conversation (Milestone 8's "evaluation"), records the result, acks or
nacks the NATS message.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from judge.scorer import score_conversation
from nats.aio.msg import Msg
from pg_sdk import (
    BlobStore,
    CheckSpec,
    ClickHouseClient,
    FaultInjectingToolbox,
    FaultSpec,
    MetadataStore,
    Recorder,
    SimulationJob,
    fork_environment,
    run_checks,
)
from reference_agent.agent import ReferenceAgent
from reference_agent.mcp_tools import MockServiceToolbox
from simulated_user import SimulatedUser

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


async def run_conversation(
    agent: ReferenceAgent, scenario: dict
) -> tuple[str, list[dict[str, str]]]:
    """Drives either the original fixed single-message scenario, or
    (Milestone 8) a multi-turn simulated_user persona that reacts to the
    agent's replies until it decides its goal is met or max_turns is
    hit. Returns the agent's final reply and the full transcript (used
    by the judge below) in the same [{"role", "text"}, ...] shape
    either way."""
    if not scenario.get("simulated_user"):
        user_message = scenario["user_message"]
        reply = await agent.respond(user_message)
        return reply, [{"role": "user", "text": user_message}, {"role": "agent", "text": reply}]

    sim_user = SimulatedUser(
        persona=scenario["persona"], goal=scenario["goal"], max_turns=scenario["max_turns"]
    )
    message = await sim_user.opening_message()
    reply = ""
    for _ in range(scenario["max_turns"] + 1):
        reply = await agent.respond(message)
        next_message = await sim_user.next_message(reply)
        if next_message is None:
            break
        message = next_message
    return reply, sim_user.transcript


async def process_job(
    store: MetadataStore, job: SimulationJob, msg: Msg, clickhouse: ClickHouseClient
) -> None:
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
        checks_raw = scenario.get("checks")
        checks = [CheckSpec.from_dict(c) for c in json.loads(checks_raw)] if checks_raw else []

        blob_store = BlobStore()
        recorder = Recorder(store=blob_store, run_id=job.sim_id, agent_name="reference_agent")

        async with MockServiceToolbox() as real_toolbox:
            await real_toolbox.connect(data_dir)
            toolbox = FaultInjectingToolbox(inner=real_toolbox, faults=faults) if faults else real_toolbox
            agent = ReferenceAgent(toolbox, recorder=recorder)
            reply, transcript = await run_conversation(agent, scenario)

        manifest = recorder.finalize()

        check_results = run_checks(data_dir, checks) if checks else []
        if check_results:
            await asyncio.to_thread(clickhouse.insert_check_results, job.sim_id, check_results)

        judge_result = await score_conversation(scenario["persona"], scenario["goal"], transcript)
        await asyncio.to_thread(
            clickhouse.insert_judge_score,
            job.sim_id,
            judge_result.resolved,
            judge_result.score,
            judge_result.rationale,
            judge_result.model,
        )

        await store.finish_simulation(
            job.sim_id,
            "completed",
            job.sim_id,
            {
                "reply": reply,
                "step_count": manifest["step_count"],
                "checks_passed": sum(1 for r in check_results if r.passed),
                "checks_total": len(check_results),
                "judge_resolved": judge_result.resolved,
                "judge_score": judge_result.score,
            },
        )
        await msg.ack()
        logger.info("completed sim=%s", job.sim_id)
        await store.maybe_finalize_run(job.run_id)

    except Exception as exc:
        logger.exception("sim=%s failed on attempt %d", job.sim_id, attempt)
        if attempt >= MAX_DELIVER:
            await store.finish_simulation(job.sim_id, "failed", None, {"error": str(exc)})
            await msg.ack()  # exhausted - acking stops JetStream retrying a lost cause forever
            await store.maybe_finalize_run(job.run_id)
        else:
            await store.retry_simulation(job.sim_id)
            await msg.nak()
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
