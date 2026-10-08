# Build Milestones

Each milestone ends with something running and tested. Checked off only when
live-verified, not merely when the code compiles. Detailed enough to double
as a teaching curriculum later.

- [x] **1. Foundations** — Repository, CI, local Kubernetes, PostgreSQL,
      ClickHouse, NATS, object storage, observability.
- [ ] **2. Reference agent and mock services** — A customer-support agent
      plus orders, payments and email mock services with SQLite state.
- [ ] **3. SDK and recording** — Python SDK intercepting model calls, tool
      calls and clock reads; tapes written to S3(-compatible storage).
- [ ] **4. Deterministic replay** — Replay from tape; determinism test suite
      passing.
- [ ] **5. Virtual time** — Simulated clock driving timers and waits.
- [ ] **6. Distributed engine** — Scheduler, NATS queue, worker leases,
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
  excluding `CLAUDE.md`, `AGENTS.md`, `.claude/` and similar AI-tooling
  droppings from ever being committed.
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

**Status:** In progress — core functionality live-verified end-to-end;
a couple of failure-mode checks still pending (see below).
**Started:** 2026-10-08.

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
  `google-genai`, decision 9) with jittered/bounded retry on transient
  errors and automatic rotation across multiple API keys when one's quota
  is exhausted.
- `scripts/smoke_test_mcp.py`: spins up each MCP server as a real
  subprocess over real stdio and exercises one real tool call per
  service — the protocol layer itself, not just the underlying Python
  functions.
- 17 unit tests (10 for the three services' DB/tool logic including
  refund idempotency and rejection paths, 7 for the agent's retry-delay
  parsing and key-rotation logic) — all passing, `ruff check` clean.

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

**Live verification performed (not just unit tests):**
- Real stdio MCP protocol smoke test against all three services
  (`scripts/smoke_test_mcp.py`): server starts, lists its real tools,
  answers one real call — PASS on all three.
- **Full live refund scenario against the real Gemini API**: asked the
  agent for a refund on a real seeded order. The agent looked up the
  order, looked up the payment, issued the refund, updated the order
  status, and sent a confirmation email — all through real tool calls,
  no mocked model responses. Verified the result wasn't just a plausible-
  sounding reply by reading the actual SQLite rows afterward: order
  status `refunded`, payment status `refunded`, exactly one `refunds` row
  with the correct amount and reason, exactly one email recorded with the
  right recipient and subject.

**Still pending (not dropped, just blocked on the real external
constraint found in bug 14 — more API key quota):**
- Duplicate-refund idempotency *through the full agent* (not just the
  service layer, which is already unit-tested): ask for the same refund
  twice in separate conversations, confirm still exactly one `refunds`
  row. First live attempt hit the free-tier daily quota mid-test.
- An unknown-order scenario through the full agent (should decline
  plainly rather than hallucinate order/payment details).
- A benchmark of real per-call latency and a rough per-scenario cost
  estimate for `docs/BENCHMARKS.md`, once enough quota is available to
  measure more than one or two calls without tripping the daily cap.
