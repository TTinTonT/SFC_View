#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Upload scan_tray_bmc_arp_ssh.sh to the Sunnyvale DHCP / ETF SV host only.

Uses ROOMS["etf_sv"] from config (default host 10.24.10.190, same user/pass/script
paths as ETF San José unless ETF_SV_* overrides).

The scan script must *execute on* that host (cron/systemd/local bash) so ipmitool/ssh
to BMC IPs uses the host's network path. Manual BMC checks: SSH to 10.24.10.190 first,
then ipmitool -H <bmc_ip> … — not from a machine that cannot reach the BMC VLAN.

Run from repo root:
  python scripts/deploy_scan_tray_etf_sv.py

Requires: paramiko, network reachability to the target host.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko

from config.etf_config import ROOMS


def upload_script(host: str, user: str, password: str, remote_path: str, local_path: str, state_dir: str) -> None:
    with open(local_path, "r", encoding="utf-8") as f:
        content = f.read()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=20)
    remote_dir = os.path.dirname(remote_path)
    stdin, stdout, stderr = client.exec_command(f"mkdir -p {remote_dir}")
    stdout.channel.recv_exit_status()
    sd = (state_dir or "").strip()
    if sd:
        stdin, stdout, stderr = client.exec_command(f"mkdir -p {sd}")
        stdout.channel.recv_exit_status()
    stdin, stdout, stderr = client.exec_command(f"cp -f {remote_path} {remote_path}.bak 2>/dev/null || true")
    stdout.channel.recv_exit_status()
    sftp = client.open_sftp()
    with sftp.open(remote_path, "w") as rf:
        rf.write(content)
    sftp.close()
    client.exec_command(f"chmod +x {remote_path}")
    client.close()


def main() -> int:
    cfg = ROOMS.get("etf_sv")
    if not cfg:
        print("ROOMS['etf_sv'] missing — check config/etf_config.py")
        return 1
    host = (cfg.get("ssh_host") or "").strip()
    if not host:
        print("etf_sv ssh_host is empty")
        return 1
    user = cfg.get("ssh_user") or "root"
    password = cfg.get("ssh_pass") or ""
    remote_path = cfg.get("script_path") or "/root/TIN/scan_tray_bmc_arp_ssh.sh"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(script_dir, "scan_tray_bmc_arp_ssh.sh")
    if not os.path.isfile(local_path):
        print(f"Local script not found: {local_path}")
        return 1
    state_dir = (cfg.get("state_dir") or "/root/TIN/scan_state").strip()
    print(f"Deploying to etf_sv {host} as {user}")
    print(f"  remote: {remote_path}")
    print(f"  state:  {state_dir} (ensure this directory exists on the host)")
    try:
        upload_script(host, user, password, remote_path, local_path, state_dir)
    except Exception as e:
        print(f"FAILED: {e}")
        return 1
    print("OK — uploaded and chmod +x. SSH to this host first, then test (ipmitool needs this hop):")
    print(f"  ssh {user}@{host}")
    print(f"  OUTPUT_RAW=1 SCAN_STATE_DIR={state_dir} bash {remote_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
