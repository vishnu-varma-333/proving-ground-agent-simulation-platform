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

---

## Milestone 2: Reference agent and mock services

### Per-conversation-turn latency (live Gemini API)

**What:** Wall-clock time for one `python -m reference_agent "<message>"`
invocation, from process start to final printed answer - includes Python/
MCP-subprocess startup, every tool call and every model round trip.

**How measured:** macOS `time` builtin, real Gemini API (`gemini-flash-
lite-latest`), real MCP subprocesses, real SQLite files already seeded
from an earlier run (not a cold database).

| Scenario | Model round trips | Result |
| --- | --- | --- |
| Read-only lookup ("what is the status of order ord_1002?") | 2 (tool call + final answer) | 5.09s real (1.83s user / 0.22s sys - most of the wall time is the network round trip, not local CPU) |
| Full refund (lookup order, lookup payment, issue refund, update status, send email, final answer) | up to 6 | 9.75s real (1.83s user / 0.20s sys) |

Both are single, cold-start-of-the-process measurements (no warm
connection reuse), on a free-tier key with no other concurrent load. Not
yet measured: p50/p95 across many runs, or any number under real
concurrent load - meaningless before Milestone 6's distributed engine
exists to generate that load.

### Free-tier quota, measured directly from live 429 responses

Not an estimate - read directly from the API's own error bodies while
building and testing this milestone:

| Model | Quota metric | Free-tier limit |
| --- | --- | --- |
| `gemini-3.8-flash` | `GenerateRequestsPerMinutePerProjectPerModel-FreeTier` | 5/minute |
| `gemini-3.8-flash` | `GenerateRequestsPerDayPerProjectPerModel-FreeTier` | 20/day |
| `gemini-flash-lite-latest` (`gemini-3.5-flash-lite`) | (per ai.google.dev/gemini-api/docs/rate-limits, not independently hit yet) | ~500/day |

A single full refund conversation costs up to 6 model round trips - on
`gemini-3.8-flash` alone, that's less than 4 complete refund
conversations before exhausting the entire *day's* quota. This is the
concrete number behind decision 10 (model rotation) and the standing
flag that this project's real goal - thousands of simulations
(Milestone 6+) - needs a paid key regardless of how many free ones are
rotated through.

### What's deliberately not benchmarked yet

Everything from the spec's metrics table that needs the SDK, scheduler,
or evaluation judges - unchanged from Milestone 1's note. Added to that
list now: real per-call *cost* in dollars (needs the actual pricing page
cross-referenced with real token counts, not done yet) and judge-model
latency/accuracy (Milestone 8).

---

## Milestone 3: SDK and recording

### Content-addressed dedup, measured directly from real storage

**What:** Count of actual objects under `blobs/` in the SeaweedFS bucket
after a mix of runs, versus the number of blob-write calls those runs
made, read with `list_objects_v2` independent of the recorder that wrote
them.

**How measured:** `scripts/smoke_test_tape.py` (1 run, 2 steps) plus two
back-to-back `reference_agent --record` invocations of the identical
scenario (4 steps each), all against the same local SeaweedFS bucket,
then a direct `boto3.list_objects_v2(Prefix="blobs/")`.

| Metric | Count |
| --- | --- |
| Total steps recorded (2 + 4 + 4) | 10 |
| Blob-write calls made (2 per step: request + response) | 20 |
| Distinct blobs actually present in storage | **16** |
| Confirmed-identical pair, cross-run | the second run's `get_order` tool-call input AND output hashes exactly matched the first run's |

4 of the 20 write attempts hit an existing hash and were skipped - a 20%
dedup rate on this small, repetitive sample. Not a claim about dedup
rate at scale (Milestone 6's real throughput numbers will tell that
story with thousands of runs); this is the mechanism proven to actually
work against real storage, with the real numbers from doing it.

### What's deliberately not benchmarked yet

Carried over from Milestones 1-2, plus: replay fidelity (Milestone 4 -
nothing replays a tape yet, so there's nothing to measure), and any
cache *hit-rate-driven cost savings* (the spec's own "cache savings"
metric needs the scheduler actually re-running suites, Milestone 6+).

---

## Milestone 4: Deterministic replay

### Replay fidelity (the spec's own target metric, first real measurement)

**What:** Whether a recorded run's final output, replayed with the same
input, matches exactly - and whether every one of its steps' recomputed
request hashes matches what was recorded (the real test; matching final
text alone could hide a step-level divergence that happened to cancel
out).

**How measured:** One real recorded refund conversation (10 steps:
clock, model, tool, model, tool, model, tool, model, tool, model),
replayed once with the identical input, read back through `pg_sdk.Player`
with no live API key present and no MCP server processes running.

| Run | Result |
| --- | --- |
| Replay with identical input | All 10/10 steps matched; final reply text identical to the original run; zero live calls made (no key available to make one) |
| Replay with a deliberately different input (negative test) | Failed at step 1 of 10 (the first model call) with a named, located `ReplayMismatch` - correctly caught, not silently wrong |

This is **1 run** replayed, not the spec's "100% identical across 10,000
replays" target (Milestone 1's benchmarks table) - that number needs
volume this project doesn't have until Milestone 6's distributed engine
can actually run thousands of simulations. What's measured here is that
the mechanism itself is sound on a real run, which is the precondition
for that number meaning anything later.

### What's deliberately not benchmarked yet

Carried over from Milestones 1-3. Replay *performance* (how much faster
a replay is than the original live run, now that no network calls
happen) wasn't measured this milestone - worth doing once there's a
reason to care about replay speed specifically, e.g. Milestone 6's kill
tests re-running failed simulations at volume.

---

## Milestone 5: Virtual time

### Virtual-time speedup (the spec's own target metric, Milestone 1's table)

**What:** Real wall-clock time for a 72-hour simulated wait against
`pg_sdk.SimulatedClock`, versus the 72 real hours that wait would cost
against a real clock.

**How measured:** `scripts/benchmark_virtual_time.py` - creates a task
that `await`s `clock.sleep(72 * 3600)`, immediately calls
`clock.advance(72 * 3600)`, times the whole thing with
`time.perf_counter()`. Run 5 times in a row on the same machine as
Milestone 1's numbers (Apple M2, macOS 26.5.2).

| Run | Real wall-clock time for the 72h wait |
| --- | --- |
| 1 | 0.070ms |
| 2 | 0.087ms |
| 3 | 0.078ms |
| 4 | 0.084ms |
| 5 | 0.077ms |

**Spec's own starting target:** under 10 seconds for a 72-hour scenario
(Milestone 1's benchmarks table, "Virtual-time speedup" row). **Measured:
~0.08ms** - about 125,000x inside that target, and roughly 3.3 billion
times faster than the real 72-hour wait it stands in for.

This measures the clock primitive alone, not an end-to-end agent
scenario spanning simulated days (decision 18 - no such scenario exists
yet). The number that will matter later is wall-clock time for a real
multi-day *agent* scenario once one exists, not just the bare clock
mechanism - this is the floor that number can't beat, not the ceiling.

### What's deliberately not benchmarked yet

Carried over from Milestones 1-4, plus: virtual time under concurrent
load (many simulated clocks / many pending timers at once) - meaningless
before Milestone 6's distributed engine exists to generate that load.
