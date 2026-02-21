#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paramiko
from config.debug_config import SSH_DHCP_HOST, SSH_DHCP_USER, SSH_DHCP_PASSWORD

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SSH_DHCP_HOST, username=SSH_DHCP_USER, password=SSH_DHCP_PASSWORD, timeout=15)
sftp = client.open_sftp()
with sftp.open("/root/TIN/scan_tray_bmc_mpi.sh", "r") as f:
    content = f.read().decode("utf-8", errors="replace")

# Find lines with echo, header, column
for i, line in enumerate(content.splitlines()):
    if "echo -e" in line and ("$ip" in line or "IP" in line):
        print(f"{i+1}: {repr(line)}")
    if "column" in line:
        print(f"{i+1}: {repr(line)}")
client.close()
