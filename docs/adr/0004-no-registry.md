# 0004. No container registry — TX2-native builds distributed as tarballs

- Date: 2026-09-30 (practiced since first fetcher; recorded 2026-10-04)
- Status: accepted

## Context
Homelab behind CGNAT: no inbound ports, no external DNS, so no reachable private
registry; ARM64 workers + one aarch64 build host (the TX2) make native builds
trivial. Options: (a) public registry (exposes homelab images, needs accounts);
(b) self-hosted registry behind Tailscale (another always-on service on RAM-starved
Pis); (c) build natively on the TX2, `docker save | gzip`, SFTP tarball to each Pi,
`k3s ctr -n k8s.io images import`, `imagePullPolicy: Never`.

## Decision
Option (c): no registry by design. Builds happen on the TX2 (docker data-root on
sda4 since 2026-10-03); tarballs distribute via `ops-tools/` paramiko helpers;
pods use `imagePullPolicy: Never` so a missing image fails loudly
(ErrImageNeverPull) instead of pulling garbage.

## Consequences
- Every code change = full cycle: edit → bump tag → build → save → distribute to
  pi1/pi2/pi3 (pi2's import detached) → **`kubectl apply` (a sed'd file is not a
  deploy — find F28)** → canary-validate. Codified in the `/rebuild` command and
  the canary-validate skill.
- Images are single-tag (`local/<name>:vN`); no image GC — prune TX2 docker
  cruft when eMMC/disk pressure warrants.
- Revisit if the cluster grows beyond 3 schedulable workers or builds outpace
  distribution patience (a lazy-registry behind Tailscale is the fallback).
