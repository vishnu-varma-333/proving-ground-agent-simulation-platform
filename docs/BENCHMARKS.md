# Benchmarks

Only real, measured numbers, with the setup that produced them. Nothing
here is an estimate presented as a measurement — where a number can't be
measured yet, that's stated explicitly, with why.

## Methodology defaults for this document

- **Hardware:** Apple MacBook Air, Apple M2 (arm64), macOS 26.5.2, running
  under Docker Desktop (containerd-snapshotter image store backend).
- **Cluster:** local `kind` v0.30-class cluster, 1 control-plane + 2 worker
  nodes, Kubernetes v1.31.0 (`kindest/node:v1.31.0`).
- Every number below states its own run conditions in addition to these
  defaults, since "cold" vs "warm" cache changes the result by an order of
  magnitude and must never be conflated.

---

## Milestone 1: Foundations

### Local stack bring-up time

**What:** Wall-clock time from `scripts/up.sh` invocation (no kind cluster,
no containers for this project running) to every backing service passing
`scripts/health-check.sh` — i.e. the full developer inner-loop cost of
starting from nothing.

**How measured:** `time ./scripts/up.sh`, macOS `time` builtin (user+sys+
elapsed), cluster and all Docker containers for this project torn down
immediately beforehand so the run is genuinely cold.

| Run | Condition | Result |
| --- | --- | --- |
| 1 | Cold: no cluster, host Docker image cache empty for 6 of 7 images, `kind load docker-image` approach (before it was found broken) | Did not complete — failed partway through image loading with `ctr: content digest ... not found` (DECISIONS.md, bug 4). Elapsed to failure: ~59s (cluster create + first image pull), then a hard error with no workaround from our side. |
| 2 | Cold: no cluster, empty pull-through registry mirror (its very first run, so every image still goes mirror → Docker Hub once), 3 of 7 images already warm in host cache from run 1's partial pulls | 3m 37.16s to a fully healthy stack (`time ./scripts/up.sh`, real elapsed). One job-level retry: the bucket-bootstrap Job raced object storage's own image pull and failed twice with `Could not connect to the endpoint`, then succeeded on its Job-controller retry (`backoffLimit: 6`) once the pod was ready — expected Kubernetes behavior, not a bug. |
| 3 | Warm: no cluster (fresh `kind create`), registry mirror cache now warm from run 2 | **1m 44.52s** to a fully healthy stack. |

Run 3 is the number that matters for day-to-day dev: every `make down &&
make up` cycle after the first one on a given machine lands around 1m 45s,
not 3-4 minutes. The improvement (3m 37s → 1m 45s, ~52% faster) is the
registry mirror paying off exactly as intended — images are served from
`kind-registry-mirror` on the Docker network instead of Docker Hub.

Not measured: a *genuinely* first-ever run on a brand new machine (empty
host Docker cache **and** no mirror container yet). Run 2 above is close
but not exact, since 3 of 7 images were already warm on the host from run
1's partial attempt. Capturing the true first-run number would mean wiping
unrelated cached images this machine uses for other projects, which wasn't
done since it has no bearing on the number this document actually needs
(the steady-state dev-loop cost, run 3).

### Teardown time

**What:** Wall-clock time for `scripts/down.sh` (`kind delete cluster`)
with the cluster in the healthy state above.

**Result:** 3.28s (`KIND_BIN=kind ./scripts/down.sh` — real 3.281s).

### Crash recovery (kill tests)

**What:** Hard-kill (`kubectl delete pod --grace-period=0 --force`, i.e. no
graceful shutdown) a stateful pod mid-session and check whether its data
survived the StatefulSet recreating it, via the pod's PersistentVolumeClaim.

| Service | Setup before kill | Result after recreation |
| --- | --- | --- |
| PostgreSQL | `CREATE TABLE kill_test`; inserted one marker row | Row present, byte-identical, after pod recreation |
| NATS JetStream | Created stream `KILLTEST` (file storage), published one message | Stream and message both present after pod recreation; sequence number unchanged |

Not yet measured: recovery **time** (how long until the service is healthy
again) and behavior under *concurrent* load during the kill (both pods were
idle when killed) — the spec's own kill tests (Milestone 6) exercise the
scheduler and worker fleet under active load, which doesn't exist yet at
Milestone 1. This section only establishes that the storage layer itself
(PVCs + StatefulSet semantics) is sound before anything is built on top of
it.

### What's deliberately not benchmarked yet

- **Throughput, virtual-time speedup, environment fork cost, cache savings,
  judge reliability, fault tolerance under load, bugs-found-in-reference-
  agent** — every one of these from the spec's own metrics table requires
  code that doesn't exist until Milestones 2-8 (the reference agent, SDK,
  scheduler, snapshot/fault logic, evaluation judges). Listed here rather
  than silently omitted, per this document's own rule: nothing is measured
  before it can be measured for real.
