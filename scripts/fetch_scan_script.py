#!/usr/bin/env python3
"""Fetch full content of scan_tray_bmc_mpi.sh from DHCP server."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko
from config.debug_config import SSH_DHCP_HOST, SSH_DHCP_USER, SSH_DHCP_PASSWORD

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_DHCP_HOST, username=SSH_DHCP_USER, password=SSH_DHCP_PASSWORD, timeout=15)
    sftp = client.open_sftp()
    with sftp.open("/root/TIN/scan_tray_bmc_mpi.sh", "r") as f:
        print(f.read().decode("utf-8", errors="replace"))
    sftp.close()
    client.close()

if __name__ == "__main__":
    main()
