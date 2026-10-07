#!/usr/bin/env bash
# Tears down the local Proving Ground kind cluster entirely.
set -euo pipefail

CLUSTER_NAME="proving-ground"
KIND_BIN="${KIND_BIN:-kind}"

if "$KIND_BIN" get clusters | grep -qx "$CLUSTER_NAME"; then
  "$KIND_BIN" delete cluster --name "$CLUSTER_NAME"
  echo "Deleted kind cluster '$CLUSTER_NAME'."
else
  echo "No kind cluster named '$CLUSTER_NAME' found; nothing to do."
fi
