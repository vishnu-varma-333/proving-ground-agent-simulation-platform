# Proving Ground

A distributed, deterministic simulation engine that runs thousands of
realistic scenarios against an AI agent before release and replays any
failure exactly.

AI agents are non-deterministic and talk to real tools and real users, so
teams can't reliably test them: bugs appear only in production, can't be
reproduced, and multi-day workflows are impossible to test quickly. Proving
Ground runs scenarios in parallel across a worker fleet, records every
model response, tool response and clock reading so any run replays exactly,
and drives simulations on a virtual clock so a three-day scenario finishes
in seconds.

Deterministic simulation testing — the technique behind famously reliable
databases — applied to AI agents.

## Status

Milestones 1-10 of v1 complete and live-verified against a real local
cluster (Milestone 10's AWS deployment is written as real Terraform/Helm
but deliberately not applied — see [DECISIONS.md](DECISIONS.md)).
[docs/MILESTONES.md](docs/MILESTONES.md) has full progress notes per
milestone; [DECISIONS.md](DECISIONS.md) has every real design decision,
with the trade-offs; [docs/BENCHMARKS.md](docs/BENCHMARKS.md) has every
measured number, with the setup that produced it.

## Quickstart

Requires Docker and `kubectl`. `kind` and `helm` are expected on `PATH`
(installed as standalone release binaries, not via a package manager).

```bash
make up                                   # local kind cluster + Postgres/ClickHouse/NATS/object storage
make health                               # verify every service is reachable and answering
uv sync --all-packages                    # install every workspace package into one shared venv

uv run --package pg-scheduler pg run suites/refunds.yaml   # submit a suite, wait, print a summary
uv run --package pg-worker python -m pg_worker --once      # process one queued job (repeat per scenario,
                                                             # or run without --once for a persistent loop)

cd console && npm install && npm run dev  # the run explorer / replay viewer / version comparison console
```

A simulation failed? `uv run --package pg-scheduler pg replay <sim-id>`
reproduces it locally, step by step, from its tape alone — no live model
API, no MCP servers, no network. See [docs/RUNBOOK.md](docs/RUNBOOK.md)
for this and every other operational task (Kubernetes Jobs + KEDA,
debugging a stuck simulation, Gemini throttling).

Prefer Docker Compose over `kind`? `docker compose up -d` brings up the
same services (the spec's own named self-hosting path) — see
[console/README.md](console/README.md) and `docker-compose.yml`'s own
header comment.

## Writing a scenario

A suite is a YAML file: one or more scenarios run against one agent
version, with one or more seeds. See
[suites/refunds.yaml](suites/refunds.yaml) for a complete real example;
the fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Scenario identifier, unique within the suite. |
| `persona` | yes | Who the simulated customer is, in plain language. |
| `goal` | yes | What they're trying to accomplish - also what the judge scores against. |
| `user_message` | one of this or `simulated_user` | A single fixed opening message - deterministic, versioned, replayed verbatim. |
| `simulated_user: true` | one of this or `user_message` | A real multi-turn conversation, generated live by a Gemini-backed persona (`agents/simulated_user`) that decides for itself when its goal is met. |
| `max_turns` | only with `simulated_user` | Safety cap on turns (default 4) - the persona usually stops itself sooner. |
| `env_template` | no (default `default`) | Which seeded mock-service snapshot to fork the simulation's environment from. |
| `faults` | no | A list of `{tool, kind, ...}` fault specs (`latency`, `error`, `timeout`, `partial`) injected at that tool's call boundary - see `pg_sdk.faults.FaultSpec`. |
| `checks` | no | A list of deterministic state checks run against the finished simulation's own forked mock-service database - see `pg_sdk.checks.CheckSpec` and the real example below. |

```yaml
checks:
  - description: refund issued exactly once for ord_1001
    service: payments
    sql: "SELECT COUNT(*) AS n FROM refunds WHERE order_id = ?"
    params: ["ord_1001"]
    expect: {n: 1}
```

Every scenario also gets an AI judge's score automatically (persona/goal
vs. the actual transcript) — nothing to configure for that part.

## What's and isn't deterministic

[docs/DETERMINISM.md](docs/DETERMINISM.md) states this precisely: every
model call, tool call, clock read and simulated-user turn is recorded and
replayed with a hash check; a few things (model/key rotation state,
injected latency, concurrency inside an agent) are not, and are named
there rather than left for a replay to silently not match.

## Project layout

```
agents/           reference_agent (the system under test), simulated_user, eval_common
sdk/pg_sdk/        the platform SDK - recording, replay, virtual time, faults, checks, queue, storage
services/          orders, payments, email - the mock services the reference agent calls
platform/          scheduler (pg CLI) and worker
console/           Next.js run explorer / replay viewer / version comparison
infra/             kind (local), k8s manifests, aws/terraform, helm chart
docs/              MILESTONES, BENCHMARKS, DETERMINISM, RUNBOOK, POSTMORTEM-*
```
