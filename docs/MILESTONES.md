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
