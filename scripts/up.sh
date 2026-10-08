#!/usr/bin/env bash
# Brings up the local Proving Ground infrastructure: a kind cluster running
# PostgreSQL, ClickHouse, NATS JetStream, object storage, Prometheus and
# Grafana.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="proving-ground"
KIND_BIN="${KIND_BIN:-kind}"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
DOCKER_BIN="${DOCKER_BIN:-docker}"

# kind nodes keep their own containerd image store, separate from the host
# Docker daemon's, and `kind delete cluster` throws that store away - so a
# from-scratch bring-up normally re-pulls every image from Docker Hub every
# time (measured: see docs/BENCHMARKS.md). `kind load docker-image` is the
# usual fix but reliably fails on this host: Docker Desktop's
# containerd-snapshotter image store makes it error with "ctr: content
# digest ... not found" (a known kind limitation, confirmed by testing both
# `kind load docker-image` and the `docker save | kind load image-archive`
# variant - both fail the same way). The durable fix is kind's own
# documented pattern: a local pull-through registry cache that kind's
# containerd reads through on every pull, so only the very first pull of
# each image ever touches Docker Hub.
MIRROR_NAME="kind-registry-mirror"
MIRROR_PORT="5001"

if [ "$("$DOCKER_BIN" inspect -f '{{.State.Running}}' "$MIRROR_NAME" 2>/dev/null || true)" != "true" ]; then
  if "$DOCKER_BIN" ps -aq -f "name=^${MIRROR_NAME}$" | grep -q .; then
    echo "Starting existing pull-through registry mirror container..."
    "$DOCKER_BIN" start "$MIRROR_NAME" >/dev/null
  else
    echo "Creating pull-through registry mirror for docker.io..."
    "$DOCKER_BIN" run -d --restart=always \
      -p "127.0.0.1:${MIRROR_PORT}:5000" \
      --name "$MIRROR_NAME" \
      -e REGISTRY_PROXY_REMOTEURL=https://registry-1.docker.io \
      registry:2 >/dev/null
  fi
fi

if "$KIND_BIN" get clusters | grep -qx "$CLUSTER_NAME"; then
  echo "kind cluster '$CLUSTER_NAME' already exists, reusing it."
else
  echo "Creating kind cluster '$CLUSTER_NAME'..."
  "$KIND_BIN" create cluster --config "$ROOT_DIR/infra/kind/cluster-config.yaml"
fi

if ! "$DOCKER_BIN" network inspect kind --format '{{range .Containers}}{{.Name}} {{end}}' | grep -qw "$MIRROR_NAME"; then
  echo "Connecting registry mirror to the kind network..."
  "$DOCKER_BIN" network connect kind "$MIRROR_NAME"
fi

"$KUBECTL_BIN" config use-context "kind-$CLUSTER_NAME"

echo "Applying base services (Postgres, ClickHouse, NATS, object storage)..."
"$KUBECTL_BIN" apply -k "$ROOT_DIR/infra/k8s/local/base"

echo "Applying observability stack (Prometheus, Grafana)..."
"$KUBECTL_BIN" apply -k "$ROOT_DIR/infra/k8s/local/observability"

echo "Waiting for StatefulSets to roll out..."
"$KUBECTL_BIN" -n proving-ground rollout status statefulset/postgres --timeout=180s
"$KUBECTL_BIN" -n proving-ground rollout status statefulset/clickhouse --timeout=180s
"$KUBECTL_BIN" -n proving-ground rollout status statefulset/nats --timeout=180s
"$KUBECTL_BIN" -n proving-ground rollout status statefulset/object-storage --timeout=180s

echo "Waiting for Deployments to roll out..."
"$KUBECTL_BIN" -n proving-ground rollout status deployment/prometheus --timeout=120s
"$KUBECTL_BIN" -n proving-ground rollout status deployment/grafana --timeout=120s

echo "Waiting for object storage bucket bootstrap job..."
"$KUBECTL_BIN" -n proving-ground wait --for=condition=complete job/object-storage-create-buckets --timeout=120s

cat <<'EOF'

Proving Ground local stack is up. Host ports:
  PostgreSQL          localhost:25432  (user: proving_ground / db: proving_ground)
  ClickHouse HTTP     localhost:28123
  ClickHouse native   localhost:29000
  NATS client         localhost:24222
  NATS monitoring     http://localhost:28222
  Object storage (S3) http://localhost:29001  (SeaweedFS S3 gateway - see DECISIONS.md)
  Object storage filer http://localhost:29002
  Prometheus          http://localhost:29090
  Grafana             http://localhost:23000  (admin / see infra/k8s/local/observability/grafana.yaml)

Run scripts/health-check.sh to verify every service is reachable and answering.
EOF
