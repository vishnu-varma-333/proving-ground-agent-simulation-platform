#!/usr/bin/env bash
# Brings up the local Proving Ground infrastructure: a kind cluster running
# PostgreSQL, ClickHouse, NATS JetStream, MinIO, Prometheus and Grafana.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="proving-ground"
KIND_BIN="${KIND_BIN:-kind}"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"

if "$KIND_BIN" get clusters | grep -qx "$CLUSTER_NAME"; then
  echo "kind cluster '$CLUSTER_NAME' already exists, reusing it."
else
  echo "Creating kind cluster '$CLUSTER_NAME'..."
  "$KIND_BIN" create cluster --config "$ROOT_DIR/infra/kind/cluster-config.yaml"
fi

"$KUBECTL_BIN" config use-context "kind-$CLUSTER_NAME"

echo "Applying base services (Postgres, ClickHouse, NATS, MinIO)..."
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
