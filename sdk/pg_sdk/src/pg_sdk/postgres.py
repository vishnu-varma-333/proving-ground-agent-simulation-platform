"""Metadata store (Milestone 1's data model table): suites, scenarios,
agent versions, runs and simulations. First real use of PostgreSQL in
this project - every earlier milestone's storage was SQLite (mock
services) or S3 (tapes). Raw asyncpg, no ORM - consistent with how the
mock services use plain sqlite3 rather than an ORM (see DECISIONS.md).
"""

from __future__ import annotations

import json
import os
from importlib import resources
from typing import Any

import asyncpg


def _dsn() -> str:
    return os.environ.get(
        "PG_POSTGRES_DSN",
        "postgresql://proving_ground:proving-ground-local-dev@127.0.0.1:25432/proving_ground",
    )


async def connect_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=_dsn(), min_size=1, max_size=10)


async def apply_schema(pool: asyncpg.Pool) -> None:
    schema_sql = resources.files("pg_sdk").joinpath("schema.sql").read_text()
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)


class MetadataStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    # --- suites / scenarios / agent versions (write-once setup data) ----

    async def upsert_environment_template(self, template_id: str, services: list[str]) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO environment_templates (id, services) VALUES ($1, $2) "
                "ON CONFLICT (id) DO NOTHING",
                template_id,
                services,
            )

    async def upsert_scenario(
        self,
        scenario_id: str,
        persona: str,
        goal: str,
        user_message: str,
        env_template_id: str,
        version: int = 1,
        faults: list | None = None,
        checks: list | None = None,
        simulated_user: bool = False,
        max_turns: int = 1,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO scenarios
                    (id, version, persona, goal, user_message, env_template_id, faults, checks,
                     simulated_user, max_turns)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (id) DO UPDATE SET
                    version = EXCLUDED.version,
                    persona = EXCLUDED.persona,
                    goal = EXCLUDED.goal,
                    user_message = EXCLUDED.user_message,
                    env_template_id = EXCLUDED.env_template_id,
                    faults = EXCLUDED.faults,
                    checks = EXCLUDED.checks,
                    simulated_user = EXCLUDED.simulated_user,
                    max_turns = EXCLUDED.max_turns
                """,
                scenario_id,
                version,
                persona,
                goal,
                user_message,
                env_template_id,
                json.dumps(faults or []),
                json.dumps(checks or []),
                simulated_user,
                max_turns,
            )

    async def upsert_suite(self, suite_id: str, name: str, scenario_ids: list[str]) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO suites (id, name, scenario_ids) VALUES ($1, $2, $3) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, "
                "scenario_ids = EXCLUDED.scenario_ids",
                suite_id,
                name,
                scenario_ids,
            )

    async def upsert_agent_version(self, version_id: str, image: str, git_sha: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO agent_versions (id, image, git_sha) VALUES ($1, $2, $3) "
                "ON CONFLICT (id) DO NOTHING",
                version_id,
                image,
                git_sha,
            )

    async def get_scenario(self, scenario_id: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM scenarios WHERE id = $1", scenario_id)
            if row is None:
                raise KeyError(f"no scenario {scenario_id!r}")
            return dict(row)

    # --- runs / simulations (the state the scheduler and workers mutate) --

    async def create_run(self, run_id: str, suite_id: str, agent_version_id: str, priority: int = 0) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO runs (id, suite_id, agent_version_id, priority) VALUES ($1, $2, $3, $4)",
                run_id,
                suite_id,
                agent_version_id,
                priority,
            )

    async def list_active_runs(self) -> list[tuple[str, int]]:
        """(run_id, priority) for every run that still has pending or
        running simulations - what pg_sdk.FairDispatcher cycles across."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT r.id, r.priority
                FROM runs r
                JOIN simulations s ON s.run_id = r.id
                WHERE s.state IN ('pending', 'running')
                ORDER BY r.id
                """
            )
            return [(row["id"], row["priority"]) for row in rows]

    async def set_run_status(self, run_id: str, status: str, finished: bool = False) -> None:
        async with self.pool.acquire() as conn:
            if finished:
                await conn.execute(
                    "UPDATE runs SET status = $1, finished_at = now() WHERE id = $2", status, run_id
                )
            else:
                await conn.execute("UPDATE runs SET status = $1 WHERE id = $2", status, run_id)

    async def create_simulation(self, sim_id: str, run_id: str, scenario_id: str, seed: int) -> None:
        """`ON CONFLICT DO NOTHING` because sim_id is deterministic
        (scenario version + agent version + seed - see
        pg_scheduler.run.simulation_id): resubmitting the same suite
        against the same agent version is documented to reuse the same
        simulation ids rather than duplicate work, but the plain INSERT
        here crashed with a UniqueViolationError instead of actually
        doing that - found live while resubmitting a suite to generate
        comparison data for the console's compare page, which also left
        a dangling empty run row behind (submit_suite creates the run
        row before this call, so a crash here orphans it). This fixes
        the crash; a resubmitted simulation keeps belonging to whichever
        run first created it."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO simulations (id, run_id, scenario_id, seed) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (id) DO NOTHING",
                sim_id,
                run_id,
                scenario_id,
                seed,
            )

    async def claim_simulation(self, sim_id: str, worker_lease: str, attempt: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE simulations SET state = 'running', worker_lease = $1, attempt = $2, "
                "started_at = now() WHERE id = $3",
                worker_lease,
                attempt,
                sim_id,
            )

    async def retry_simulation(self, sim_id: str) -> None:
        """A failed attempt that still has redeliveries left - back to
        'pending' so list_active_runs still finds this run, until the
        next delivery claims it again."""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE simulations SET state = 'pending' WHERE id = $1", sim_id)

    async def finish_simulation(
        self, sim_id: str, state: str, tape_ref: str | None, result: dict | None
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE simulations SET state = $1, tape_ref = $2, result = $3, "
                "finished_at = now() WHERE id = $4",
                state,
                tape_ref,
                json.dumps(result) if result is not None else None,
                sim_id,
            )

    async def get_simulation(self, sim_id: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM simulations WHERE id = $1", sim_id)
            if row is None:
                raise KeyError(f"no simulation {sim_id!r}")
            return dict(row)

    async def list_simulations_for_run(self, run_id: str) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM simulations WHERE run_id = $1 ORDER BY created_at", run_id
            )
            return [dict(row) for row in rows]

    async def maybe_finalize_run(self, run_id: str) -> None:
        """Sets the run's own status once every one of its simulations has
        reached a terminal state - 'failed' if any did, else 'completed',
        the same rule pg_scheduler.cli's wait loop already used to decide
        its exit code, just never persisted. Called after each simulation
        finishes; a harmless race if two workers finish a run's last two
        simulations at once (both see every simulation terminal and write
        the same final status - idempotent, not a double-count)."""
        sims = await self.list_simulations_for_run(run_id)
        if not sims or any(s["state"] not in ("completed", "failed") for s in sims):
            return
        status = "failed" if any(s["state"] == "failed" for s in sims) else "completed"
        await self.set_run_status(run_id, status, finished=True)
