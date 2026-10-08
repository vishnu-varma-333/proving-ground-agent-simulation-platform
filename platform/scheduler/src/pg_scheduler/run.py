"""Turns a loaded suite into a Run row plus one Simulation row and one
queued job per (scenario, seed) - "the scheduler turns a suite into
simulation jobs on the queue" (the spec's own architecture description).

A simulation's identity is its scenario version, agent version and seed
(the spec's data-model note) - sim_id is built from exactly those three,
so re-submitting the same suite against the same agent version produces
the same simulation ids rather than silently duplicating work.
"""

from __future__ import annotations

import hashlib
import uuid

from pg_sdk import MetadataStore, SimulationJob, ensure_run_consumer, ensure_stream, publish_job
from pg_sdk.queue import JetStreamContext

from pg_scheduler.suite import ScenarioDef, SuiteDef


def simulation_id(scenario: ScenarioDef, agent_version_id: str, seed: int) -> str:
    key = f"{scenario.id}:{scenario.version}:{agent_version_id}:{seed}"
    return f"sim_{hashlib.sha256(key.encode()).hexdigest()[:16]}"


async def submit_suite(
    store: MetadataStore, js: JetStreamContext, suite: SuiteDef
) -> str:
    await store.upsert_agent_version(suite.agent_version_id, suite.agent_image, suite.agent_git_sha)

    env_template_ids = {s.env_template for s in suite.scenarios}
    for template_id in env_template_ids:
        await store.upsert_environment_template(template_id, services=["orders", "payments", "email"])

    for scenario in suite.scenarios:
        await store.upsert_scenario(
            scenario_id=scenario.id,
            persona=scenario.persona,
            goal=scenario.goal,
            user_message=scenario.user_message,
            env_template_id=scenario.env_template,
            version=scenario.version,
            faults=list(scenario.faults),
            checks=list(scenario.checks),
            simulated_user=scenario.simulated_user,
            max_turns=scenario.max_turns,
        )

    await store.upsert_suite(suite.id, suite.name, [s.id for s in suite.scenarios])

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    await store.create_run(run_id, suite.id, suite.agent_version_id, priority=suite.priority)

    await ensure_stream(js)
    await ensure_run_consumer(js, run_id)

    for scenario in suite.scenarios:
        for seed in suite.seeds:
            sim_id = simulation_id(scenario, suite.agent_version_id, seed)
            await store.create_simulation(sim_id, run_id, scenario.id, seed)
            job = SimulationJob(
                sim_id=sim_id,
                run_id=run_id,
                scenario_id=scenario.id,
                seed=seed,
                agent_version_id=suite.agent_version_id,
            )
            await publish_job(js, job)

    return run_id
