"""SFTP-get a remote file to a local path (password auth). Mirror of putfile.py.

Usage:
    python3 ops-tools/getfile.py <host> <user> <remote> <local>   # host: pi0..pi3 | tx2 | raw IP

Used for pulling built image tarballs off the TX2. Password comes from the
gitignored `.secrets.env` via _creds.py (SSH_PASS in the environment overrides).
Host keys: pinned via .ssh_known_hosts when present (see _creds.host_key_policy).

Exit codes (match runcmd.py): 2 usage/no-password · 3 connect fail · 4 transfer fail.
"""
import sys

import paramiko

from _creds import host_key_policy, password_for, resolve_host


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: getfile.py <host> <user> <remote> <local>", file=sys.stderr)
        return 2
    host, user, remote, local = sys.argv[1:5]
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
        sftp.get(remote, local)
        sftp.close()
    except Exception as exc:  # noqa: BLE001
        print(f"GET FAIL {label}:{remote}: {exc}", file=sys.stderr)
        return 4
    finally:
        client.close()
    print(f"GOT {label}:{remote} -> {local}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
