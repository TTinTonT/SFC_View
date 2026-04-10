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
# Oberon L10 log share UNC prefix (see crabber.log_unc_path); override with CRABBER_LOG_UNC_ROOT
CRABBER_LOG_UNC_ROOT = os.environ.get("CRABBER_LOG_UNC_ROOT", get_default("CRABBER_LOG_UNC_ROOT") or "").strip()
CRABBER_REPLAY_TIMEOUT_SEC = int(
    os.environ.get("CRABBER_REPLAY_TIMEOUT_SEC", get_default("CRABBER_REPLAY_TIMEOUT_SEC") or 25)
)

# Offline replay execution profile (no hardcoded host/path in business logic)
REPLAY_EXECUTION_HOST = (os.environ.get("REPLAY_EXECUTION_HOST", get_default("REPLAY_EXECUTION_HOST") or "")).strip()
REPLAY_SSH_USER = (os.environ.get("REPLAY_SSH_USER", get_default("REPLAY_SSH_USER") or "")).strip()
REPLAY_SSH_PASSWORD = (os.environ.get("REPLAY_SSH_PASSWORD", get_default("REPLAY_SSH_PASSWORD") or "")).strip()
REPLAY_DATAFILE_DIR = (os.environ.get("REPLAY_DATAFILE_DIR", get_default("REPLAY_DATAFILE_DIR") or "/tmp/replay_datafiles")).strip()
REPLAY_DATACENTER_CMD = (os.environ.get("REPLAY_DATACENTER_CMD", get_default("REPLAY_DATACENTER_CMD") or "run_datacenter.sh")).strip()

# Offline replay site infra profile
REPLAY_MAIN_BUNDLE_ROOT = (os.environ.get("REPLAY_MAIN_BUNDLE_ROOT", get_default("REPLAY_MAIN_BUNDLE_ROOT") or "")).strip()
REPLAY_AUX_BUNDLE_ROOT = (os.environ.get("REPLAY_AUX_BUNDLE_ROOT", get_default("REPLAY_AUX_BUNDLE_ROOT") or "")).strip()
REPLAY_TEST_BAY_PORT_MAP = (os.environ.get("REPLAY_TEST_BAY_PORT_MAP", get_default("REPLAY_TEST_BAY_PORT_MAP") or "{}")).strip()
REPLAY_FACTORY_CODE_DEFAULT = (os.environ.get("REPLAY_FACTORY_CODE_DEFAULT", get_default("REPLAY_FACTORY_CODE_DEFAULT") or "")).strip()
REPLAY_DEFAULT_SKU = (os.environ.get("REPLAY_DEFAULT_SKU", get_default("REPLAY_DEFAULT_SKU") or "l10_prod_ts2") or "l10_prod_ts2").strip()

# Replay console transcript + backend verdict polling
REPLAY_CONSOLE_LOGGING_ENABLED = (
    os.environ.get("REPLAY_CONSOLE_LOGGING_ENABLED", get_default("REPLAY_CONSOLE_LOGGING_ENABLED") or "1") or "1"
).strip().lower() in ("1", "true", "yes", "on")
REPLAY_CONSOLE_LOG_DIR = (
    os.environ.get("REPLAY_CONSOLE_LOG_DIR", get_default("REPLAY_CONSOLE_LOG_DIR") or "/tmp/replay_console_logs") or "/tmp/replay_console_logs"
).strip()
REPLAY_EXIT_SIDECAR_DIR = (
    os.environ.get("REPLAY_EXIT_SIDECAR_DIR", get_default("REPLAY_EXIT_SIDECAR_DIR") or REPLAY_CONSOLE_LOG_DIR) or REPLAY_CONSOLE_LOG_DIR
).strip()
REPLAY_STATUS_POLL_HINT_MS = int(
    os.environ.get("REPLAY_STATUS_POLL_HINT_MS", get_default("REPLAY_STATUS_POLL_HINT_MS") or 3000) or 3000
)
REPLAY_STATUS_SSH_TIMEOUT_SEC = int(
    os.environ.get("REPLAY_STATUS_SSH_TIMEOUT_SEC", get_default("REPLAY_STATUS_SSH_TIMEOUT_SEC") or 15) or 15
)
REPLAY_LOG_TAIL_MAX_LINES = int(
    os.environ.get("REPLAY_LOG_TAIL_MAX_LINES", get_default("REPLAY_LOG_TAIL_MAX_LINES") or 400) or 400
)
REPLAY_LOG_PARSE_MAX_BYTES = int(
    os.environ.get("REPLAY_LOG_PARSE_MAX_BYTES", get_default("REPLAY_LOG_PARSE_MAX_BYTES") or 1048576) or 1048576
)
REPLAY_RUN_TIMEOUT_SEC = int(
    os.environ.get("REPLAY_RUN_TIMEOUT_SEC", get_default("REPLAY_RUN_TIMEOUT_SEC") or 43200) or 43200
)
REPLAY_BACKEND_COPY_MODE = (
    os.environ.get("REPLAY_BACKEND_COPY_MODE", get_default("REPLAY_BACKEND_COPY_MODE") or "disabled") or "disabled"
).strip().lower()
REPLAY_BACKEND_LOG_DIR = (os.environ.get("REPLAY_BACKEND_LOG_DIR", get_default("REPLAY_BACKEND_LOG_DIR") or "")).strip()
REPLAY_CLEANUP_CONSOLE_MAX_BYTES = int(
    os.environ.get("REPLAY_CLEANUP_CONSOLE_MAX_BYTES", get_default("REPLAY_CLEANUP_CONSOLE_MAX_BYTES") or 2097152) or 2097152
)
