# -*- coding: utf-8 -*-
"""FA Debug Place config: poll interval, lookback, terminal WebSocket URL."""

import os

from config.site_defaults import get_default

# Server poller and browser poll: same interval (ms passed to fa_debug.html as pollIntervalMs).
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_SEC", get_default("POLL_INTERVAL_SEC") or 60))
POLL_INTERVAL_MS = POLL_INTERVAL_SEC * 1000
LOOKBACK_HOURS = 24

# Crabber timeline: global search_log_items page-1 + per-SN reconcile budget
CRABBER_PAGE_TIMEOUT_SEC = int(os.environ.get("CRABBER_PAGE_TIMEOUT_SEC", get_default("CRABBER_PAGE_TIMEOUT_SEC") or 22))
CRABBER_PROC_RECONCILE_MAX_SN = int(
    os.environ.get("CRABBER_PROC_RECONCILE_MAX_SN", get_default("CRABBER_PROC_RECONCILE_MAX_SN") or 15)
)
CRABBER_RECONCILE_TIMEOUT_SEC = int(
    os.environ.get("CRABBER_RECONCILE_TIMEOUT_SEC", get_default("CRABBER_RECONCILE_TIMEOUT_SEC") or 10)
)

WS_TERMINAL_URL = os.environ.get("WS_TERMINAL_URL", get_default("WS_TERMINAL_URL"))
UPLOAD_URL = os.environ.get("UPLOAD_URL", get_default("UPLOAD_URL"))
# AI server admin API (for purge uploads)
AI_ADMIN_BASE_URL = os.environ.get("AI_ADMIN_BASE_URL", get_default("AI_ADMIN_BASE_URL")).rstrip("/")
# Form field name for file upload (e.g. "file", "files", "upload")
UPLOAD_FIELD_NAME = os.environ.get("UPLOAD_FIELD_NAME", get_default("UPLOAD_FIELD_NAME"))

# SSH to DHCP server (for terminal proxy)
SSH_DHCP_HOST = os.environ.get("SSH_DHCP_HOST", get_default("SSH_DHCP_HOST"))
SSH_DHCP_USER = os.environ.get("SSH_DHCP_USER", get_default("SSH_DHCP_USER"))
SSH_DHCP_PASSWORD = os.environ.get("SSH_DHCP_PASSWORD", get_default("SSH_DHCP_PASSWORD"))

# SSH to DUT BMC (root@bmc_ip) and Host (nvidia@sys_ip) from SN menu
BMC_SSH_USER = os.environ.get("BMC_SSH_USER", get_default("BMC_SSH_USER"))
BMC_SSH_PASSWORD = os.environ.get("BMC_SSH_PASSWORD", get_default("BMC_SSH_PASSWORD"))
HOST_SSH_USER = os.environ.get("HOST_SSH_USER", get_default("HOST_SSH_USER"))
HOST_SSH_PASSWORD = os.environ.get("HOST_SSH_PASSWORD", get_default("HOST_SSH_PASSWORD"))

# Crabber API: search by SN -> node_log_id -> get_node_info -> Log Report File Path
# search_log_items: GET /api/search_log_items/?sn=XXX
# get_node_info: GET /api/get_node_info/?node_log_id=XXX
CRABBER_BASE_URL = os.environ.get("CRABBER_BASE_URL", get_default("CRABBER_BASE_URL")).rstrip("/")
CRABBER_TOKEN = os.environ.get("CRABBER_TOKEN", get_default("CRABBER_TOKEN"))
CRABBER_USER_ID = str(os.environ.get("CRABBER_USER_ID", get_default("CRABBER_USER_ID") or "41")).strip()
CRABBER_SITENAME = (os.environ.get("CRABBER_SITENAME", get_default("CRABBER_SITENAME") or "SanJose")).strip()
