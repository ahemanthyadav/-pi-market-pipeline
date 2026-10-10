#!/bin/bash
# apply-grafana-provisioning.sh — apply manifests/grafana/provisioning.yaml with the
# Telegram chat id rendered in from the live cluster Secret.
#
# The tracked manifest carries the placeholder __TELEGRAM_CHAT_ID__ so no personal
# id lives in git (finds F29: Grafana needs the id as a literal in the file).
# This script reads it from Secret `telegram-bot` (key chat-id) and pipes the
# rendered manifest straight to kubectl — the id is never written to disk.
#
# Usage (after the cluster-mutation pre-flight; then wait ~60 s before deleting
# the Grafana pod — finds F32):
#   bash ops-tools/apply-grafana-provisioning.sh            # apply
#   bash ops-tools/apply-grafana-provisioning.sh --dry-run  # render + validate only
set -euo pipefail
cd "$(dirname "$0")/.."
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"
MANIFEST=manifests/grafana/provisioning.yaml

CHAT_ID="$(kubectl -n market-data get secret telegram-bot -o jsonpath='{.data.chat-id}' | base64 -d)"
if ! [[ "$CHAT_ID" =~ ^-?[0-9]+$ ]]; then
  echo "chat-id in Secret telegram-bot missing or not numeric — refusing to apply" >&2
  exit 1
fi

RENDERED="$(sed "s/__TELEGRAM_CHAT_ID__/$CHAT_ID/" "$MANIFEST")"
if grep -q "__TELEGRAM_CHAT_ID__" <<<"$RENDERED"; then
  echo "placeholder still present after render — refusing to apply" >&2
  exit 1
fi

if [ "${1:-}" = "--dry-run" ]; then
  kubectl apply --dry-run=server -f - <<<"$RENDERED"
else
  kubectl apply -f - <<<"$RENDERED"
fi
