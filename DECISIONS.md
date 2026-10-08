# Design Decisions

Every real design decision, in the order made: the options considered, what
was chosen, why, and what it cost. Written for interview talking points, not
as documentation — specifics and real trade-offs, not generic justification.

---

## 1. Local cluster: kind, multi-node

**Options considered:** `kind` (Kubernetes-in-Docker), `k3d`/`k3s`, Docker
Compose without Kubernetes at all, minikube.

**Chosen:** `kind`, 1 control-plane + 2 worker nodes.

**Why:** The platform's own production target is Kubernetes (EKS with spot
nodes, KEDA-driven autoscaling of worker Jobs — Milestone 6+). Developing
against real Kubernetes primitives (StatefulSets, Jobs, NodePort Services,
PVCs, RBAC) from Milestone 1 means the manifests written now are the same
manifests that run in production later, not a parallel Compose setup that
has to be reconciled with the "real" one afterward. `k3d` is a reasonable
alternative (lighter weight, built-in LoadBalancer via servicelb) but `kind`
is the SIG-maintained reference implementation and what most interviewers
will recognize immediately. Multi-node (not single-node) because later
milestones (distributed engine, kill tests, autoscaling) need to exercise
actual pod-to-node scheduling, not just intra-node behavior.

**Cost:** A 3-node kind cluster is heavier to start than a single Compose
`up` — measured cold-start time is in docs/BENCHMARKS.md. Multi-node kind
also means NodePort Services (not simple host-port binding) to reach
services from the host, which is one more layer to explain (see decision 3).

---

## 2. Object storage: SeaweedFS instead of MinIO

**Options considered:** MinIO (as the original spec called for), SeaweedFS,
Garage (deuxfleurs), RustFS, LocalStack's S3 emulation.

**Chosen:** SeaweedFS, run as a single `weed server -s3` process with its
embedded S3 gateway enabled.

**Why:** MinIO Inc. withdrew the `minio/minio` and `minio/mc` images from
Docker Hub and quay.io during 2025; every tag now returns
`pull access denied: repository does not exist or may require authorization`
for an anonymous pull, and MinIO's AGPL community edition went source-only
as of its final container release. This was discovered live, mid-build (see
the real bug log below), not assumed — confirmed first by `docker manifest
inspect` against several MinIO tags and both registries, then corroborated
by search. Rebuilding MinIO from source was on the table but adds a Go build
step to the local dev loop for no benefit over a maintained alternative.
RustFS (a MinIO-API-compatible fork born from exactly this situation) was
considered but is new enough that its long-term maintenance is unproven.
Garage is actively maintained and lightweight but its layout/bootstrap for a
single node is more ceremony than this project needs. SeaweedFS is mature,
widely deployed in production elsewhere, and its `-s3` flag gives a
drop-in S3-compatible gateway with no separate configuration file.

**Cost:** SeaweedFS's default S3 gateway runs without authentication unless
an explicit identity/access config is supplied — fine for a local, no-network-
exposed kind cluster, but it means the bucket-bootstrap Job's AWS credentials
are decorative (SeaweedFS ignores them) rather than enforced. This is flagged
again in Milestone 7 (isolation/security) and will need a real decision if
SeaweedFS is still in use when the platform is deployed to AWS, versus
switching to real S3 there (the spec's "S3 (MinIO locally)" row already
implies prod and local diverge here anyway).

---

## 3. NodePort + kind `extraPortMappings` over port-forward for local access

**Options considered:** `kubectl port-forward` run ad hoc per service,
NodePort Services with static ports mapped through kind's
`extraPortMappings`, an ingress controller.

**Chosen:** Fixed NodePort Services (30400s-30900s range), each mapped to a
distinct host port via the kind cluster config's `extraPortMappings`.

**Why:** `port-forward` requires a long-lived foreground process per service
and dies silently on pod restart, which would have hidden the kill-test
results behind a reconnect step. A static, scripted port map means `up.sh`
and CI both get the same stable `localhost:<port>` endpoints with zero
manual steps, and the health-check script can hit them directly. An ingress
controller is the right answer for the console (Milestone 9) but is pure
overhead for raw TCP/HTTP backing services that nothing but the platform's
own code and this developer will ever address directly.

**Cost:** Every new service needs a nodePort + extraPortMapping pair kept in
sync by hand across `infra/kind/cluster-config.yaml` and the service's own
manifest; nothing enforces that automatically. Documented port table lives
in the manifests and `scripts/up.sh`'s own banner output.

---

## 4. Local credentials committed in plain Secret manifests

**Options considered:** Generate random local credentials via a script and
gitignore them, use `kubectl create secret` imperatively (never on disk),
commit fixed dev-only credentials in the manifests.

**Chosen:** Fixed, clearly-labeled dev-only credentials committed directly
in each Secret manifest (e.g. `proving-ground-local-dev`).

**Why:** These credentials only ever authenticate services inside a
disposable, non-networked kind cluster that is deleted and recreated
constantly; they are never valid anywhere else and never will be (AWS
deployment uses AWS Secrets Manager — Milestone 10's production-readiness
requirement). Generating them randomly would make `up.sh` non-reproducible
for no security benefit, and keeping them out of git entirely would mean
every clone needs an undocumented bootstrap step before anything works.

**Cost:** A future contributor skimming the manifests could mistake these
for real secrets if the comments are ever stripped. Mitigated by a comment
on every such Secret pointing at this decision.

---

## 5. Pull-through registry mirror instead of `kind load docker-image`

**Options considered:** (a) `kind load docker-image` — the standard way to
inject host-cached images into a kind cluster without a registry round
trip; (b) `docker save | kind load image-archive` — the usual fallback
when (a) fails; (c) a local pull-through registry cache that kind's
containerd reads through on every pull; (d) accept the slow re-pull and
move on.

**Chosen:** (c), following kind's own documented
["local registry"](https://kind.sigs.k8s.io/docs/user/local-registry/)
pattern — a `registry:2` container (`REGISTRY_PROXY_REMOTEURL` pointed at
`https://registry-1.docker.io`) on the same Docker network as the kind
nodes, referenced from `containerdConfigPatches` in the cluster config as
a mirror for `docker.io`.

**Why:** Both (a) and (b) were tried first and both failed identically —
`ctr: content digest sha256:... not found` during `ctr images import
--all-platforms` — against Docker Desktop's containerd-snapshotter image
store backend (confirmed via `docker info`'s `driver-type:
io.containerd.snapshotter.v1`). This is a known kind/Docker-Desktop
incompatibility, not a mistake in how the images were pulled or saved:
Docker's multi-arch manifest list for e.g. `postgres:16.4` references
other platforms' blobs that were never actually pulled to this arm64
host, and kind's `--all-platforms` import tries to import them anyway.
There is no supported flag to make kind skip non-local platforms during
import. (d) would have meant eating a 3-4 minute re-pull on every single
`down`/`up` cycle for the rest of the project — unacceptable for a dev
loop used dozens of times across the remaining ten milestones. The
registry mirror sidesteps the broken code path entirely: nodes pull
normally over the network (no special kind command involved), just from a
cache instead of Docker Hub.

**Cost:** One more long-lived container (`kind-registry-mirror`,
`--restart=always`) that `down.sh` deliberately does not touch, so its
cache survives cluster teardown — this is the point, but it means "is my
object storage actually clean" questions in later milestones need to
remember the *registry* cache is independent of the *cluster's* data
(PVCs), which independently get wiped by `kind delete cluster`. Measured
payoff: cold bring-up with an already-warm mirror cache is 1m 44.52s vs.
3m 37.16s with a cold one (docs/BENCHMARKS.md) — roughly 52% faster, on
every bring-up after the first.

---

## Real bugs found while building Milestone 1

Documented here rather than silently fixed, per the project's own rule:

1. **MinIO images unpullable.** `docker manifest inspect minio/minio:<any
   tag>` → `pull access denied`, both on Docker Hub and quay.io. Root cause:
   vendor withdrawal (2025), not a local config issue. Fix: decision 2 above.

2. **ClickHouse HTTP query returns 403 for the unauthenticated `default`
   user.** Setting `CLICKHOUSE_PASSWORD` via the container's environment
   variables locks down the `default` user, so anonymous `curl` queries that
   worked in earlier manual testing started failing with
   `AUTHENTICATION_FAILED` (code 516) once credentials were introduced. Fix:
   every ClickHouse HTTP call (health check included) now authenticates as
   `proving_ground`, which matches how the real SDK/scheduler will connect
   anyway — the health check was wrong to assume anonymous access, not
   ClickHouse.

3. **Own health-check script crashed on its own log filenames.** The
   `check()` helper only replaced spaces in a check's name before using it
   in a `/tmp/...` path; names containing `:` or `/` (e.g.
   `"nats: jetstream enabled (/jsz)"`) produced an invalid path and the
   whole check silently failed with a shell error instead of a real
   PASS/FAIL. Fix: sanitize with `tr -c 'A-Za-z0-9' '_'` instead of a single
   space substitution.

4. **`kind` doesn't share the host Docker image cache.** Every image a kind
   node pulls lives in that node's own containerd store, not the host
   Docker daemon's. `kind delete cluster` throws that store away entirely,
   so a from-scratch `up.sh` re-pulls every image from its registry even
   though `docker images` on the host shows nothing missing — timed at
   several minutes dominated by image pulls (docs/BENCHMARKS.md). First
   fix attempt (`kind load docker-image` after a host-side `docker pull`)
   hit bug 5 below and had to be replaced. Final fix: decision 5 above (a
   pull-through registry mirror).

5. **`kind load docker-image` (and its `docker save | kind load
   image-archive` fallback) both fail on this host.** Both reliably threw
   `ctr: content digest sha256:... not found` during `ctr images import
   --all-platforms`, against Docker Desktop's containerd-snapshotter image
   store. Root cause and fix: decision 5 above.

6. **Bucket-bootstrap Job raced the object store's own startup.** On a
   cold bring-up, `object-storage-create-buckets` reached
   `Could not connect to the endpoint URL` twice before the SeaweedFS pod
   finished pulling its image and became ready, because nothing orders a
   plain `Job` after a `StatefulSet`'s readiness. Not a bug in the strict
   sense — the Job's `backoffLimit: 6` is exactly Kubernetes's own answer
   to this race, and it did recover and succeed on a later attempt every
   time it was observed — but worth naming because `up.sh`'s `kubectl wait
   --for=condition=complete` would otherwise look like a hang rather than
   an expected retry. Left as-is rather than "fixed" with an initContainer
   wait: the retry behavior is the correct Kubernetes-native answer, and
   adding a redundant wait would just be two mechanisms doing one job.

---

## Milestone 2: Reference agent and mock services

## 6. Monorepo as a single uv workspace, one package per service/agent

**Options considered:** One flat Python package for everything; a uv
workspace with a member package per deployable (orders/payments/email
services, reference agent); fully separate repos per service.

**Chosen:** A uv workspace (`[tool.uv.workspace]` at the repo root), one
member under `services/<name>` or `agents/<name>` per deployable, each
with its own `pyproject.toml` and `src/` layout, sharing one lockfile and
one `.venv`.

**Why:** Each mock service is genuinely independent (own SQLite file, own
MCP process, will run as its own container later), so they need their own
dependency manifests - but they're developed and tested together
constantly, so a single shared venv and one `uv sync --all-packages` is
far faster than juggling four separate virtualenvs for a project this
size. Separate repos would be the wrong trade for a solo portfolio project
with this much cross-service iteration.

**Cost:** `uv sync` (no flags) only syncs the root project, silently
skipping every workspace member unless you know to pass
`--all-packages` - cost real time when the first sync appeared to
succeed but installed nothing but `pytest`/`ruff` (bug 7 below).

## 7. MCP servers built on `mcp` v2's `MCPServer`, not `FastMCP`

**Options considered:** Pin `mcp<2` to keep using `FastMCP`'s decorator
API (the version most existing docs/tutorials show); migrate to `mcp` v2's
`MCPServer` (`FastMCP` renamed and restructured).

**Chosen:** `mcp` v2's `MCPServer` (`from mcp.server.mcpserver import
MCPServer`), current as of this build.

**Why:** `pyproject.toml` declared `mcp>=1.2` with no upper bound, and `uv
sync` correctly resolved that to the latest release - v2.3.0 - which had
already renamed `FastMCP` to `MCPServer` with a restructured API. Pinning
to `mcp<2` would have meant deliberately building on a superseded API
just to match older tutorials; adapting to the real current SDK is more
correct and a better portfolio signal than code that only works because
of a version pin nobody would otherwise need.

**Cost:** None beyond the one-time migration - the v2 `@mcp.tool()`
decorator is actually simpler to test with (see bug 8 below): it returns
the plain function unchanged, instead of v1's `FastMCP` wrapping it in a
`Tool` object accessed via `.fn`.

## 8. Refund idempotency enforced in the mock service itself

**Options considered:** Let the agent be responsible for checking "have I
already refunded this?" before calling `issue_refund`; enforce it inside
`payments_service.issue_refund` with a `UNIQUE(order_id)` constraint on
the `refunds` table.

**Chosen:** Enforced in the service: a second `issue_refund` call for the
same order returns the existing refund (`already_refunded: true`) instead
of creating a duplicate, backed by a real SQL `UNIQUE` constraint, not
just an application-level check.

**Why:** The spec's own evaluation story (Milestone 8) names "refund
issued exactly once" as the canonical example of a deterministic state
check. If that invariant only held because the agent happened to check
first, it would be the agent's correctness being tested, not the
platform's ability to catch a violation. Enforcing it at the data layer
means a buggy or malicious agent that calls `issue_refund` five times
still can't produce five refunds - the check later milestones run against
this is actually meaningful.

**Cost:** None found yet. Verified live (not just unit-tested): asking the
reference agent to refund the same order twice, in two separate
conversations, produced exactly one `refunds` row both times.

## 9. Gemini as the reference agent's model, with dev-time multi-key rotation

**Options considered:** Anthropic Claude, OpenAI, Gemini; for Gemini
specifically, a single free-tier key vs. several personal free-tier keys
rotated on exhaustion vs. paying for one key up front.

**Chosen:** Gemini (`google-genai` SDK, native function calling), with the
agent able to rotate across multiple `GEMINI_API_KEY_N` keys when one hits
its daily quota.

**Why:** Gemini Flash-tier pricing is cheap per call, which matters a lot
once the platform is running thousands of simulations (Milestone 6+) and
the spec explicitly wants cost measured and reported. Multi-key rotation
is a pragmatic, time-boxed way to keep building and testing *today*
without paying anything, using several of the user's own existing Google
accounts - not a production design: the real cost/throughput story
belongs to Milestone 3's SDK (model-call layer) and its caching, and the
free tier's actual daily caps (see bug 10 below) mean this project's real
goal - thousands of simulations - will need a paid key regardless, before
any later milestone's throughput numbers mean anything.

**Cost:** Key rotation is dev-only scaffolding that should not be mistaken
for the platform's real cost-control design. It's isolated to
`ReferenceAgent.load_api_keys`/`_rotate_key` specifically so it's easy to
delete or replace once Milestone 3 builds the real model-call layer.

---

## Real bugs found while building Milestone 2

7. **`uv sync` silently installed almost nothing.** With no flags, `uv
   sync` only syncs the *root* project; every workspace member (all four
   services/agents) was skipped with no error. `uv sync --all-packages`
   is required to install the whole workspace together.

8. **`mcp.server.fastmcp.FastMCP` doesn't exist in the installed `mcp`
   2.3.0** - raises `ModuleNotFoundError` with its own migration-guide
   link. Root cause: decision 7 above (an unbounded `mcp>=1.2` dependency
   resolved to the newest major version, which renamed the class).

9. **`sqlite3.Connection.execute()` can only run one SQL statement.**
   `payments_service`'s schema has two `CREATE TABLE` statements separated
   by `;`; `conn.execute(SCHEMA)` raised `ProgrammingError: You can only
   execute one statement at a time`. `orders_service` and `email_service`
   each have only one table, so the same bug was latent there but never
   triggered. Fixed by using `executescript()` for any schema with more
   than one statement.

10. **The reference-agent workspace package's editable install was
    silently incomplete.** After the *first* `uv sync --all-packages`
    (run when the package held only an empty `__init__.py`), site-packages
    had `reference_agent-0.1.0.dist-info` but no `_editable_impl_*.pth`
    finder - `import reference_agent` raised `ModuleNotFoundError` even
    though `uv sync` reported success. The other three packages (which
    already had real modules at that point) got their `.pth` files
    correctly. Fixed with `uv sync --all-packages --reinstall-package
    reference-agent` once the real source files existed.

11. **MCP's `Tool.inputSchema` doesn't exist** - the Python SDK exposes it
    as `tool.input_schema` (snake_case); the wire protocol's camelCase
    `inputSchema` is a JSON field name, not the Python attribute.
    `AttributeError: 'Tool' object has no attribute 'inputSchema'. Did you
    mean: 'input_schema'?` - the SDK's own message named the fix.

12. **`gemini-2.5-flash` is no longer available to new API keys.** The
    live API's 404 response named the replacement directly:
    `models/gemini-2.5-flash is no longer available to new users ...
    use models/gemini-3.8-flash`. Not discoverable without actually
    calling the API - the SDK accepts any model-name string with no
    client-side validation.

13. **A naive fixed-schedule retry on 429/503 can hang for 30+ minutes.**
    First retry implementation used `2**attempt` backoff per attempt
    with no cap, inside a loop that itself ran up to `MAX_TOOL_ROUNDS` (8)
    times per `respond()` call. A quota-exhausted free tier's own 429
    response can suggest waiting up to ~60s *per attempt*; 8 rounds ×
    several attempts × up to 60s compounds past 30 minutes in the worst
    case - confirmed live: an early version of the agent was killed by the
    harness after running silently for the full 30-minute background
    limit with no output. Fixed by capping any single retry sleep at
    `MAX_RETRY_DELAY_SECONDS` (20s) regardless of what the server suggests.

14. **The free tier's real cap is 20 requests/*day* per model, not just
    5/minute.** A `GenerateRequestsPerMinutePerProjectPerModel-FreeTier`
    429 (5 RPM) was the first limit hit and looked like the whole story;
    a few calls later, a second, more specific
    `GenerateRequestsPerDayPerProjectPerModel-FreeTier` 429 appeared with
    `limit: 20` and `retryDelay: 81400s` (~22.6 hours). No per-minute
    backoff fixes a per-day cap. Fixed with cross-key rotation (decision
    9) once a 429's suggested delay exceeds `KEY_EXHAUSTED_THRESHOLD_SECONDS`
    (120s) - a short delay is treated as transient and retried on the same
    key, a long one triggers rotation instead of a long sleep.

## 10. Model rotation alongside key rotation, cheap model first

**Options considered:** Rotate only across API keys (one model, several
accounts); rotate only across models (one key, several models); rotate
across both, cheapest/highest-quota model first.

**Chosen:** Both. `MODEL_CANDIDATES = ("gemini-flash-lite-latest",
"gemini-3.8-flash")`, tried in that order on every key before moving to
the next key.

**Why:** A 429's `quotaId` names the model explicitly
(`GenerateRequestsPerDayPerProjectPerModel-FreeTier`), confirming quota is
tracked per (key, model) pair - a different model on the SAME key is a
genuinely separate daily budget, not a trick that merely feels like one.
Per ai.google.dev/gemini-api/docs/rate-limits, the lite tier's free RPD is
roughly 25x the full flash tier's (~500 vs ~20) - and this agent's actual
task (a handful of simple lookup/refund/email tool calls) doesn't need
frontier-level reasoning, so trying the cheap/high-quota model first
multiplies effective daily capacity for free, before ever touching a
second account.

**Cost:** One more thing to explain if asked "why does the agent sometimes
answer with a different model" - mitigated by the rotation logging a
clear line every time it switches. Output quality across the two models
wasn't A/B compared; for this agent's narrow task both produced correct
tool-calling behavior in testing.

---

## Real bugs found while building Milestone 2 (continued)

15. **The true root cause of the 30+ minute hangs wasn't retry logic at
    all - it was the complete absence of an HTTP request timeout.**
    `google.genai.types.HttpOptions.timeout` is `None` by default, and
    the SDK passes that straight through to httpx, where `None` means
    "wait forever," not "use a sane default." A stalled request (observed
    live, twice) blocked silently with zero output and zero exception for
    the full 30-minute harness limit, because nothing ever fired to
    interrupt it - every earlier "fix" to the retry *schedule* was
    correctly bounding a code path that was never the one hanging.
    Diagnosed by reading `_api_client.py`'s own `retry_args()`: with no
    `retry_options` set, the SDK's internal tenacity wrapper uses
    `stop_after_attempt(1)` (confirmed NOT the cause either - it doesn't
    retry internally by default). Fixed by setting
    `HttpOptions(timeout=30_000)` (milliseconds) explicitly on every
    client, and by running the synchronous `generate_content()` call via
    `asyncio.to_thread` so a stall can't also block the event loop.

16. **A free-tier key can be denied outright (403), independent of
    quota.** One of five personal accounts' keys returned
    `403 PERMISSION_DENIED: "Your project has been denied access. Please
    contact support."` - not a 429, not a 503, not fixable by any retry
    or rotation logic, and correctly NOT retried (403 isn't in
    `RETRYABLE_STATUS_CODES`). Likely Google's abuse detection on rapid
    multi-account free-tier key creation. No code fix exists for this -
    it's an account-level state only the account owner can resolve.

17. **The API-key loader's sequential scan silently missed keys that
    didn't fit the pattern it expected.** First version required
    `GEMINI_API_KEY`, then `GEMINI_API_KEY_2`, `_3`, ... with no gaps,
    stopping at the first missing index. A key added by hand arrived as
    `GEMINI_API_KEY5` with no `GEMINI_API_KEY`/`_2`/`_3`/`_4` ever set -
    the loader found zero keys and the agent failed with "no Gemini API
    key set" despite a real key being present in the environment. Fixed
    with a regex scan (`^GEMINI_API_KEY_?(\d*)$`) over all of
    `os.environ`, sorted by suffix, accepting any numbering gaps or
    spelling.
