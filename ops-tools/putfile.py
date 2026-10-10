"""SFTP-put a local file to a homelab host (password auth). No sudo needed locally.

Usage:
    python3 ops-tools/putfile.py <host> <user> <local> <remote>   # host: pi0..pi3 | tx2 | raw IP

Companion to runcmd.py / getfile.py. Used for shipping build contexts and
image tarballs to TX2/Pis. Password comes from the gitignored `.secrets.env`
via _creds.py (SSH_PASS in the environment overrides).
"""
import paramiko
import sys

from _creds import password_for, resolve_host

host, user, local, remote = sys.argv[1:5]
pw = password_for(host, user)
label = host            # print the alias, not the resolved address
host = resolve_host(host)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pw, timeout=15)
sftp = client.open_sftp()
sftp.put(local, remote)
sftp.close()
client.close()
print(f"PUT {local} -> {label}:{remote}")
