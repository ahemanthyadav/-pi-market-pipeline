"""SFTP-get a remote file to a local path (password auth). Mirror of putfile.py.

Usage:
    python3 ops-tools/getfile.py <host> <user> <remote> <local>   # host: pi0..pi3 | tx2 | raw IP

Used for pulling built image tarballs off the TX2. Password comes from the
gitignored `.secrets.env` via _creds.py (SSH_PASS in the environment overrides).
"""
import paramiko
import sys

from _creds import password_for, resolve_host

host, user, remote, local = sys.argv[1:5]
pw = password_for(host, user)
label = host            # print the alias, not the resolved address
host = resolve_host(host)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pw, timeout=15)
sftp = client.open_sftp()
sftp.get(remote, local)
sftp.close()
client.close()
print(f"GOT {label}:{remote} -> {local}")
