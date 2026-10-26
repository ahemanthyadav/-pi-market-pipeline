"""Credential + host lookup for ops-tools — nothing sensitive in args, docs or tracked files.

Passwords (resolution order):
  1. SSH_PASS environment variable (explicit override)
  2. <repo>/.secrets.env (gitignored, mode 600), host-aware:
       TX2 (alias tx2 / its IPs / ahytx2-desktop / user ahytx2) -> TX2_PASS
       everything else (the Pis)                               -> PI_PASS

Hosts: tools accept the aliases pi0 pi1 pi2 pi3 tx2, resolved from the gitignored
<repo>/.hosts.env (PI0_IP … TX2_IP). A raw IP still works.

Remote commands may contain tokens: @@PW@@ is replaced by the shell-quoted host
password (e.g. 'echo @@PW@@ | sudo -S systemctl restart k3s-agent'); any other
@@KEY@@ present in .secrets.env is replaced by its shell-quoted value (e.g.
@@TELEGRAM_BOT_TOKEN@@ for a getMe/sendMessage channel check, run via runcmd).
Unknown tokens are left literal with a stderr warning — a typo'd key must be
visible, not silently shipped to a host as text.
"""
import os
import re
import shlex
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".secrets.env"
HOSTS_FILE = REPO / ".hosts.env"
KNOWN_HOSTS = REPO / ".ssh_known_hosts"
ALIASES = {"pi0": "PI0_IP", "pi1": "PI1_IP", "pi2": "PI2_IP", "pi3": "PI3_IP", "tx2": "TX2_IP"}

_truncation_warned: set = set()


def _load(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            try:
                parts = shlex.split(val)
            except ValueError:
                parts = [val]
            out[key.strip()] = parts[0] if parts else ""
            # An unquoted value with spaces silently became its first word — the
            # symptom is a baffling auth failure, so say it once, loudly.
            if len(parts) > 1 and (path.name, key.strip()) not in _truncation_warned:
                _truncation_warned.add((path.name, key.strip()))
                print(f"WARN: {key.strip()} in {path.name} has unquoted whitespace — "
                      "using only the first word; quote the value if that is wrong",
                      file=sys.stderr)
    return out


def host_key_policy(client) -> None:
    """Pin SSH host keys when <repo>/.ssh_known_hosts exists (gitignored; create it
    once with `ssh-keyscan <each-ip> >> .ssh_known_hosts`): unknown or changed keys
    are then rejected instead of auto-accepted — password auth on a LAN deserves
    that. Without the file, fall back to auto-accept (previous behavior)."""
    import paramiko
    if KNOWN_HOSTS.exists():
        client.load_host_keys(str(KNOWN_HOSTS))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())


def resolve_host(host: str) -> str:
    key = ALIASES.get(host.lower())
    if key:
        ip = _load(HOSTS_FILE).get(key, "")
        if not ip:
            raise SystemExit(f"alias '{host}' not found: set {key} in .hosts.env")
        return ip
    return host


def _is_tx2(host: str, user: str) -> bool:
    if user == "ahytx2" or host.lower() in {"tx2", "ahytx2-desktop"}:
        return True
    hosts = _load(HOSTS_FILE)
    return host in {hosts.get("TX2_IP"), hosts.get("TX2_TS_IP")} - {None, ""}


def password_for(host: str, user: str) -> str:
    if os.environ.get("SSH_PASS"):
        return os.environ["SSH_PASS"]
    key = "TX2_PASS" if _is_tx2(host, user) else "PI_PASS"
    return _load(ENV_FILE).get(key, "")


TOKEN_RE = re.compile(r"@@([A-Za-z0-9_]+)@@")


def expand(cmd: str, pw: str) -> str:
    """Substitute @@PW@@ and any @@KEY@@ found in .secrets.env, shell-quoted."""
    secrets = _load(ENV_FILE)
    warned: set[str] = set()

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key == "PW":
            return shlex.quote(pw)
        if key in secrets:
            return shlex.quote(secrets[key])
        if key not in warned:
            warned.add(key)
            print(f"WARN: @@{key}@@ not found in .secrets.env — left literal", file=sys.stderr)
        return m.group(0)

    return TOKEN_RE.sub(_sub, cmd)
