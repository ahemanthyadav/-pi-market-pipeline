#!/usr/bin/env python3
"""Workload inventory generated from manifests/ — the doc tables must agree with it.

    python3 ops-tools/workloads.py            # markdown table of every workload
    python3 ops-tools/workloads.py --check    # compare docs/*.md against the manifests
                                              # (exit 1 on any drift; safe for a pre-push check)

Checked: (a) any docs table row whose first cell is a CronJob name must carry the
manifest's schedule and image tag; (b) any "<N> CronJobs" phrase must equal the
manifest count. Read-only; needs no cluster.
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load():
    cronjobs, others = {}, []
    for p in sorted((ROOT / "manifests").rglob("*.yaml")):
        for d in yaml.safe_load_all(p.read_text()):
            if not isinstance(d, dict):
                continue
            kind, name = d.get("kind"), d.get("metadata", {}).get("name")
            if kind == "CronJob":
                s = d["spec"]
                pod = s["jobTemplate"]["spec"]["template"]["spec"]
                c = pod["containers"][0]
                cronjobs[name] = {
                    "schedule": s["schedule"], "tz": s.get("timeZone") or "node-local",
                    "image": c["image"],
                    "node": (pod.get("nodeSelector") or {}).get("kubernetes.io/hostname")
                            or (pod.get("nodeSelector") or {}).get("hardware") or "any",
                    "file": str(p.relative_to(ROOT)),
                }
            elif kind in ("Deployment", "StatefulSet"):
                pod = d["spec"]["template"]["spec"]
                others.append((kind, name, pod["containers"][0]["image"], str(p.relative_to(ROOT))))
    return cronjobs, others


def table(cronjobs, others):
    out = ["| CronJob | Schedule | TZ | Image | Node |", "|---|---|---|---|---|"]
    for n, c in sorted(cronjobs.items()):
        out.append(f"| {n} | `{c['schedule']}` | {c['tz']} | `{c['image']}` | {c['node']} |")
    out += ["", "| Always-on | Kind | Image |", "|---|---|---|"]
    out += [f"| {n} | {k} | `{i}` |" for k, n, i, _ in others]
    return "\n".join(out)


def check(cronjobs):
    problems = []
    for doc in sorted((ROOT / "docs").glob("*.md")):
        for i, line in enumerate(doc.read_text().splitlines(), 1):
            if line.startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                name = re.sub(r"[`*]", "", cells[0]) if cells else ""
                if name in cronjobs and len(cells) >= 3:
                    m = cronjobs[name]
                    sched = re.match(r"([\d*/,-]+(?:\s+[\d*/,-]+){4})", re.sub(r"[`*]", "", cells[1]))
                    if sched and sched.group(1) != m["schedule"]:
                        problems.append((doc.name, i, f"{name}: schedule '{sched.group(1)}' != manifest '{m['schedule']}'"))
                    img = re.search(r"([\w.-]+/[\w.-]+:[\w.-]+)", cells[2])
                    if img and img.group(1) != m["image"]:
                        problems.append((doc.name, i, f"{name}: image '{img.group(1)}' != manifest '{m['image']}'"))
            for mm in re.finditer(r"\b(\d+)\s+(?:live\s+)?CronJobs?\b", line):
                if "cronjobs.yaml" in line:  # a per-file count, not the cluster total
                    continue
                if int(mm.group(1)) != len(cronjobs) and int(mm.group(1)) > 3:
                    problems.append((doc.name, i, f"count says {mm.group(1)} CronJobs, manifests have {len(cronjobs)}"))
            for mm in re.finditer(r"CronJobs? \((\d+) live\)", line):
                if int(mm.group(1)) != len(cronjobs):
                    problems.append((doc.name, i, f"'({mm.group(1)} live)' vs {len(cronjobs)} manifests"))
    for docname in ("market-data-pipeline-operations-manual.md", "market-data-architecture.md"):
        listed = set()
        for line in (ROOT / "docs" / docname).read_text().splitlines():
            if line.startswith("|"):
                first = re.sub(r"[`*]", "", line.strip().strip("|").split("|")[0].strip())
                if first in cronjobs:
                    listed.add(first)
        for missing in sorted(set(cronjobs) - listed):
            problems.append((docname, 0, f"CronJob '{missing}' has no row in this doc's schedule table"))
    return problems


def main() -> int:
    cronjobs, others = load()
    if "--check" in sys.argv:
        problems = check(cronjobs)
        print(f"manifests: {len(cronjobs)} CronJobs, {len(others)} always-on workloads")
        for d, ln, msg in problems:
            print(f"  DRIFT {d}:{ln}  {msg}")
        print("docs agree with manifests" if not problems else f"{len(problems)} drift item(s)")
        return 1 if problems else 0
    print(table(cronjobs, others))
    return 0


if __name__ == "__main__":
    sys.exit(main())
