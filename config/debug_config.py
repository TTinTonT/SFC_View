# -*- coding: utf-8 -*-
"""FA Debug Place config: poll interval, lookback, terminal WebSocket URL."""

import os

POLL_INTERVAL_SEC = 60
LOOKBACK_HOURS = 24

WS_TERMINAL_URL = os.environ.get(
    "WS_TERMINAL_URL",
    "ws://10.16.138.80:5111/api/agent/terminal?model=gpt-5.1-codex-max-high",
)
UPLOAD_URL = os.environ.get(
    "UPLOAD_URL",
    "http://10.16.138.80:5111/api/agent/upload",
)
# AI server admin API (for purge uploads)
AI_ADMIN_BASE_URL = os.environ.get("AI_ADMIN_BASE_URL", "http://10.16.138.80:5111").rstrip("/")
# Form field name for file upload (e.g. "file", "files", "upload")
UPLOAD_FIELD_NAME = os.environ.get("UPLOAD_FIELD_NAME", "file")

# SSH to DHCP server (for terminal proxy)
SSH_DHCP_HOST = "10.16.138.67"
SSH_DHCP_USER = "root"
SSH_DHCP_PASSWORD = "root"

# Crabber API: search by SN -> node_log_id -> get_node_info -> Log Report File Path
# search_log_items: GET /api/search_log_items/?sn=XXX
# get_node_info: GET /api/get_node_info/?node_log_id=XXX
CRABBER_BASE_URL = os.environ.get("CRABBER_BASE_URL", "http://10.16.138.66:8000").rstrip("/")
CRABBER_TOKEN = os.environ.get("CRABBER_TOKEN", "06939a6ac0ed828115deba6a6bed85de77c715bb")
