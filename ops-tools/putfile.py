"""SFTP-put a local file to a homelab host (password auth). No sudo needed locally.

Usage:
    python3 ops-tools/putfile.py <host> <user> <local> <remote>   # host: pi0..pi3 | tx2 | raw IP

Companion to runcmd.py / getfile.py. Used for shipping build contexts and
image tarballs to TX2/Pis. Password comes from the gitignored `.secrets.env`
via _creds.py (SSH_PASS in the environment overrides).
Host keys: pinned via .ssh_known_hosts when present (see _creds.host_key_policy).

Exit codes (match runcmd.py): 2 usage/no-password · 3 connect fail · 4 transfer fail.
"""
import sys

import paramiko

from _creds import host_key_policy, password_for, resolve_host


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: putfile.py <host> <user> <local> <remote>", file=sys.stderr)
        return 2
    host, user, local, remote = sys.argv[1:5]
    pw = password_for(host, user)
    if not pw:
        print("no password found: fill PI_PASS/TX2_PASS in .secrets.env", file=sys.stderr)
        return 2
    label = host            # print the alias, not the resolved address
    host = resolve_host(host)
    client = paramiko.SSHClient()
    host_key_policy(client)
    try:
        client.connect(host, username=user, password=pw, timeout=15)
    except Exception as exc:  # noqa: BLE001 - report and exit nonzero
        print(f"CONNECT FAIL {label}: {exc}", file=sys.stderr)
        return 3
    try:
        sftp = client.open_sftp()
        sftp.put(local, remote)
        sftp.close()
    except Exception as exc:  # noqa: BLE001
        print(f"PUT FAIL {local} -> {label}:{remote}: {exc}", file=sys.stderr)
        return 4
    finally:
        client.close()
    print(f"PUT {local} -> {label}:{remote}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
