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
