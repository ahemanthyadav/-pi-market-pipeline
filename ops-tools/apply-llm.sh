#!/bin/bash
# apply-llm.sh — ship manifests/llm/narrative.py as ConfigMap llm-narrative-script and apply the
# llm-narrative CronJob (ML-7a); bakeoff.py rides in the same ConfigMap. Run after any change to either. Tests: tests/test_narrative.py.
set -euo pipefail
cd "$(dirname "$0")/.."
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"
python3 tests/test_narrative.py >/dev/null 2>&1 || { echo "tests/test_narrative.py fails" >&2; exit 1; }
kubectl -n market-data create configmap llm-narrative-script --from-file=narrative.py=manifests/llm/narrative.py \
  --from-file=bakeoff.py=manifests/llm/bakeoff.py \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f manifests/llm/cronjob.yaml
