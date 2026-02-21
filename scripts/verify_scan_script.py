#!/usr/bin/env python3
"""Verify ALLOW_HOSTS_REGEX in scan_tray_bmc_mpi.sh on DHCP server."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko
from config.debug_config import SSH_DHCP_HOST, SSH_DHCP_USER, SSH_DHCP_PASSWORD

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_DHCP_HOST, username=SSH_DHCP_USER, password=SSH_DHCP_PASSWORD, timeout=15)
    stdin, stdout, stderr = client.exec_command(
    "grep -n 'ALLOW_HOSTS_REGEX\\|EXCLUDE_HOSTS_REGEX\\|host ~ re\\|host !~ ex\\|SMM_IP\\|arp_map' /root/TIN/scan_tray_bmc_mpi.sh"
)
    print(stdout.read().decode())
    client.close()

if __name__ == "__main__":
    main()
