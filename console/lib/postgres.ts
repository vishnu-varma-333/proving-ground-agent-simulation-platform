// Postgres is the metadata store (suites, scenarios, runs, simulations) -
// the same database and schema pg_sdk.postgres writes to; this is a second,
// read-only client speaking to it directly (no shared code with the Python
// side makes sense across a language boundary, same reasoning as decision
// 29's separate Gemini-calling code for Python).
import { Pool } from "pg";
import type { AgentVersionRow, RunRow, SimulationRow, SuiteRow } from "./types";

let pool: Pool | null = null;

function getPool(): Pool {
  if (!pool) {
    pool = new Pool({
      connectionString:
        process.env.PG_POSTGRES_DSN ??
        "postgresql://proving_ground:proving-ground-local-dev@127.0.0.1:25432/proving_ground",
    });
  }
  return pool;
}

export async function listRuns(limit = 50): Promise<RunRow[]> {
  const { rows } = await getPool().query(
    `SELECT
       r.id, r.suite_id, s.name AS suite_name, r.agent_version_id, r.priority,
       r.status, r.started_at, r.finished_at,
       COUNT(sim.id)::int AS total,
       COUNT(sim.id) FILTER (WHERE sim.state = 'completed')::int AS completed,
       COUNT(sim.id) FILTER (WHERE sim.state = 'failed')::int AS failed,
       COUNT(sim.id) FILTER (WHERE sim.state IN ('pending', 'running'))::int AS pending
     FROM runs r
     JOIN suites s ON s.id = r.suite_id
     LEFT JOIN simulations sim ON sim.run_id = r.id
     GROUP BY r.id, s.name
     ORDER BY r.started_at DESC
     LIMIT $1`,
    [limit],
  );
  return rows;
}

export async function getRun(runId: string): Promise<RunRow | null> {
  const { rows } = await getPool().query(
    `SELECT
       r.id, r.suite_id, s.name AS suite_name, r.agent_version_id, r.priority,
       r.status, r.started_at, r.finished_at,
       COUNT(sim.id)::int AS total,
       COUNT(sim.id) FILTER (WHERE sim.state = 'completed')::int AS completed,
       COUNT(sim.id) FILTER (WHERE sim.state = 'failed')::int AS failed,
       COUNT(sim.id) FILTER (WHERE sim.state IN ('pending', 'running'))::int AS pending
     FROM runs r
     JOIN suites s ON s.id = r.suite_id
     LEFT JOIN simulations sim ON sim.run_id = r.id
     WHERE r.id = $1
     GROUP BY r.id, s.name`,
    [runId],
  );
  return rows[0] ?? null;
}

export async function listSimulationsForRun(
  runId: string,
): Promise<SimulationRow[]> {
  const { rows } = await getPool().query(
    `SELECT
       sim.id, sim.run_id, sim.scenario_id, sim.seed, sim.state, sim.worker_lease,
       sim.tape_ref, sim.result, sim.attempt, sim.created_at, sim.started_at, sim.finished_at,
       sc.persona, sc.goal, sc.user_message, sc.simulated_user
     FROM simulations sim
     JOIN scenarios sc ON sc.id = sim.scenario_id
     WHERE sim.run_id = $1
     ORDER BY sim.created_at ASC`,
    [runId],
  );
  return rows;
}

export async function getSimulation(
  simId: string,
): Promise<SimulationRow | null> {
  const { rows } = await getPool().query(
    `SELECT
       sim.id, sim.run_id, sim.scenario_id, sim.seed, sim.state, sim.worker_lease,
       sim.tape_ref, sim.result, sim.attempt, sim.created_at, sim.started_at, sim.finished_at,
       sc.persona, sc.goal, sc.user_message, sc.simulated_user
     FROM simulations sim
     JOIN scenarios sc ON sc.id = sim.scenario_id
     WHERE sim.id = $1`,
    [simId],
  );
  return rows[0] ?? null;
}

export async function listAgentVersions(): Promise<AgentVersionRow[]> {
  const { rows } = await getPool().query(
    `SELECT id, image, git_sha, created_at FROM agent_versions ORDER BY created_at DESC`,
  );
  return rows;
}

export async function listSuites(): Promise<SuiteRow[]> {
  const { rows } = await getPool().query(
    `SELECT id, name, created_at FROM suites ORDER BY created_at DESC`,
  );
  return rows;
}

export async function listRunsForSuite(suiteId: string): Promise<RunRow[]> {
  const { rows } = await getPool().query(
    `SELECT
       r.id, r.suite_id, s.name AS suite_name, r.agent_version_id, r.priority,
       r.status, r.started_at, r.finished_at,
       COUNT(sim.id)::int AS total,
       COUNT(sim.id) FILTER (WHERE sim.state = 'completed')::int AS completed,
       COUNT(sim.id) FILTER (WHERE sim.state = 'failed')::int AS failed,
       COUNT(sim.id) FILTER (WHERE sim.state IN ('pending', 'running'))::int AS pending
     FROM runs r
     JOIN suites s ON s.id = r.suite_id
     LEFT JOIN simulations sim ON sim.run_id = r.id
     WHERE r.suite_id = $1
     GROUP BY r.id, s.name
     ORDER BY r.started_at DESC`,
    [suiteId],
  );
  return rows;
}
