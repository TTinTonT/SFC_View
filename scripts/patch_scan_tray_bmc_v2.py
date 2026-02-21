#!/usr/bin/env python3
"""Patch scan_tray_bmc_mpi.sh: add ARP lookup for SMM_IP, remove HOST/LEASE_MAC/CLTT."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko
from config.debug_config import SSH_DHCP_HOST, SSH_DHCP_USER, SSH_DHCP_PASSWORD

REMOTE_PATH = "/root/TIN/scan_tray_bmc_mpi.sh"

# Replacements to apply (use \\t - file has literal backslash-t)
PATCHES = [
    # 1. run_one: output only ip, bmc_mac, smm_mac, chassis_sn, status, fru_err
    (
        '  echo -e "$ip\\t$host\\t$lease_mac\\t$cltt\\t$bmc_mac\\t$smm_mac\\t$chassis_sn\\t$status\\t$fru_err"',
        '  echo -e "$ip\\t$bmc_mac\\t$smm_mac\\t$chassis_sn\\t$status\\t$fru_err"',
    ),
    # 2. Header: add SMM_IP, remove HOST LEASE_MAC CLTT
    (
        'echo -e "IP\\tHOST\\tLEASE_MAC\\tCLTT\\tBMC_FRU_MAC\\tSMM_FRU_MAC\\tCHASSIS_SERIAL\\tFRU_STATUS\\tFRU_ERR" > "$out"',
        'echo -e "IP\\tSMM_IP\\tBMC_FRU_MAC\\tSMM_FRU_MAC\\tCHASSIS_SERIAL\\tFRU_STATUS\\tFRU_ERR" > "$out"',
    ),
]

# Block to insert before "column -t" - post-process to add SMM_IP from ARP
POST_PROCESS_BLOCK = r'''
########################################
# ARP lookup: SMM_FRU_MAC -> SMM_IP
# Parse /proc/net/arp, build MAC->IP map, add SMM_IP column
########################################
arp_map="$tmp_dir/arp_map.tsv"
awk '
NR>1 && $3=="0x2" {
  gsub(/:/,"",$4); mac=tolower($4)
  if(length(mac)==12) print mac "\t" $1
}
' /proc/net/arp 2>/dev/null | sort -u > "$arp_map"

out2="$tmp_dir/out2.tsv"
awk -v arpfile="$arp_map" -F"\t" '
BEGIN{ while((getline < arpfile) > 0) arp[$1]=$2 }
NR==1{ print; next }
{
  ip=$1; bmc=$2; smm=$3; chassis=$4; status=$5; err=$6
  smm_ip=""
  if(smm!=""){
    gsub(/[^0-9A-Fa-f]/,"",smm)
    smm_norm=tolower(smm)
    if(smm_norm in arp) smm_ip=arp[smm_norm]
  }
  print ip "\t" smm_ip "\t" bmc "\t" smm "\t" chassis "\t" status "\t" err
}
' "$out" > "$out2"
mv "$out2" "$out"
'''

# Replace: "column -t -s $'\\t' \"$out\"" with the block + column
OLD_COLUMN = "column -t -s $'\\t' \"$out\""


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_DHCP_HOST, username=SSH_DHCP_USER, password=SSH_DHCP_PASSWORD, timeout=15)

    sftp = client.open_sftp()
    with sftp.open(REMOTE_PATH, "r") as f:
        content = f.read().decode("utf-8", errors="replace")

    changes = []
    for old, new in PATCHES:
        if old in content:
            if new in content:
                changes.append("(already applied)")
            else:
                content = content.replace(old, new)
                changes.append("Patched")
        else:
            changes.append(f"SKIP: old string not found (len={len(old)})")

    # Insert ARP post-process before column
    if "arp_map=" not in content and "SMM_IP" in content:
        content = content.replace(
            OLD_COLUMN,
            POST_PROCESS_BLOCK + "\n" + OLD_COLUMN,
        )
        changes.append("Added ARP lookup for SMM_FRU_MAC -> SMM_IP")
    elif "arp_map=" in content:
        changes.append("ARP lookup already present")

    with sftp.open(REMOTE_PATH, "w") as f:
        f.write(content)
    sftp.close()
    client.close()

    for c in changes:
        print(c)
    if not changes:
        print("No changes needed.")


if __name__ == "__main__":
    main()
