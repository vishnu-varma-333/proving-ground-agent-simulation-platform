#!/usr/bin/env bash
# Deploys the Milestone 6 platform pieces (metrics exporter + the worker
# ScaledJob) on top of the Milestone 1 base infra. Requires scripts/up.sh
# to have already run, KEDA installed (see docs/MILESTONES.md), and the
# worker image already built+pushed to localhost:5002/pg-worker:dev.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
NAMESPACE="proving-ground"

if [ ! -f "$ROOT_DIR/.env.local" ]; then
  echo "error: .env.local not found - need GEMINI_API_KEY* to create the worker-api-keys Secret" >&2
  exit 1
fi

echo "Creating worker-api-keys Secret from .env.local (not committed)..."
# shellcheck disable=SC2046
"$KUBECTL_BIN" -n "$NAMESPACE" create secret generic worker-api-keys \
  $(grep -E '^GEMINI_API_KEY' "$ROOT_DIR/.env.local" | sed -E 's/^([A-Z_0-9]+)=(.*)$/--from-literal=\1=\2/') \
  --dry-run=client -o yaml | "$KUBECTL_BIN" apply -f -

echo "Applying metrics exporter and worker ScaledJob..."
"$KUBECTL_BIN" apply -k "$ROOT_DIR/infra/k8s/local/platform"

echo "Waiting for metrics exporter to be ready..."
"$KUBECTL_BIN" -n "$NAMESPACE" rollout status deployment/metrics-exporter --timeout=60s

echo "Platform deployed. Check KEDA's scaling decisions with:"
echo "  kubectl -n $NAMESPACE get scaledjob pg-worker"
echo "  kubectl -n $NAMESPACE get jobs -w"
