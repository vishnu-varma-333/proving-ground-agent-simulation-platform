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
- [x] **7. Snapshots and faults** — Environment forking and the
      fault-injection proxy.
- [x] **8. Evaluation** — State checks, simulated users, calibrated judges.
- [x] **9. Console** — Run explorer, replay viewer, version comparison.
- [x] **10. Ship it** — AWS deploy on spot nodes, scale and determinism
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

---

## Milestone 7: Snapshots and faults

**Status:** Done, live-verified. **Started / finished:** 2026-10-08.

**Goal.** Two pieces named in this milestone's own title: real
environment forking (replacing Milestone 6's reseed-from-scratch stand-in
with cheap file-copy snapshots of a template) and fault injection (a
layer that can add latency, errors, timeouts or partial responses to a
mock tool call, per scenario).

**What got built:**
- `pg_sdk.fork_environment` / `pg_sdk.environment`: plain file copies
  from a template directory into a fresh fork - the project's own
  "Snapshot strategy" design decision made concrete (SQLite file copies,
  not Postgres templates or copy-on-write).
- `pg_sdk.FaultInjectingToolbox` / `FaultSpec`: wraps the same
  `call()` boundary the Recorder/Player already use; one fault per tool
  name (`latency`, `error`, `timeout`, `partial`).
- Wired into `pg_worker.runner`: `ensure_template()` seeds a template
  once per `env_template_id`, then every simulation forks a copy;
  faults are read from the scenario's own `faults` column and applied
  only when present.
- `ReferenceAgent.respond()` now catches a tool-call failure and feeds
  it back to the model as a result instead of crashing the whole
  conversation - needed for fault injection to be something the agent
  can react to rather than something that just kills the simulation.
- 13 new unit tests (environment forking isolation, all four fault
  kinds, a real regression test for bug 21 using actual subprocesses) -
  65 total across the project, all passing, `ruff check` clean.

**Real bug found and fixed** (full detail in DECISIONS.md): the first
version of environment-template seeding connected to the mock services
and disconnected without calling any tool - but each service's SQLite
file is only created inside its first tool call, not at connect time.
The function logged success and left an empty directory; a second call
"reseeded" the same empty directory again. Found live (the log said
"seeded" twice for one template id), fixed by actually calling one
real, read-only tool per service, and covered by a regression test
using the real subprocesses rather than a mock.

**Live verification performed (not just unit tests):**
- **Error fault**: a `get_order` scenario configured with an `error`
  fault produced an agent reply declining to guess the order's status
  rather than crashing or hallucinating one.
- **Latency fault**: a 3s `latency` fault on the same tool still let
  the agent complete correctly with the real order data once the delay
  passed.
- **The forking bug itself**, found by noticing the seed log fired
  twice for what should have been an idempotent operation - fixed, then
  proven with a regression test against the real mock-service
  subprocesses (a mock MCP connection would not have reproduced the bug).

---

## Milestone 8: Evaluation

**Status:** Done, live-verified. **Started / finished:** 2026-10-08.

**Goal.** The spec's core feature #8, two halves: deterministic checks
on a simulation's final mock-service state ("refund issued exactly
once"), and AI judges scoring conversation quality, calibrated against
a small human-labelled set (target metric: Cohen's kappa). Building
this also meant finally building the multi-turn "simulated user"
persona that Milestone 6's scenario format explicitly deferred - a
scenario can now either send one fixed message (the original form) or
set `simulated_user: true` and let a Gemini-backed persona hold a real
back-and-forth with the agent until it decides its own goal is met.

**What got built:**
- `pg_sdk.checks` (`CheckSpec`/`CheckResult`/`run_checks`): plain SQL
  assertions against a simulation's own forked service database -
  the spec's own "refund issued exactly once" example is one query
  away, no bespoke check-type DSL needed.
- `pg_sdk.clickhouse` (`ClickHouseClient`): ClickHouse's first real
  write in this project - raw HTTP (`JSONEachRow`), two tables
  (`check_results`, `judge_scores`) matching the data model the spec
  named back in Milestone 1 and that sat unused until now.
- `agents/eval_common`: a second, smaller, stateless implementation of
  the reference agent's own key/model-rotation retry idea
  (`generate_text`), used by the two new packages below - deliberately
  not shared code with `reference_agent.agent`, which is the tested
  system under test, not a library to extend.
- `agents/simulated_user` (`SimulatedUser`): a persona that generates
  the customer's next message from its own persona/goal and the
  agent's last reply, and decides for itself (not a fixed turn count)
  when its goal has been met, capped by `max_turns` as a safety bound.
  Not recorded or replayed - it plays the role a human tester typing
  messages would, not the system under determinism test.
- `agents/judge` (`score_conversation`, `cohen_kappa`): an AI judge
  that scores a finished transcript against its scenario's persona/
  goal (`resolved: bool`, `score: 1-5`, a one-line rationale), plus a
  direct (no-sklearn) implementation of Cohen's kappa for calibration.
- `scenarios` table gained `simulated_user` and `max_turns` columns
  (the existing `checks` JSONB column, present but unused since
  Milestone 6, is now actually read and written); `suite.py`/`run.py`
  wire both new fields and `checks` end to end from suite YAML through
  to the worker.
- `pg_worker.runner.run_conversation`: branches between the original
  fixed-message flow and the new simulated-user loop, returning a
  uniform transcript either way; `process_job` now also runs the
  scenario's checks and the judge after the agent finishes, writing
  both to ClickHouse and surfacing a summary (`checks_passed`,
  `judge_resolved`, `judge_score`) in the simulation's own Postgres
  result.
- `scripts/calibrate_judge.py`: runs four real scenarios (two plain
  successes, one driven through Milestone 7's own fault injection, one
  against a nonexistent order) through the real agent, hand-labels
  each from its actual reply, scores each with the real judge, and
  reports the real Cohen's kappa.
- 22 new unit tests (state checks against a real SQLite schema,
  simulated-user turn-taking and stop conditions, judge JSON parsing,
  Cohen's kappa edge cases, the worker's conversation-branching logic
  with fakes) - 87 total across the project, all passing.

**No genuine runtime bug surfaced live this milestone** - the first
milestone where that's true. One real mistake was caught before
causing one: `ClickHouseConfig`'s first draft pointed at ClickHouse's
in-cluster NodePort (30123) instead of the actual host port kind maps
it to (28123) - caught by re-reading `infra/kind/cluster-config.yaml`
before the first live call, not by a failure. Documented honestly in
DECISIONS.md rather than folded into "bugs found live."

**Live verification performed (not just unit tests):**
- **State checks against the real cluster**: all three scenarios in
  `suites/refunds.yaml` ran through the real scheduler → NATS → worker
  pipeline; each scenario's "refund issued exactly once" check ran
  against its own forked `payments.db` and the result landed in a real
  ClickHouse row. All three passed.
- **Simulated user against the real agent and real Gemini API**: the
  new `refund-via-chat` scenario produced a genuine multi-turn
  conversation (persona asks → agent asks for the order id → persona
  answers → agent issues the refund → persona says `DONE`) - 15
  recorded steps versus 9 for the single-message scenarios run in the
  same batch. The run hit real 429/503 responses partway through
  (free-tier throttling, not injected) and recovered via
  `eval_common.gemini`'s own retry/rotation.
- **Judge calibration, real numbers**: 4 real transcripts (2 plain
  successes, 1 real payments-outage failure via fault injection, 1
  nonexistent-order failure), each hand-labelled before the judge's
  verdict was requested. Raw agreement 4/4, **Cohen's kappa = 1.000**.
  Reported as a small sample (`n=4`) - a real, measured number on the
  set this project has, not a general reliability claim. Full numbers
  and setup in docs/BENCHMARKS.md.

**Still pending, deliberately left for later:**
- A broader, more diverse calibration set (more failure modes than
  "payments outage" and "nonexistent order", disagreement cases to see
  how kappa behaves when the judge is actually wrong about something).
- Running the judge on a sample rather than every simulation, once
  suite sizes grow large enough for that cost tradeoff to matter (every
  simulation gets judged today - cheap at this project's scale).
- Stacking a simulated-user scenario with fault injection together in
  one live run (both paths are proven independently; not yet proven
  together).

---

## Milestone 9: Console

**Status:** Done, live-verified. **Started / finished:** 2026-10-08.

**Goal.** The spec's exact Milestone 9 scope: a Next.js/TypeScript
console with a run explorer (run overviews, failure lists), a step-
by-step replay viewer that surfaces the simulated clock, and a side-
by-side comparison of two agent versions on the same suite - reading
live from the same Postgres, ClickHouse and S3 the rest of the
platform already writes to, with no separate API service.

**What got built:**
- `console/` - a Next.js 16 (App Router, TypeScript, Tailwind) app with
  `lib/postgres.ts`, `lib/clickhouse.ts`, `lib/tape.ts`: three plain
  server-side data modules, no REST layer in between (decision 31).
- `/` - every run, newest first, with live pass/fail/pending counts.
- `/runs/[runId]` - a run's simulations with each scenario's checks
  (from ClickHouse) and judge score, failed rows visually flagged.
- `/simulations/[simId]` - the full recorded tape in order: every
  model/tool/clock step, the simulated clock's actual recorded value
  shown inline for clock reads, and each step's full input/output
  (read straight from the same S3 manifest + content-addressed blobs
  `pg_sdk.Player` replays from - decision 32, not a separate ClickHouse
  Step table) expandable via native `<details>`.
- `/compare?a=&b=` - two runs of the same suite joined by scenario id,
  each scenario's outcome (ok / regressed / missing) on both sides and
  whether it changed.
- A deliberately restrained dark-only design system (one accent color,
  four semantic status colors, Geist Sans/Mono) - decision 33 - built
  specifically so the console reads as a serious internal engineering
  tool rather than a generic dashboard template.
- Two real backend bugs found and fixed while wiring the console
  against real data (both covered in DECISIONS.md and live-verified
  against the running cluster, not just unit-tested):
  1. `runs.status` was never persisted anywhere - every run sat at
     `'pending'` in Postgres forever, even long after every one of its
     simulations had finished. Fixed with
     `MetadataStore.maybe_finalize_run`, called from the worker right
     after each simulation's terminal state is recorded.
  2. `MetadataStore.create_simulation` crashed with a
     `UniqueViolationError` on a resubmitted suite instead of the
     idempotent no-op its own docstring already promised (simulation
     ids are deterministic by design) - found while resubmitting a
     suite to generate comparison data, which also left a dangling,
     zero-simulation run row behind. Fixed with `ON CONFLICT DO
     NOTHING`.

**Live verification performed (not just a dev-server screenshot):**
- Ran the real dev server against the real cluster and the real tape
  from Milestone 8's own `run_7db00aab410f`: the run explorer, run
  detail and replay viewer all rendered genuine data end to end,
  including expanding a real recorded Gemini request/response pair out
  of S3 and a real clock-read step's recorded timestamp.
- **Mobile viewport caught a real layout bug live**: at 375px wide, the
  data tables overflowed the page itself rather than scrolling in
  place. Fixed by wrapping each table in its own `overflow-x-auto`
  container; re-verified at the same width afterward.
- **Compare page, every branch exercised against real rows**: a self-
  comparison (`a=b=run_7db00aab410f`) proved the "no change" path
  against real joined data; a second, explicitly-labeled test run
  written directly into the real Postgres/ClickHouse tables (same
  technique as the `maybe_finalize_run` verification above, cleaned up
  immediately after) proved the "regressed," "missing," and "changed"
  paths all render correctly. A true second *agent-generated* run
  (resubmitting the suite with a different seed) took about 6 minutes
  on its third scenario under heavy free-tier throttling but did
  complete - `run_3be0effdaf4d`, a genuinely independent second run,
  diffed against the first with all three scenarios comparing
  identical ("no change"), a real data point about this reference
  agent's run-to-run consistency, not just a UI smoke test.
- `npm run build` (production build, not just the dev server) compiles
  clean with no type errors.

**Still pending, deliberately left for later:**
- Any real auth/access control on the console - it's a local, read-
  only dev tool today; Milestone 10's hosted recruiter demo will need
  to address this before the console is reachable from outside this
  machine.
- A light theme (deliberately deferred, not forgotten - see decision
  33).

---

## Milestone 10: Ship it

**Status:** Done, scoped with the project owner's explicit input.
**Started / finished:** 2026-10-08.

**Goal.** The spec's final v1 milestone, broken into what's genuinely
buildable without real-world consequences and what isn't: AWS
deployment (Terraform, Helm, spot nodes) costs real money and needs
credentials nobody handed over, so - confirmed directly with the
project owner before starting, not decided alone - it's written as
real, validated infrastructure-as-code and deliberately not applied.
Everything else (the `pg replay` CLI the spec's access-patterns
section names, Docker Compose self-hosting, the runbook, the
determinism-boundary document, a real postmortem, and the scale/
determinism reports) is built and live-verified in full.

**What got built:**
- `pg replay <sim-id>` (`platform/scheduler/src/pg_scheduler/
  {cli,replay}.py`) - the scheduler-level replay command the spec's
  own CLI section names, restructured `pg`'s argparse into `run`/
  `replay` subcommands and added a `[project.scripts] pg = ...` entry
  point. Finding it required fixing a real, spec-named gap first:
  `pg_sdk.recorder.StepKind` was missing `"user"` (the spec's own Step
  data model lists `model, tool, user, clock`), so no
  `simulated_user: true` scenario recorded before this milestone could
  actually be replayed end to end - every agent step was on the tape,
  but nothing recorded what the live persona had said to produce them.
  Fixed (`Recorder.record_user_turn` / `Player.replay_user_turn`),
  live-verified on a fresh 19-step multi-turn tape: all 19 steps
  replayed with zero mismatches, no live API, no MCP servers, no
  network.
- `docker-compose.yml` + `console/Dockerfile` - the spec's named
  self-hosting path, same images/credentials/host ports as
  `scripts/up.sh`'s kind cluster so nothing's connection string
  changes between the two. Live-verified completely: brought the full
  stack up, ran a real suite through it, confirmed the containerized
  console rendered the real result, found and fixed two real bugs
  (below).
- `infra/aws/terraform/` - VPC + EKS (community modules, not
  hand-rolled), two node groups (on-demand system / spot worker,
  0-desired, taints matching the Helm chart's own tolerations), S3,
  ECR, Secrets Manager, least-privilege IRSA roles for the worker and
  console separately, KEDA. `terraform validate` passes. **Not
  applied** - see DECISIONS.md decision 35.
- `infra/helm/proving-ground/` - one chart, `values.yaml` (matches
  local exactly) and `values-aws.yaml` (only the real deltas: real S3,
  IRSA annotations, spot-node tolerations, a `LoadBalancer` console
  service). `helm lint`/`helm template` pass; a real
  `helm install --dry-run=server` against the live kind cluster
  server-side-validated all 33 resources, including KEDA's own
  `ScaledJob` CRD (installed fresh this milestone, since the cluster
  had been recreated since Milestone 6).
- `docs/DETERMINISM.md` - the spec's own "document stating exactly
  what is and isn't deterministic," consolidating and extending what
  had been scattered across several DECISIONS.md entries: what's
  recorded/replayed and hash-verified (model, tool, clock, and now
  user-turn steps), and what isn't (model/key rotation state, injected
  latency, live-run retry jitter, concurrency inside an agent - the
  spec's own named example).
- `docs/RUNBOOK.md` - every operational command actually used while
  building this project, not written speculatively.
- `docs/POSTMORTEM-fair-dispatcher-starvation.md` - a full postmortem
  (summary, impact, timeline, root cause, resolution, lessons) on the
  most severe real bug this project found (Milestone 6's
  `FairDispatcher` starvation bug), in the format a genuine incident
  would get.
- Root `README.md` rewritten from its stale "Milestone 1" status into
  a real quickstart, scenario-format reference and project map -
  covering the spec's "Quickstart, scenario reference" docs-site
  content as thorough markdown rather than standing up a separate
  docs-site generator (a deliberate scope choice, not an oversight).
- `scripts/scale_test.py` + `pg_scheduler.replay_bench` - a dedicated,
  separate benchmark harness (never touches the real simulation
  pipeline) measuring the platform's own queue/worker/Kubernetes
  throughput, decoupled from Gemini's rate limit by replaying a tape
  instead of running live scenarios.

**Real bugs found and fixed:**
- **A CPU resource limit silently throttled the scale-test worker's
  cold start by over 10x** (`infra/k8s/local/platform/
  replay-bench-worker.yaml`) - found by isolating `replay_simulation`'s
  real cost (~0.1s, measured three independent ways) against the
  benchmark's actual measured throughput, which didn't add up until
  the CPU limit itself was the thing timed. Fixed; the same round that
  took ~65s before took ~4s after, a measured ~15x.
- **`object-storage` (SeaweedFS) OOMKilled under real concurrent
  load** it had never seen before (a handful of clients, normally) -
  its memory limit was a guess (512Mi) rather than a measurement;
  raised to 1Gi after confirming via `kubectl describe pod`'s own
  `OOMKilled` reason, not assumed.
- Two bugs in Docker Compose's own healthchecks, found by actually
  bringing the stack up rather than trusting the YAML: `localhost`
  resolved to `::1` first in a minimal image whose server only bound
  IPv4, and SeaweedFS's own master -> volume -> filer bootstrap
  (~15-30s) exceeded the default healthcheck retry budget before
  `start_period` was added.

**Live verification performed (not just written, actually run):**
- `pg replay` against both a fixed-message tape (existing, zero live
  calls needed) and a freshly-recorded multi-turn tape (new, to
  exercise the user-turn fix) - both replayed with zero mismatches.
- Docker Compose: full stack up, a real suite submitted and processed
  through it, the containerized console confirmed showing the real
  result - not just "the containers started."
- Terraform: `init`, `validate` (no AWS credentials needed for
  either - module/provider resolution and HCL correctness only).
- Helm: `lint`, `template` against both value sets, and a real
  `--dry-run=server` against the live cluster.
- The scale test: see docs/BENCHMARKS.md for the full numbers and the
  honestly-documented 64-worker hardware ceiling, including the exact
  failure evidence (OOMKilled, a dropped Postgres connection) rather
  than a faked or silently-omitted number.

**Still pending, deliberately left for later (confirmed with the
project owner, not quietly dropped):**
- The actual `terraform apply` / AWS deployment, the hosted recruiter
  console and the demo video - all blocked on the same real
  constraint (AWS credentials + real spend, confirmed before this
  milestone started rather than assumed).
- A genuine 64-worker throughput number - needs real multi-node
  capacity this single machine doesn't have; the exact same
  `scripts/scale_test.py` is what would measure it once that capacity
  exists.
- Production-to-the-letter network egress restriction ("no outbound
  network except approved model endpoints") - a security-group port
  rule can't actually enforce a domain allowlist; the real fix (AWS
  Network Firewall or equivalent) is named as a specific, honest gap
  in `infra/aws/terraform/README.md` rather than approximated.
