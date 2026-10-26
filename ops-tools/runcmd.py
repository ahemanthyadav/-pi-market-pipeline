"""Run a command on a homelab host via paramiko (password auth). No sudo needed locally.

Usage:
    python3 ops-tools/runcmd.py <host> <user> '<command>'
    # <host> is an alias (pi0 pi1 pi2 pi3 tx2, resolved from the gitignored .hosts.env)
    # or a raw IP. sudo on the remote: use the @@PW@@ token, e.g.
    python3 ops-tools/runcmd.py pi2 pi2 'echo @@PW@@ | sudo -S systemctl status k3s'
    # any @@KEY@@ from .secrets.env also expands (shell-quoted), e.g.
    #   @@TELEGRAM_BOT_TOKEN@@ / @@TELEGRAM_CHAT_ID@@ for a channel sanity check

Notes:
- Passwords come from the gitignored `.secrets.env` (PI_PASS / TX2_PASS, picked by
  host) via _creds.py; SSH_PASS in the environment overrides. Never put a
  password on the command line or in a doc.
- Long commands (>~120s of no output, e.g. big untars) hit the exec timeout
  (reported as TIMEOUT, rc 5): launch those detached with nohup and poll instead.
- Host keys: pinned against the gitignored .ssh_known_hosts when it exists
  (ssh-keyscan each host once); otherwise auto-accepted (homelab LAN).
- stdout is drained before stderr on one channel; a command spewing many MB of
  stderr while stdout is still open can stall into the timeout — redirect 2>&1
  remotely for such commands.

Exit codes: 2 usage/no-password · 3 connect fail · 4 remote rc!=0 · 5 timeout.
"""
import socket
import sys

import paramiko

from _creds import expand, host_key_policy, password_for, resolve_host


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: runcmd.py <host> <user> <command>", file=sys.stderr)
        return 2
    host, user, cmd = sys.argv[1], sys.argv[2], sys.argv[3]
    pw = password_for(host, user)
    if not pw:
        print("no password found: fill PI_PASS/TX2_PASS in .secrets.env", file=sys.stderr)
        return 2
    cmd = expand(cmd, pw)
    host = resolve_host(host)
    client = paramiko.SSHClient()
    host_key_policy(client)
    try:
        # 30s auth/banner timeouts: pi2's PAM auth under load can exceed 10s,
        # which paramiko aborts as a generic "Authentication failed" —
        # misdiagnosed as a wrong password for an hour on 2026-10-09 (the
        # server journal showed ZERO "Failed password" events). Real wrong
        # passwords still fail instantly; only the slow-server case changes.
        client.connect(host, username=user, password=pw, timeout=30,
                       banner_timeout=30, auth_timeout=30)
    except Exception as exc:  # noqa: BLE001 - report and exit nonzero
        print(f"CONNECT FAIL {host}: {exc}", file=sys.stderr)
        return 3
    try:
        _, stdout, stderr = client.exec_command(cmd, timeout=120)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        rc = stdout.channel.recv_exit_status()
    except socket.timeout:
        print("TIMEOUT: no channel data for 120s — long commands: launch with "
              "nohup and poll (see docstring)", file=sys.stderr)
        return 5
    finally:
        client.close()
    print(out, end="")
    if err:
        print(f"[stderr] {err}", file=sys.stderr, end="")
    print(f"[rc={rc}]", file=sys.stderr)
    return 0 if rc == 0 else 4


if __name__ == "__main__":
    sys.exit(main())
