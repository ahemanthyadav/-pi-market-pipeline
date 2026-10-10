---
name: Node Power & Health Check
description: Use when checking whether cluster nodes are healthy, when a Pi is wedging, undervolting, or throttling, or after ANY PSU/cable/adapter/hardware change — the per-node check battery, throttle-hex decoding, the wedge signature, and the identity-free swap-test ladder for power faults. Paid for by the 2026-10-09→10 outage (16 h control-plane wedge, root cause = undervolting PSU; pending-tasks §1, ADR 0011).
---

# Node power & health check

Two jobs: (a) the fast fleet health battery, (b) undervolt/power-fault triage
when a node misbehaves. Use node aliases, never raw IPs; sudo via the `@@PW@@`
token only (AGENTS.md rules 7–8).

## 1. The check battery

Per Pi (users `pi0..pi3`; TX2 user `ahytx2`, no `vcgencmd` there):

```bash
python3 ops-tools/runcmd.py pi1 pi1 '
  echo "uptime: $(uptime -p)  load: $(cut -d" " -f1-3 /proc/loadavg)";
  echo "throttled: $(vcgencmd get_throttled)  temp: $(vcgencmd measure_temp)";
  echo "k3s-agent: $(systemctl is-active k3s-agent)";
  echo "uv events: $(echo @@PW@@ | sudo -S dmesg 2>/dev/null | grep -icE "under.?volt")";
  free -m | sed -n 2p; tail -2 /var/log/node-stats/stats.csv'
```

Cluster-wide:

```bash
kubectl get nodes                      # all Ready; pi2 shows SchedulingDisabled (keep it)
kubectl get pods -A | grep -Ev "Running|Completed"   # the exceptions list IS the story
```

Intended state per node: pi0 `pihole-FTL`+`unbound` active (DNS is the
fleet's egress dependency — a down pi0 crash-loops the telegram bot via DNS
resolution); pi2 `k3s` (server) active, **cordoned**, load < 2; workers
`k3s-agent` active; TX2 root disk < 85% (prune docker at 85, ops manual §7).

## 2. Reading the throttle hex

| Bit | Meaning |
|-----|---------|
| `0x1` | under-voltage **now** |
| `0x2` | arm freq capped now |
| `0x4` | throttled **now** |
| `0x8` | soft temp limit now (Pi 3 B+: >60 °C) — thermal, NOT voltage |
| `0x10000` | under-voltage has occurred (this boot) |
| `0x40000` | throttling has occurred |
| `0x80000` | soft-temp has occurred |

- Past bits clear at reboot → **past uv bits on a fresh boot mean it sagged
  since that boot**. Count and timestamp `dmesg` events (`grep -icE
  "under.?volt"`) to separate boot-burst sags (seconds 20–40, SSD spin-up +
  k3s start) from sustained-load sags (minutes 6+, load falling).
- `0x50000`-style (past-only, no live bits) = watch; `0x50005`-style (live
  `0x1`) = replace that supply now.
- **A single idle reading proves nothing.** The 16 h wedge showed `0x0`-clean
  at idle and `0xd0005` under load an hour later. Verify under load; trust
  the 5-min `stats.csv` trend (ADR 0011), not one sample.

## 3. The wedge signature

Ping answers, TCP 22/6443 **open**, but SSH sessions won't establish
("No existing session") and kubectl stalls at TLS handshake = a starved box
(memory/CPU), not a network fault. Do NOT restart things into it — §8
cool-down first, `cluster-mutation` skill for anything touching k3s.

## 4. Undervolt triage — swap-test ladder

Bisect with **identity-free components only**. Never swap boot SSDs between
nodes to chase a power fault: hostname, static IP, k3s certs and cluster state
travel with the disk — that's an identity swap, and it takes down the
control-plane mid-recovery.

Ladder, in order (each step = one reboot pair, ~10 min):
1. **PSU + its cable** ↔ a healthy identical node (pi3 ↔ pi1 class). Fault
   follows the supply → convicted (2026-10-10: pi3 sagged live at load <1
   within a minute of getting pi2's PSU — case closed). Cable included: a
   thin micro-USB lead drops 0.2–0.3 V on its own.
2. **USB-SATA adapter** ↔ same. The SSD rides the Pi's 5 V rail through it.
3. **Board** — last resort, least likely.

Specs sidebar: Pi 3 B+ wants **5.1 V / ≥2.5 A before the SSD's share**; buy
5.1 V 3 A. Firmware browns out ≈4.65 V. "5 V" phone chargers sag to 4.8–4.9 V
under load — three different chargers all failed on pi2 while identical
SSD+adapter hardware ran clean on pi3 for days. A powered USB hub takes the
SSD off the Pi's rail entirely if adapters keep eating supplies.

Fleet theme: supplies fail as a class — when one is convicted, check the
others via the stats logger (`throttle_hex` column) before assuming one bad
unit. pi0's chronic `0x50000` and pi1's accumulating events are the same
disease at lower stakes.

## 5. Protecting the cluster while power is bad

- Don't trigger load bursts (TX2 return, DB reschedule, backlog drain) onto a
  control-plane showing **live** uv — that burst is the wedge trigger.
- Emergency brake if pi2's load keeps climbing: re-suspend the CronJobs —
  `kubectl -n market-data patch cronjob --all -p '{"spec":{"suspend":true}}'`
  — reversible, same catchup-storm brake as the outage protocol.
- Worker on a sagging rail = corruption risk for whatever it writes
  (pi3 hosts the pg-backup hostPath) → `kubectl cordon <node>` until the
  supply is replaced.
- Control-plane stays cordoned, permanently:
  `kubectl taint node pi2 workload=true:NoSchedule`.

## Anti-patterns (all happened, 2026-10-10)

- Trying random phone chargers instead of bisecting — 2 A and 2.4 A both
  failed; the swap test found the answer in 10 minutes.
- Trusting one clean idle reading (three separate times).
- Proposing an SSD swap to isolate a power fault.
- Restarting agents while the control-plane still showed live undervolt.

## Record it

Pull the `stats.csv` trend as evidence, note verdicts in the ops manual /
pending-tasks in the same session, and verify any PSU replacement by watching
`throttle_hex` stay clean under load for a day — idle-clean is not proof.
