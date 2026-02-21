#!/usr/bin/env python3
"""Edit scan_tray_bmc_mpi.sh on DHCP server: allow *bmc*, exclude dpu-bmc."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko
from config.debug_config import SSH_DHCP_HOST, SSH_DHCP_USER, SSH_DHCP_PASSWORD

REMOTE_PATH = "/root/TIN/scan_tray_bmc_mpi.sh"


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_DHCP_HOST, username=SSH_DHCP_USER, password=SSH_DHCP_PASSWORD, timeout=15)

    sftp = client.open_sftp()
    with sftp.open(REMOTE_PATH, "r") as f:
        content = f.read().decode("utf-8", errors="replace")

    changes = []

    # 1. Add EXCLUDE_HOSTS_REGEX after ALLOW_HOSTS_REGEX (if not present)
    if "EXCLUDE_HOSTS_REGEX" not in content:
        content = content.replace(
            'ALLOW_HOSTS_REGEX="${ALLOW_HOSTS_REGEX:-bmc}"',
            'ALLOW_HOSTS_REGEX="${ALLOW_HOSTS_REGEX:-bmc}"\nEXCLUDE_HOSTS_REGEX="${EXCLUDE_HOSTS_REGEX:-dpu-bmc}"',
        )
        changes.append("Added EXCLUDE_HOSTS_REGEX=dpu-bmc")
    else:
        changes.append("EXCLUDE_HOSTS_REGEX already present")

    # 2. Update awk to use exclusion
    old_awk = "awk -v re=\"$ALLOW_HOSTS_REGEX\" '"
    new_awk = "awk -v re=\"$ALLOW_HOSTS_REGEX\" -v ex=\"$EXCLUDE_HOSTS_REGEX\" '"
    if old_awk in content and new_awk not in content:
        content = content.replace(old_awk, new_awk)
        changes.append("awk now receives ex (EXCLUDE_HOSTS_REGEX)")

    old_cond = "if(active && host ~ re && mac!=\"\" && ip!=\"\" && cltt_date!=\"\" && cltt_time!=\"\"){"
    new_cond = "if(active && host ~ re && host !~ ex && mac!=\"\" && ip!=\"\" && cltt_date!=\"\" && cltt_time!=\"\"){"
    if old_cond in content and new_cond not in content:
        content = content.replace(old_cond, new_cond)
        changes.append("Excluded hosts matching EXCLUDE_HOSTS_REGEX (dpu-bmc)")
    elif "host !~ ex" in content:
        changes.append("Exclusion condition already present")

    with sftp.open(REMOTE_PATH, "w") as f:
        f.write(content)
    sftp.close()
    client.close()

    for c in changes:
        print(c)


if __name__ == "__main__":
    main()
