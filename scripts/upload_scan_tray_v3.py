#!/usr/bin/env python3
"""Upload scan_tray_bmc_mpi_new.sh to server as scan_tray_bmc_mpi.sh (backup old first)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko
from config.debug_config import SSH_DHCP_HOST, SSH_DHCP_USER, SSH_DHCP_PASSWORD

REMOTE_PATH = "/root/TIN/scan_tray_bmc_mpi.sh"
BACKUP_PATH = "/root/TIN/scan_tray_bmc_mpi.sh.bak"

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(script_dir, "scan_tray_bmc_mpi_new.sh")
    with open(local_path, "r", encoding="utf-8") as f:
        content = f.read()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_DHCP_HOST, username=SSH_DHCP_USER, password=SSH_DHCP_PASSWORD, timeout=15)

    stdin, stdout, stderr = client.exec_command(f"cp -f {REMOTE_PATH} {BACKUP_PATH} 2>/dev/null || true")
    stdout.channel.recv_exit_status()
    print("Backed up to", BACKUP_PATH)

    sftp = client.open_sftp()
    with sftp.open(REMOTE_PATH, "w") as f:
        f.write(content)
    sftp.close()
    client.close()
    print(f"Uploaded new script to {REMOTE_PATH}")

if __name__ == "__main__":
    main()
