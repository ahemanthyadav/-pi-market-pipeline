# 0007. Sentiment scoring runs on CPU (FinBERT), not the TX2 GPU

- Date: 2026-09-30 (recorded 2026-10-04)
- Status: accepted

## Context
The TX2 is the cluster's only GPU node — but its stack is JetPack 4.6.1 /
CUDA 10.2 / Pascal (sm_62): modern PyTorch cannot use this GPU at all (only
old L4T-era wheels or TensorRT 8.2 ONNX). Daily load is a few hundred
headlines. Options: (a) GPU via old-stack containers — heavy images, fragile
era-locked stack, for minutes of weekly work; (b) CPU inference with modern
torch (2.14 aarch64) on the TX2; (c) GPU on the RTX 3090 box — off-cluster,
needs WoL orchestration for a nightly cron.

## Decision
Option (b): FinBERT on CPU inside the TX2-only CronJob (4 Gi window, off the
DB's 2 Gi). The GPU passthrough stack is proven (RuntimeClass + smoke test) and
reserved for experiments / TensorRT candidates.

## Consequences
- Simple, reproducible, modern toolchain; GPU stays idle (0% measured) as
  headroom rather than a maintenance liability.
- Anything needing modern CUDA or large models belongs on the RTX 3090 layer
  (roadmap Tier 3), never the TX2.
- Revisit only alongside a JetPack 5 reflash (which would lift the CUDA 10.2
  ceiling entirely — its own ADR if ever attempted).
