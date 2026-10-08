# Runbook

Operational reference for running this platform locally, submitting
and investigating simulations, and what to do when something's stuck.
Every command here has actually been run against this project's own
cluster at some point while building it - nothing speculative.

## Bringing the local cluster up and down

```bash
scripts/up.sh             # kind cluster + Postgres/ClickHouse/NATS/object storage/Prometheus/Grafana
scripts/health-check.sh   # verify every service is actually reachable, not just "pod Running"
scripts/down.sh           # tear the kind cluster down
```

`scripts/up.sh` is idempotent - safe to rerun against an already-up
cluster. If a host port is already in use (commonly: a `docker compose`
stack started from the self-hosting path using the same port numbers
on purpose - see `docker-compose.yml`'s own comment on why), stop
whichever one you don't need before bringing the other up; both can't
hold the same host ports at once.

Self-hosting without kind at all: `docker compose up -d`, see
`console/README.md` and the comment at the top of `docker-compose.yml`.

## Submitting a suite and investigating results

```bash
uv run --package pg-scheduler pg run suites/refunds.yaml           # submit, wait, print a summary
uv run --package pg-scheduler pg run suites/refunds.yaml --no-wait  # submit and exit
uv run --package pg-worker python -m pg_worker --once               # process exactly one job (local dev)
uv run --package pg-worker python -m pg_worker                      # persistent loop
```

Then open the console (`cd console && npm run dev`, or the
Kubernetes-deployed one) at `/` for the run, `/runs/<run-id>` for its
simulations, `/simulations/<sim-id>` for the full step-by-step tape.

### A simulation failed - now what

```bash
uv run --package pg-scheduler pg replay <sim-id>
```

Reproduces it locally, step by step, from the tape alone - no live
model API, no MCP servers, no network. Prints every user/agent turn
and the step count consumed; a mismatch raises `ReplayMismatch` with
the exact step and both hashes, which is the real determinism
violation to go investigate (see `docs/DETERMINISM.md` for what's and
isn't covered). Works for both fixed-message and `simulated_user: true`
scenarios recorded after Milestone 10 (see DETERMINISM.md's
compatibility note for tapes recorded before it).

## Kubernetes Jobs + KEDA (the real autoscaled worker fleet)

```bash
scripts/deploy_platform.sh   # creates worker-api-keys Secret from .env.local, applies the ScaledJob + metrics exporter
kubectl -n proving-ground get scaledjob pg-worker
kubectl -n proving-ground get jobs -w
```

Requires KEDA already installed in the cluster (`helm install keda
kedacore/keda -n keda-system --create-namespace`, matching
`infra/aws/terraform/keda.tf`'s own installation for the AWS path).

**Queue draining but no Jobs appearing:** check the ScaledJob's trigger
can actually reach Prometheus - `infra/k8s/local/platform/
worker-scaledjob.yaml`'s own hard-won fix was a fully-qualified service
name (`prometheus.proving-ground.svc.cluster.local`, not bare
`prometheus`) specifically because KEDA's operator runs in a different
namespace (`keda-system`) and bare service names don't resolve across
namespaces. If Jobs still don't appear, check the operator's own logs
first (`kubectl -n keda-system logs deploy/keda-operator`) - it names
the exact DNS/connection failure, which is faster than guessing.

**A worker pod dies mid-simulation:** this is exactly what JetStream's
`ack_wait` + redelivery (`pg_sdk.queue.ensure_run_consumer`, `max_deliver
= 5`) exists for - the message redelivers to another worker
automatically. Confirm with `kubectl -n proving-ground get jobs` (a
failed Job's pod shows the restart) and `pg_sdk.MetadataStore
.list_simulations_for_run` (the simulation's `attempt` column
increments). No manual intervention needed unless a simulation has
exhausted all 5 attempts (`state = 'failed'`, `result.error` set) - at
that point it's a real failure to `pg replay`, not a platform problem.

## Stuck simulations, expired leases

**Not yet wired up as an automated alert** - the spec's own Production
readiness section asks for "alerts on stuck simulations, expired
leases and determinism violations," and this project doesn't have that
running yet (no Alertmanager / PagerDuty-equivalent is deployed; see
docs/MILESTONES.md's own pending list). Until then, the manual check:

```sql
-- simulations stuck "running" far longer than this suite normally takes
SELECT id, run_id, scenario_id, worker_lease, started_at
FROM simulations
WHERE state = 'running' AND started_at < now() - interval '10 minutes';
```

A genuinely stuck one (its worker died in a way JetStream's own
redelivery didn't catch - rare, but possible if the pod wedged rather
than actually exiting) can be manually reset with
`MetadataStore.retry_simulation(sim_id)` to put it back to `pending`
for the next delivery to claim.

## Gemini free-tier throttling

Expect real `429`/`503` responses under load - this project's own
multi-key rotation (`agent.py`'s `load_api_keys`) and
`eval_common.gemini`'s independent retry/rotation both handle this
automatically, but a `simulated_user` scenario can still take several
minutes under heavy throttling (observed live, Milestone 9/10: one
scenario took ~6 minutes under sustained 429s before succeeding). This
is expected behavior, not a hang, up to the point every configured key
is genuinely exhausted for the day - at which point `pg_worker`'s job
fails after `MAX_DELIVER` attempts and needs a fresh key or the next
day's quota reset, a real external constraint this project can't code
its way around (see DECISIONS.md).

## Checking the platform's own health

```bash
scripts/health-check.sh                       # every storage/queue service answering
kubectl -n proving-ground get pods             # pod-level status
open http://localhost:29090                    # Prometheus (queue depth, worker utilization, etc.)
open http://localhost:23000                     # Grafana
```
