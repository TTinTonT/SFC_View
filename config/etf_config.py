# -*- coding: utf-8 -*-
"""ETF Status config: per-room SSH, script paths, poll interval."""

import os

from config.debug_config import SSH_DHCP_HOST, SSH_DHCP_PASSWORD, SSH_DHCP_USER
from config.site_defaults import get_default

ETF_POLL_INTERVAL_SEC = int(os.environ.get("ETF_POLL_INTERVAL_SEC", get_default("ETF_POLL_INTERVAL_SEC")))

SFC_TRAY_STATUS_URL = os.environ.get(
    "SFC_TRAY_STATUS_URL",
    get_default("SFC_TRAY_STATUS_URL"),
).rstrip("/")

SFC_LEVEL_GRADE = os.environ.get("SFC_LEVEL_GRADE", get_default("SFC_LEVEL_GRADE"))

def _room6_hosts():
    raw = os.environ.get("ROOM6_SSH_HOSTS", get_default("ROOM6_SSH_HOSTS"))
    lst = [h.strip() for h in (raw or "").split(",") if h.strip()]
    if not lst:
        fallback = get_default("ROOM6_SSH_HOSTS") or ""
        lst = [h.strip() for h in fallback.split(",") if h.strip()]
    return lst

ROOMS = {
    "etf": {
        "ssh_host": os.environ.get("ETF_SSH_HOST", get_default("ETF_SSH_HOST") or SSH_DHCP_HOST),
        "ssh_user": os.environ.get("ETF_SSH_USER", SSH_DHCP_USER),
        "ssh_pass": os.environ.get("ETF_SSH_PASS", SSH_DHCP_PASSWORD),
        "script_path": os.environ.get("ETF_SCRIPT_PATH", get_default("ETF_SCRIPT_PATH")),
        "state_dir": os.environ.get("ETF_STATE_DIR", get_default("ETF_STATE_DIR")),
    },
    "room6": {
        "ssh_hosts": _room6_hosts(),
        "ssh_user": os.environ.get("ROOM6_SSH_USER", get_default("ROOM6_SSH_USER")),
        "ssh_pass": os.environ.get("ROOM6_SSH_PASS", get_default("ROOM6_SSH_PASS")),
        "script_path": os.environ.get("ROOM6_SCRIPT_PATH", get_default("ROOM6_SCRIPT_PATH")),
        "state_dir": os.environ.get("ROOM6_STATE_DIR", get_default("ROOM6_STATE_DIR")),
    },
    "room7": {
        "ssh_host": os.environ.get("ROOM7_SSH_HOST", get_default("ROOM7_SSH_HOST")),
        "ssh_user": os.environ.get("ROOM7_SSH_USER", get_default("ROOM7_SSH_USER")),
        "ssh_pass": os.environ.get("ROOM7_SSH_PASS", get_default("ROOM7_SSH_PASS")),
        "script_path": os.environ.get("ROOM7_SCRIPT_PATH", get_default("ROOM7_SCRIPT_PATH")),
        "state_dir": os.environ.get("ROOM7_STATE_DIR", get_default("ROOM7_STATE_DIR")),
    },
    "room8": {
        "ssh_host": os.environ.get("ROOM8_SSH_HOST", get_default("ROOM8_SSH_HOST")),
        "ssh_user": os.environ.get("ROOM8_SSH_USER", get_default("ROOM8_SSH_USER")),
        "ssh_pass": os.environ.get("ROOM8_SSH_PASS", get_default("ROOM8_SSH_PASS")),
        "script_path": os.environ.get("ROOM8_SCRIPT_PATH", get_default("ROOM8_SCRIPT_PATH")),
        "state_dir": os.environ.get("ROOM8_STATE_DIR", get_default("ROOM8_STATE_DIR")),
    },
}
