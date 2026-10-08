-- Metadata store schema (Milestone 1's data model table, first real use
-- of Postgres in this project - every earlier milestone's own storage
-- was SQLite per mock service or S3 for tapes).
--
-- EnvironmentTemplate exists here to match the spec's data model, but is
-- barely used before Milestone 7 (environment forking/snapshots); it's
-- created now rather than bolted on later so the schema doesn't change
-- shape mid-project for no reason.

CREATE TABLE IF NOT EXISTS suites (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    scenario_ids TEXT[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS environment_templates (
    id TEXT PRIMARY KEY,
    services TEXT[] NOT NULL,
    snapshot_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 1,
    persona TEXT NOT NULL,
    goal TEXT NOT NULL,
    user_message TEXT NOT NULL,
    env_template_id TEXT REFERENCES environment_templates(id),
    faults JSONB NOT NULL DEFAULT '[]',
    checks JSONB NOT NULL DEFAULT '[]',
    simulated_user BOOLEAN NOT NULL DEFAULT false,
    max_turns INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_versions (
    id TEXT PRIMARY KEY,
    image TEXT NOT NULL,
    git_sha TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL REFERENCES suites(id),
    agent_version_id TEXT NOT NULL REFERENCES agent_versions(id),
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS simulations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    scenario_id TEXT NOT NULL REFERENCES scenarios(id),
    seed INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    worker_lease TEXT,
    tape_ref TEXT,
    result JSONB,
    attempt INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS simulations_run_id_idx ON simulations(run_id);
CREATE INDEX IF NOT EXISTS simulations_state_idx ON simulations(state);
CREATE INDEX IF NOT EXISTS runs_suite_id_idx ON runs(suite_id);
