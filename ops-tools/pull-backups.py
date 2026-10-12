"""Pull the newest verified pg-backup dumps from pi3 to a second location, checksummed, and check freshness.

Usage:
    python3 ops-tools/pull-backups.py [--dest out/backups] [--keep 2] [--max-age-hours 36]

A "verified" dump is one with a `.sha256` sidecar written by the (AR-11) pg-backup job, which only publishes a
dump after `pg_restore -l` and size checks. For each of the newest --keep dumps: skip if the local copy already
matches the sidecar hash, otherwise download to a temp name, verify the sha256, then rename. Never deletes anything.

Exit codes: 0 ok · 2 newest verified dump older than --max-age-hours (staleness alert) · 3 checksum mismatch ·
4 no verified dump found. Password comes from the gitignored .secrets.env via _creds.py (never on a command line).
Cron-able from the workstation or pi0 — the sidecar hash is the integrity check, the exit code is the alert.
"""
import argparse
import hashlib
import os
import sys
import time

import paramiko

from _creds import password_for, resolve_host

HOST, USER, REMOTE_DIR = "pi3", "pi3", "/var/lib/market-data/backups"


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="out/backups")
    ap.add_argument("--keep", type=int, default=2)
    ap.add_argument("--max-age-hours", type=float, default=36)
    a = ap.parse_args()
    os.makedirs(a.dest, exist_ok=True)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(resolve_host(HOST), username=USER, password=password_for(HOST, USER), timeout=15)
    sftp = client.open_sftp()
    attrs = {e.filename: e for e in sftp.listdir_attr(REMOTE_DIR)}
    verified = sorted((n for n in attrs if n.startswith("marketdata-") and n.endswith(".dump")
                       and n + ".sha256" in attrs and attrs[n].st_size > 0),
                      key=lambda n: attrs[n].st_mtime, reverse=True)
    if not verified:
        print("NO-VERIFIED-DUMP on pi3")
        return 4
    rc = 0
    newest_age_h = (time.time() - attrs[verified[0]].st_mtime) / 3600
    for name in verified[:a.keep]:
        with sftp.open(f"{REMOTE_DIR}/{name}.sha256") as f:
            want = f.read().decode().split()[0]
        local = os.path.join(a.dest, name)
        if os.path.exists(local) and sha256_of(local) == want:
            print(f"have  {name}  sha256 ok")
            continue
        tmp = local + ".part"
        sftp.get(f"{REMOTE_DIR}/{name}", tmp)
        got = sha256_of(tmp)
        if got != want:
            os.remove(tmp)
            print(f"MISMATCH {name}: downloaded {got[:12]} != sidecar {want[:12]} (removed)")
            rc = 3
            continue
        os.replace(tmp, local)
        with open(local + ".sha256", "w") as f:
            f.write(f"{want}  {name}\n")
        print(f"pulled {name}  {os.path.getsize(local) / 1e6:.0f} MB  sha256 ok")
    sftp.close()
    client.close()
    print(f"newest verified dump: {verified[0]} ({newest_age_h:.1f} h old, limit {a.max_age_hours:g} h)")
    if newest_age_h > a.max_age_hours:
        print("STALE: newest verified dump is older than the limit")
        return rc or 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
