# Build Milestones

Each milestone ends with something running and tested. Checked off only when
live-verified, not merely when the code compiles. Detailed enough to double
as a teaching curriculum later.

- [x] **1. Foundations** — Repository, CI, local Kubernetes, PostgreSQL,
      ClickHouse, NATS, object storage, observability.
- [x] **2. Reference agent and mock services** — A customer-support agent
      plus orders, payments and email mock services with SQLite state.
- [x] **3. SDK and recording** — Python SDK intercepting model calls, tool
      calls and clock reads; tapes written to S3(-compatible storage).
- [x] **4. Deterministic replay** — Replay from tape; determinism test suite
      passing.
- [x] **5. Virtual time** — Simulated clock driving timers and waits.
- [x] **6. Distributed engine** — Scheduler, NATS queue, worker leases,
      retries, Kubernetes Jobs, KEDA autoscaling. Kill tests.
- [ ] **7. Snapshots and faults** — Environment forking and the
      fault-injection proxy.
- [ ] **8. Evaluation** — State checks, simulated users, calibrated judges.
- [ ] **9. Console** — Run explorer, replay viewer, version comparison.
- [ ] **10. Ship it** — AWS deploy on spot nodes, scale and determinism
      reports, demo video, docs, write-up.
- [ ] **11. Version 2** — Failure shrinking, production capture, adversarial
      generation.

---

## Milestone 1: Foundations

**Status:** Done, live-verified. **Started / finished:** 2026-10-07 –
2026-10-08.

**Goal.** Nothing agent-specific yet — just the ground every later milestone
stands on: a repo, a local Kubernetes cluster, the four backing services
(PostgreSQL, ClickHouse, NATS JetStream, S3-compatible object storage), and
basic observability (Prometheus, Grafana), all brought up and torn down by
one command, with CI exercising the same bring-up on every push.

**What got built:**
- `infra/kind/cluster-config.yaml` — a 3-node (1 control-plane + 2 worker)
  kind cluster definition with 9 `extraPortMappings` exposing every backing
  service on a fixed, documented host port.
- `infra/k8s/local/base/` — kustomize-managed manifests for PostgreSQL
  (StatefulSet + PVC), ClickHouse (StatefulSet + PVC), NATS with JetStream
  enabled (StatefulSet + PVC, file-backed storage), and SeaweedFS as the S3-
  compatible object store (StatefulSet + PVC + a bucket-bootstrap Job).
- `infra/k8s/local/observability/` — Prometheus (scraping any pod annotated
  `prometheus.io/scrape: "true"` in the `proving-ground` namespace — nothing
  to scrape yet until Milestone 3+ instruments code) and Grafana with a
  pre-provisioned Prometheus datasource.
- `scripts/up.sh` / `down.sh` / `health-check.sh` and a `Makefile` wrapping
  them (`make up` / `make down` / `make health`).
- `.gitignore` covering Python/Node/Terraform artifacts and proactively
  excluding stray local tooling/config files from ever being committed.
- Tooling installed user-locally (no Homebrew): `helm` (official release
  binary), `uv` (official installer) managing a project-local Python 3.12.

**Real bugs found and fixed** (full detail in DECISIONS.md):
1. MinIO's container images were withdrawn from Docker Hub and quay.io by
   the vendor in 2025 — swapped the object store for SeaweedFS.
2. ClickHouse's `default` user needs a password once `CLICKHOUSE_PASSWORD`
   is set via env — an anonymous health-check query that worked earlier
   started failing with `AUTHENTICATION_FAILED`; fixed by authenticating
   every ClickHouse call as the `proving_ground` user.
3. The health-check script's own log-filename sanitization only handled
   spaces, not `:` or `/` in check names — silently broke several checks.
4. `kind` nodes keep their own containerd image store, discarded on
   `kind delete cluster`; every from-scratch bring-up re-pulled every image
   from its registry (minutes, dominated by pulls). First fix attempt
   (`kind load docker-image`) and its `docker save`-based fallback both hit
   a separate, unrelated bug (#5) and had to be abandoned.
5. `kind load docker-image` — and `docker save | kind load image-archive`
   — both fail against Docker Desktop's containerd-snapshotter image store
   with `ctr: content digest ... not found`. Fixed #4 for good with a
   pull-through registry mirror (kind's own documented pattern) instead:
   measured 52% faster warm-cache bring-up (1m 44.52s vs. 3m 37.16s cold —
   docs/BENCHMARKS.md).
6. The object-storage bucket-bootstrap Job races the object store's own
   startup on a cold bring-up and fails once or twice before succeeding —
   expected Kubernetes retry behavior (`backoffLimit`), not a real bug;
   left as-is rather than papered over with a redundant wait.

**Live verification performed (not just unit tests):**
- Full `scripts/health-check.sh` run: every service reachable from the
  host on its documented port, and answering a real query/ping, not just
  "pod is Running" — PASS on all 12 checks.
- Hard-killed `postgres-0` with `--grace-period=0 --force` mid-session
  (simulating a crash, not a graceful stop) after seeding a marker row;
  StatefulSet recreated the pod and the row was still there via the PVC.
- Hard-killed `nats-0` the same way after creating a JetStream stream and
  publishing a durable message; the stream and message both survived the
  restart via file-backed JetStream storage.
- Timed a full cold bring-up (kind cluster create + image pull/load +
  every service healthy) from a completely clean slate — see
  docs/BENCHMARKS.md for the measured numbers.

**Deliberately deferred to later milestones, not dropped:**
- OpenTelemetry collector — nothing emits traces yet (first real workload
  arrives in Milestone 2/3); adding a collector with no instrumented code
  to collect from would be unverifiable scaffolding. Revisit when the
  scheduler/mock services exist.
- Terraform / AWS resources — explicitly a Milestone 10 ("Ship it")
  deliverable in the spec; nothing to deploy to AWS yet.
- Helm chart packaging of these same manifests — the spec calls for Helm
  specifically for the self-hosting story and AWS deployment; local dev
  uses plain kustomize manifests for now, repackaged as a chart once there
  is a real app to ship (see DECISIONS.md if/when that happens).

---

## Milestone 2: Reference agent and mock services

**Status:** Done, live-verified. **Started / finished:** 2026-10-08.

**Goal.** The first real application code: a customer-support reference
agent that actually works, backed by three mock services (orders,
payments, email), each its own MCP server over its own SQLite file so it
can later be snapshotted and forked (Milestone 7). Nothing here talks to
the simulation platform yet — the SDK that intercepts an agent's calls to
record/replay them is Milestone 3; this milestone only needs the agent
and its tools to work standalone, as the realistic system under test
everything else will run thousands of scenarios against.

**What got built:**
- A uv workspace (`services/orders`, `services/payments`, `services/email`,
  `agents/reference_agent`) sharing one lockfile/venv (decision 6).
- Three MCP servers (`mcp` v2's `MCPServer`, decision 7), each with its
  own SQLite file and seed data:
  - **orders**: `get_order`, `list_orders_by_customer`,
    `update_order_status`.
  - **payments**: `get_payment`, `issue_refund` (idempotent — decision 8,
    backed by a real `UNIQUE(order_id)` constraint, not just an
    application check), `list_refunds`.
  - **email**: `send_email` (simulated, just recorded), `list_emails`.
- `ReferenceAgent` (`agents/reference_agent`): connects to all three MCP
  servers as real subprocesses, adapts their tool schemas into Gemini
  function declarations, and runs the tool-calling loop (Gemini via
  `google-genai`) with a 30s per-request timeout, bounded jittered
  retry on transient errors, and automatic rotation across models
  (cheap/high-quota first) and then API keys when one combination's
  quota is exhausted (decisions 9-10).
- `scripts/smoke_test_mcp.py`: spins up each MCP server as a real
  subprocess over real stdio and exercises one real tool call per
  service — the protocol layer itself, not just the underlying Python
  functions.
- 19 unit tests (10 for the three services' DB/tool logic including
  refund idempotency and rejection paths, 9 for the agent's retry-delay
  parsing and key/model-rotation logic) — all passing, `ruff check` clean.

**Real bugs found and fixed** (full detail in DECISIONS.md):
7. `uv sync` with no flags silently skips every workspace member.
8. `mcp` v2 renamed `FastMCP` → `MCPServer` — an unbounded `mcp>=1.2`
   dependency resolved to the new major version.
9. `sqlite3.Connection.execute()` can't run multi-statement SQL —
   payments' two-table schema needed `executescript()`.
10. The reference-agent package's first editable install was silently
    incomplete (no `.pth` finder) because it was synced before any real
    module existed.
11. MCP's `Tool.inputSchema` is actually `tool.input_schema` in the
    Python SDK.
12. `gemini-2.5-flash` was deprecated for new API keys mid-build; the
    live 404 named `gemini-3.8-flash` as the replacement.
13. A naive fixed-backoff retry compounded across tool-calling rounds and
    hung for 30+ minutes under real quota exhaustion before being killed.
14. The Gemini free tier's binding constraint is 20 requests/*day* per
    model, not just 5/minute — found only by continuing to hit it after
    "fixing" the per-minute case.
15. The *actual* root cause of the 30+ minute hangs was never the retry
    schedule - it was `HttpOptions.timeout` being unset, which means no
    timeout reaches httpx at all (`None` = wait forever). Every earlier
    retry fix was correctly bounding a code path that was never the one
    hanging. Fixed with an explicit 30s timeout plus running the
    (synchronous) model call via `asyncio.to_thread`.
16. A free-tier key can be denied outright (`403 PERMISSION_DENIED`,
    "project has been denied access"), independent of quota and not
    fixable by any retry/rotation logic - likely Google's abuse detection
    on rapid multi-account key creation. Correctly not retried; no code
    fix exists for this, it needs the account owner's attention.
17. The API-key loader's sequential scanner silently missed keys that
    didn't follow its expected naming - a key arrived as
    `GEMINI_API_KEY5` with no `GEMINI_API_KEY`/`_2`/`_3`/`_4` ever set,
    and the agent failed with "no API key set" despite a real key being
    present. Fixed with a regex scan over the whole environment.

**Live verification performed (not just unit tests):**
- Real stdio MCP protocol smoke test against all three services
  (`scripts/smoke_test_mcp.py`): server starts, lists its real tools,
  answers one real call — PASS on all three.
- **Full live refund scenario against the real Gemini API**: asked the
  agent for a refund on a real seeded order. The agent looked up the
  order, looked up the payment, issued the refund, updated the order
  status, and sent a confirmation email — all through real tool calls,
  no mocked model responses. Verified by reading the actual SQLite rows
  afterward, not by trusting the agent's own summary: order status
  `refunded`, payment status `refunded`, exactly one `refunds` row with
  the correct amount and reason, exactly one email recorded with the
  right recipient and subject.
- **Duplicate-refund idempotency through the full agent**: asked for the
  same refund again in a separate conversation. The agent correctly
  reported it was already refunded rather than attempting it again;
  `refunds` table still had exactly one row for that order, same id as
  before.
- **Unknown-order scenario**: asked for a refund on an order id that
  doesn't exist. The agent declined plainly ("could not be found")
  instead of hallucinating order or payment details; verified zero new
  rows in any of the three databases as a result.
- A second real refund (a different order) to get a clean timing number
  without reusing already-refunded state — see docs/BENCHMARKS.md.

---

## Milestone 3: SDK and recording

**Status:** Done, live-verified. **Started / finished:** 2026-10-08.

**Goal.** The piece that makes the platform's core promise possible: a
Python SDK sitting between an agent and its three sources of
non-determinism - model calls, tool calls, clock reads - recording every
one to a content-addressed tape in S3-compatible storage. No replay yet
(Milestone 4); this milestone only needs every call the reference agent
makes to be captured faithfully and verifiably, by an agent that doesn't
need the SDK to run at all if recording isn't turned on.

**What got built:**
- `sdk/pg_sdk` (new uv workspace member): `hashing.py` (canonical JSON +
  sha256, so identical content always hashes the same regardless of dict
  key order), `storage.py` (`BlobStore`, an S3-compatible client -
  SeaweedFS locally, real S3 in prod, same API - with real dedup via a
  HEAD-check before every blob upload), `recorder.py` (`Recorder`:
  sequences steps, hashes and stores each one's request/response,
  produces an ordered manifest), `clock.py` (`RecordingClock`: records
  every real-time read; Milestone 5 makes this a simulated clock).
- Wired into `agents/reference_agent`: `ReferenceAgent` takes an optional
  `recorder` (decision 13 - opt-in, zero platform dependency when
  omitted); all three call sites instrumented (`_call_model`, the
  tool-calling loop in `respond()`, and one clock read per message). The
  CLI gained `--record`, which creates a run id, records the whole
  conversation, and prints the step count on exit.
- `scripts/smoke_test_tape.py`: writes and reads back a blob, a step, and
  a manifest through the real `BlobStore` API, independent of unit tests.
- 10 new unit tests (hashing stability, recorder sequencing, content-
  addressing dedup, manifest shape) against a fake in-memory store - 29
  total across the whole project, all passing, `ruff check` clean.

**Real bugs found:** none this milestone - stated plainly in DECISIONS.md
rather than searched for one to report. Milestones 1-2 had already
forced out the registry-mirror, bucket-race, ClickHouse-auth and MCP-
version issues; this milestone's actual new surface area (hashing, S3
object layout, the dict-conversion boundary) was smaller and already
covered by unit tests before touching real storage.

**Live verification performed (not just unit tests):**
- `scripts/smoke_test_tape.py` against the real local SeaweedFS S3
  gateway (Milestone 1's cluster, brought back up for this): blob,
  step and manifest all round-tripped through actual object storage,
  read back independently of the code that wrote them.
- **Full reference-agent conversation with `--record`** against the real
  Gemini API and real MCP tool calls: produced a real 4-step tape
  (clock → model → tool → model), fetched the manifest directly from
  S3 afterward and confirmed the step order and kinds, then fetched the
  tool-call blob's actual bytes and confirmed they matched the real
  order lookup (`{"order_id":"ord_1002"}` → the real seeded order row).
- **Cross-run content-addressing, proven live, not assumed**: ran the
  identical scenario a second time as a separate run id. The tool call's
  input and output blob hashes were byte-identical to the first run's -
  real deduplication across runs, not just within one. Counted the
  actual objects in the bucket afterward: 3 runs' worth of steps (10
  total) attempted 20 blob writes; only 16 distinct blobs exist in
  storage. See docs/BENCHMARKS.md for the exact numbers.

---

## Milestone 4: Deterministic replay

**Status:** Done, live-verified. **Started / finished:** 2026-10-08.

**Goal.** The tape from Milestone 3 actually gets used: feed a recorded
run's model/tool/clock answers back to the agent instead of making real
calls, so a failure reproduces exactly without the live API or mock
services. The real bar isn't "replay prints the same text" - it's that
replay recomputes each step's request from scratch and that recomputed
request hashes identically to what was recorded, which is what actually
proves the recording/replay plumbing is sound (the LLM itself isn't
expected to be deterministic; the orchestration around it is).

**What got built:**
- `pg_sdk.Player` (`sdk/pg_sdk/src/pg_sdk/player.py`): loads a run's
  manifest, and for each `replay_model_call` / `replay_tool_call` /
  `replay_clock_read`, recomputes the request's hash the same way the
  recorder did and compares it against the tape (decision 14) before
  serving the recorded output. Three distinct, clearly-named failure
  modes: `TapeExhausted` (asked for more steps than were recorded),
  `TapeOrderMismatch` (asked for a different kind/name of step than the
  tape has next), `ReplayMismatch` (same kind/name, different content -
  the actual determinism violation).
- `ReferenceAgent` takes an optional `player` (mutually exclusive with
  `recorder`): when set, `_call_model` never touches the real Gemini
  client, the tool-calling loop never touches the real MCP toolbox, and
  the clock read never touches real time - every one is served from the
  tape instead. No API key or MCP servers are required in this mode at
  all (proven live, not just structurally).
- CLI gained `--replay RUN_ID "message"` (the same message that produced
  that run originally, since the tape records model/tool/clock outputs,
  not the human's own input - that was never non-deterministic).
- 6 new unit tests for `Player` (serves recorded outputs in order, tape
  exhaustion, kind/name mismatch, a real determinism-violation case,
  clock replay, and reading a tape with a fresh store object unrelated
  to the original `Recorder` instance) - 35 total across the project,
  all passing, `ruff check` clean.

**Real bugs found:** none - the one place a mismatch could have hidden
(the request-dict-building code diverging between record and replay) was
designed around by construction (decision 15), not discovered as a
failure afterward.

**Live verification performed (not just unit tests):**
- **Recorded a real refund** (order `ord_1004`), then **replayed it**
  with the exact same message, with `GEMINI_API_KEY*` deliberately unset
  and confirmed no mock-service processes were running beforehand: the
  reply text matched exactly, and the CLI reported "all 10 recorded
  steps consumed, no mismatch." Replay could not have made a live call -
  there was no key for it to use.
- **Confirmed replay never touched the real services**: refund row count
  in `payments.db` was 1 before replay and still exactly 1 (same id)
  after - replay produced the right answer without re-executing the
  real refund logic at all.
- **Deliberately broke replay** by feeding a different message
  ("What's the weather today?") against the same run id. It failed
  loudly and specifically: `pg_sdk.player.ReplayMismatch: determinism
  violation at seq 1 (model/gemini-flash-lite-latest): recorded input
  hash 936cc96de17e... but replay recomputed 1f701a8ca2bf...` - exactly
  the negative-test proof a determinism checker needs: a real deviation
  is caught, named, and located, not silently accepted.

---

## Milestone 5: Virtual time

**Status:** Done, live-verified. **Started / finished:** 2026-10-08.

**Goal.** The mechanism behind "a three-day scenario finishes in
seconds" (the project's own one-line pitch): a simulated clock that only
moves when told to, so anything waiting on it resolves the moment the
simulation decides to jump forward - not after real wall-clock time
actually passes. Scoped deliberately to the SDK primitive itself this
milestone, not retrofitted into the reference agent's own domain (which
has no honest reason to wait three days mid-conversation) - see
decision 18.

**What got built:**
- `pg_sdk.SimulatedClock` (`sdk/pg_sdk/src/pg_sdk/clock.py`): `now()`
  returns virtual time; `advance(seconds)` moves it forward and releases
  every pending `sleep()` whose deadline has been reached; nothing moves
  on its own. Timer ordering (decision 17) via a min-heap keyed on
  `(wake_time, insertion_sequence)` - ties broken by registration order,
  not arbitrarily.
- `pg_sdk.RealClock`: the real-wall-time behavior Milestones 3-4 used
  directly, now named and pluggable rather than hardcoded.
- `RecordingClock` takes an optional `clock` (default `RealClock()`) -
  fully backward compatible with every existing call site; nothing in
  `reference_agent` needed to change.
- `scripts/benchmark_virtual_time.py`: a standalone, real measurement of
  the actual claim (see docs/BENCHMARKS.md).
- 8 new unit tests (`test_clock.py`): real-clock sanity, simulated time
  not moving on its own, sleep blocking until the right `advance()`,
  the 72-hour-wait-in-milliseconds claim itself as a unit test, and two
  ordering tests that specifically try to break the heap (register a
  later-waking timer first; register two timers with the identical
  deadline) - 43 total across the project, all passing, `ruff check`
  clean.

**Real bugs found:** none - the one real risk (`heapq` comparing two
`asyncio.Event` objects on a tied wake time, which has no defined
ordering) was designed around before it could happen, not discovered as
a failure.

**Live verification performed (not just unit tests):**
- **`scripts/benchmark_virtual_time.py`, run 5 times**: a simulated
  72-hour wait resolved in 0.077-0.087ms of real wall-clock time every
  time - consistent, not a one-off fluke. Exact numbers and methodology
  in docs/BENCHMARKS.md.
- **Ordering proven adversarially, not just happy-path**: one test
  registers the timer that wakes *later* before the one that wakes
  *earlier*, then jumps past both at once, and asserts the earlier one
  still resolves first - the heap's correctness under the one way it
  could have been built wrong.

---

## Milestone 6: Distributed engine

**Status:** Done, live-verified. **Started / finished:** 2026-10-08.

**Goal.** Turn the single-agent demo into an actual distributed system:
a scheduler that turns a suite into queued simulation jobs, a worker
fleet that pulls them with lease/retry semantics (a crashed worker's job
is never lost, never double-counted), fair scheduling so one large suite
can't starve a smaller one, and Kubernetes Jobs autoscaled by KEDA based
on queue depth.

**What got built so far:**
- **Postgres data model** (`sdk/pg_sdk/src/pg_sdk/schema.sql` +
  `postgres.py`): `suites`, `scenarios`, `environment_templates`,
  `agent_versions`, `runs`, `simulations` - the first real use of
  Postgres in this project (idle since Milestone 1). Raw `asyncpg`, no
  ORM, matching the mock services' own plain-`sqlite3` style.
- **A minimal scenario/suite file format** (`platform/scheduler/src/
  pg_scheduler/suite.py`, YAML) - the first real formalization of
  "Scenario definitions" (core feature #1), deliberately kept to a
  persona/goal label plus one driving message; a full multi-turn
  simulated-user persona is Milestone 8's job.
- **NATS JetStream job queue** (`pg_sdk/queue.py`): one subject per run
  under a wildcard stream, `FairDispatcher` holding one filtered pull
  consumer per active run and cycling across them in a priority-weighted
  round robin (decision 20) - fairness lives on the consumer side
  because JetStream's strict per-stream FIFO ordering makes producer-
  side interleaving unable to recover it once one run has published far
  ahead of another.
- **Scheduler CLI** (`pg_scheduler`, decision 19): `pg run suite.yaml`
  submits a suite's scenarios as jobs, optionally polling Postgres until
  the run finishes.
- **Worker** (`pg_worker`): claims a job, gives the simulation a fresh
  isolated temp directory for the mock services (decision 21 - a
  deliberate, simpler stand-in for Milestone 7's real environment
  forking), runs the reference agent with a real `Recorder`, records
  the result, acks on success or nacks (with a Postgres-tracked retry)
  on failure up to `max_deliver`. `--once` mode is what will run inside
  a Kubernetes Job pod; the persistent loop is for local dev.
- 9 new unit tests for the queue/fairness logic (weighted-cycle math,
  dispatcher rotation including a regression test for bug 19 below) -
  52 total across the project, all passing, `ruff check` clean.

**Real bugs found** (full detail in DECISIONS.md):
18. The worker never called `load_dotenv()` - every simulation failed
    immediately with "no API key set" despite the key being present.
19. `FairDispatcher.refresh()` reset the round-robin position on every
    call, and the worker calls `refresh()` before every fetch - rotation
    never actually advanced across fetches, so one run would silently
    dominate forever. Found by re-reading the code before the live test,
    confirmed by reverting the fix and watching a new regression test
    fail exactly as predicted, then restored and reverified.

**Live verification performed (not just unit tests):**
- **End-to-end suite run**: `suites/refunds.yaml` submitted and fully
  processed through the real scheduler → queue → worker → agent → tape
  path against the live local cluster - two real refunds issued, both
  tapes verified in S3.
- **Kill test** (the spec's own "0 lost or double-counted simulations"
  target): hard-killed a worker right after it claimed a job, confirmed
  the simulation sat in `state=running` with the dead worker's lease,
  waited past the 15s ack-wait, and watched a second worker pick up the
  same job at `attempt=2` and complete it - exactly one refund issued
  for order `ord_1003`, zero duplication.
- **Fairness test**: submitted a 6-scenario suite immediately followed
  by a 2-scenario suite, ran one persistent worker, and read the real
  completion order back from Postgres timestamps: big, small, big,
  small, big, big, big, big - the small suite's two jobs landed in
  positions 2 and 4 of 8, not stuck behind all six of the big suite's.

**Kubernetes Jobs + KEDA autoscaling (completed after the checkpoint above):**
- `docker/worker.Dockerfile` packages the whole workspace (the worker
  spawns the mock services as subprocesses, so they have to be
  installed in the same venv) - built and pushed to a second, writable
  local registry (`localhost:5002`, decision 23) alongside Milestone 1's
  pull-through Docker Hub mirror, which only proxies docker.io and isn't
  a place to push a new image name.
- KEDA installed via Helm into `keda-system`.
- `infra/k8s/local/platform/metrics-exporter.yaml`: a small Deployment
  exposing `pg_pending_simulations`/`pg_running_simulations` (queried
  from Postgres, the real source of truth for backlog) for Prometheus
  to scrape - KEDA scales against this metric rather than NATS
  JetStream directly, because decision 20's one-consumer-per-run fair-
  dispatch design means there's no single static consumer name that
  reflects total backlog across every active run (decision 22).
- `infra/k8s/local/platform/worker-scaledjob.yaml`: a KEDA `ScaledJob`
  running the worker image with `--once` - one Job pod per simulation,
  exactly the spec's own "each worker pod runs one simulation in
  isolation."
- `scripts/deploy_platform.sh`: creates the `worker-api-keys` Secret
  from `.env.local` (never committed) and applies both manifests.

**Real bug found and fixed in this stretch** (full detail in
DECISIONS.md): the ScaledJob's Prometheus trigger used a bare
`prometheus` service name, which resolves fine for anything inside the
`proving-ground` namespace but not for KEDA's own operator, which runs
in `keda-system` - cross-namespace service names need to be fully
qualified. The operator's own logs named the exact DNS failure.

**Live verification performed (Kubernetes Jobs + KEDA, real numbers):**
- Confirmed the custom image is pullable from *inside* the kind cluster
  via the new local registry: a test pod pulled
  `localhost:5002/pg-worker:dev` in 2.048s.
- **Full autoscaling run**: submitted a 4-scenario suite. KEDA scaled
  the ScaledJob from 0 to 4 replicas, 4 separate Job pods each pulled
  and processed exactly one simulation, all 4 completed successfully
  (verified in Postgres, not just `kubectl get jobs`), and KEDA scaled
  back to 0 once the queue drained.
- **Clean, isolated timing measurement** (a second single-job run,
  after the DNS bug was fixed, to avoid a number contaminated by manual
  debugging time): submission to KEDA creating the pod - **11.1s**; job
  execution - 17s (one lookup, consistent with Milestone 2's per-call
  timing); scale-down to `ACTIVE: False` - within the next 2s polling
  check after completion. Full numbers in docs/BENCHMARKS.md.

**Still pending, deliberately left for later:**
- Priorities (the data model and dispatcher already support a priority
  weight; only equal-priority fairness has been exercised live so far,
  not two runs at genuinely different priorities).
- Cleaning up a finished run's durable JetStream consumer
  (`delete_run_consumer` exists but isn't called from anywhere yet -
  decision 20's accepted minor leak).
- Throughput at higher worker counts (`maxReplicaCount` was 4 for this
  test, matching the exact queue depth tested; the spec's own
  1/4/16/64-worker throughput table needs a real suite larger than this
  milestone's verification needed).
