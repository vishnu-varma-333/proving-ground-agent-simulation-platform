#!/usr/bin/env bash
# Verifies every backing service in the local stack is actually reachable and
# answering correctly, not just that its pod is Running. Exits non-zero on
# any failure so CI can gate on it.
set -uo pipefail

KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
NAMESPACE="proving-ground"
FAILURES=0

check() {
  local name="$1"
  shift
  local slug
  slug="$(echo "$name" | tr -c 'A-Za-z0-9' '_')"
  if "$@" >/tmp/pg-health-"$slug".log 2>&1; then
    echo "PASS  $name"
  else
    echo "FAIL  $name (see /tmp/pg-health-$slug.log)"
    FAILURES=$((FAILURES + 1))
  fi
}

check "postgres: pg_isready in-cluster" \
  "$KUBECTL_BIN" -n "$NAMESPACE" exec statefulset/postgres -- pg_isready -U proving_ground

check "postgres: SELECT 1 in-cluster" \
  "$KUBECTL_BIN" -n "$NAMESPACE" exec statefulset/postgres -- \
    psql -U proving_ground -d proving_ground -c "SELECT 1" -t -A

check "postgres: TCP reachable on host port 25432" \
  bash -c "echo > /dev/tcp/127.0.0.1/25432"

check "clickhouse: /ping over host port 28123" \
  bash -c 'test "$(curl -fsS http://127.0.0.1:28123/ping)" = "Ok."'

check "clickhouse: authenticated SELECT 1 over HTTP" \
  bash -c 'test "$(curl -fsS -u proving_ground:proving-ground-local-dev "http://127.0.0.1:28123/?query=SELECT%201")" = "1"'

check "nats: /healthz over host port 28222" \
  curl -fsS http://127.0.0.1:28222/healthz

check "nats: jetstream enabled (/jsz)" \
  bash -c 'curl -fsS http://127.0.0.1:28222/jsz | grep -q "\"config\""'

check "object storage: S3 gateway reachable on host port 29001" \
  bash -c "echo > /dev/tcp/127.0.0.1/29001"

check "object storage: filer UI reachable on host port 29002" \
  curl -fsS http://127.0.0.1:29002/

check "object storage: tapes/snapshots buckets exist" \
  bash -c "$KUBECTL_BIN -n $NAMESPACE logs job/object-storage-create-buckets | grep -q proving-ground-tapes"

check "prometheus: /-/ready over host port 29090" \
  curl -fsS http://127.0.0.1:29090/-/ready

check "grafana: /api/health over host port 23000" \
  curl -fsS http://127.0.0.1:23000/api/health

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "All checks passed."
  exit 0
else
  echo "$FAILURES check(s) failed."
  exit 1
fi
