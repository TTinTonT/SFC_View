# -*- coding: utf-8 -*-
"""ETF Status config: per-room SSH and script paths."""

import os

from config.debug_config import SSH_DHCP_HOST, SSH_DHCP_PASSWORD, SSH_DHCP_USER

# Per-room config: host, user, pass, script_path, state_dir
ROOMS = {
    "etf": {
        "ssh_host": os.environ.get("ETF_SSH_HOST", SSH_DHCP_HOST),
        "ssh_user": os.environ.get("ETF_SSH_USER", SSH_DHCP_USER),
        "ssh_pass": os.environ.get("ETF_SSH_PASS", SSH_DHCP_PASSWORD),
        "script_path": os.environ.get("ETF_SCRIPT_PATH", "/root/TIN/scan_tray_bmc_mpi.sh"),
        "state_dir": os.environ.get("ETF_STATE_DIR", "/root/TIN/scan_state"),
    },
    "room6": {
        "ssh_hosts": (
            [h.strip() for h in os.environ.get("ROOM6_SSH_HOSTS", "10.16.138.71,10.16.138.79,10.16.138.73").split(",") if h.strip()]
            or ["10.16.138.71", "10.16.138.79", "10.16.138.73"]
        ),
        "ssh_user": os.environ.get("ROOM6_SSH_USER", "root"),
        "ssh_pass": os.environ.get("ROOM6_SSH_PASS", "root"),
        "script_path": os.environ.get("ROOM6_SCRIPT_PATH", "/root/TIN/scan_tray_bmc_mpi_new.sh"),
        "state_dir": os.environ.get("ROOM6_STATE_DIR", "/root/TIN/scan_state"),
    },
    "room7": {
        "ssh_host": os.environ.get("ROOM7_SSH_HOST", "10.16.138.87"),
        "ssh_user": os.environ.get("ROOM7_SSH_USER", "root"),
        "ssh_pass": os.environ.get("ROOM7_SSH_PASS", "root"),
        "script_path": os.environ.get("ROOM7_SCRIPT_PATH", "/root/TIN/scan_tray_bmc_mpi_new.sh"),
        "state_dir": os.environ.get("ROOM7_STATE_DIR", "/root/TIN/scan_state"),
    },
    "room8": {
        "ssh_host": os.environ.get("ROOM8_SSH_HOST", "10.16.138.75"),
        "ssh_user": os.environ.get("ROOM8_SSH_USER", "root"),
        "ssh_pass": os.environ.get("ROOM8_SSH_PASS", "root"),
        "script_path": os.environ.get("ROOM8_SCRIPT_PATH", "/root/TIN/scan_tray_bmc_mpi_new.sh"),
        "state_dir": os.environ.get("ROOM8_STATE_DIR", "/root/TIN/scan_state"),
    },
}
