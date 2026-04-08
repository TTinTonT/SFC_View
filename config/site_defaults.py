# -*- coding: utf-8 -*-
"""
Single source of default config values. No other config modules imported (avoid circular import).
Override via env: os.environ.get("KEY", get_default("KEY")).
Override by site: set SITE=taiwan (or other key in SITE_PROFILES) to use that profile for defaults.
"""

import os

# Defaults for current/san_jose site. All values as strings; consumers convert (int, bool) as needed.
DEFAULT = {
    # Flask
    "FLASK_HOST": "0.0.0.0",
    "FLASK_PORT": "5556",
    "FLASK_DEBUG": "true",
    # SFC
    "SFC_BASE_URL": "http://10.16.137.110",
    "SFC_USER": "SFC",
    "SFC_PWD": "EPD2TJW",
    "SFC_GROUP_NAME": "'AST','DCC','FC2','FCT','FLA','FLB','FLC','FLD','FLF','FLT','FPF','FTS','HPT','IOT','IST','NVL','PRET','RIN','RST'",
    "SFC_SESSION_TTL_SECONDS": "1800",
    "VALID_LOCATION": "San Jose",
    "SFC_INCLUDE_RACK": "L10",
    # SSH / Debug (DHCP jump host, terminal proxy)
    "SSH_DHCP_HOST": "10.16.138.67",
    "SSH_DHCP_USER": "root",
    "SSH_DHCP_PASSWORD": "root",
    # AI agent (terminal WebSocket, upload)
    "WS_TERMINAL_URL": "ws://10.16.138.80:5111/api/agent/terminal?model=gpt-5.1-codex-max-high",
    "UPLOAD_URL": "http://10.16.138.80:5111/api/agent/upload",
    "AI_ADMIN_BASE_URL": "http://10.16.138.80:5111",
    "UPLOAD_FIELD_NAME": "file",
    # BMC / Host SSH (SN menu)
    "BMC_SSH_USER": "root",
    "BMC_SSH_PASSWORD": "0penBmc",
    "HOST_SSH_USER": "nvidia",
    "HOST_SSH_PASSWORD": "nvidia",
    # Crabber API
    "CRABBER_BASE_URL": "http://10.16.138.66:8000",
    "CRABBER_TOKEN": "06939a6ac0ed828115deba6a6bed85de77c715bb",
    "CRABBER_USER_ID": "41",
    "CRABBER_SITENAME": "SanJose",
    # Oberon L10 log share (UNC prefix; folder segment = node_log_id + log_time UTC)
    "CRABBER_LOG_UNC_ROOT": r"\\10.16.137.111\Oberon\L10",
    # Crabber replay / raw offline test
    "CRABBER_REPLAY_TIMEOUT_SEC": "25",
    "REPLAY_EXECUTION_HOST": "10.16.138.67",
    "REPLAY_SSH_USER": "",
    "REPLAY_SSH_PASSWORD": "",
    "REPLAY_DATAFILE_DIR": "/tmp/replay_datafiles",
    "REPLAY_DATACENTER_CMD": "run_datacenter.sh",
    "REPLAY_MAIN_BUNDLE_ROOT": "",
    "REPLAY_AUX_BUNDLE_ROOT": "",
    "REPLAY_TEST_BAY_PORT_MAP": "{}",
    "REPLAY_FACTORY_CODE_DEFAULT": "",
    "REPLAY_DEFAULT_SKU": "l10_prod_ts2",
    # ETF
    "SFC_TRAY_STATUS_URL": "http://10.16.137.115/SFCAPI/SFC/Test_Fixture_Status",
    "SFC_LEVEL_GRADE": "L10",
    "ETF_POLL_INTERVAL_SEC": "60",
    "ETF_SSH_HOST": "10.16.138.67",
    "ETF_SCRIPT_PATH": "/root/TIN/scan_tray_bmc_arp_ssh.sh",
    "ETF_STATE_DIR": "/root/TIN/scan_state",
    "ROOM6_SSH_HOSTS": "10.16.138.71,10.16.138.79,10.16.138.73",
    "ROOM6_SSH_USER": "root",
    "ROOM6_SSH_PASS": "root",
    "ROOM6_SCRIPT_PATH": "/root/TIN/scan_tray_bmc_arp_ssh.sh",
    "ROOM6_STATE_DIR": "/root/TIN/scan_state",
    "ROOM7_SSH_HOST": "10.16.138.87",
    "ROOM7_SSH_USER": "root",
    "ROOM7_SSH_PASS": "root",
    "ROOM7_SCRIPT_PATH": "/root/TIN/scan_tray_bmc_arp_ssh.sh",
    "ROOM7_STATE_DIR": "/root/TIN/scan_state",
    "ROOM8_SSH_HOST": "10.16.138.75",
    "ROOM8_SSH_USER": "root",
    "ROOM8_SSH_PASS": "root",
    "ROOM8_SCRIPT_PATH": "/root/TIN/scan_tray_bmc_arp_ssh.sh",
    "ROOM8_STATE_DIR": "/root/TIN/scan_state",
    # Table config (IT Kitting proxy)
    "TABLE_CONFIG_API_URL": "http://10.16.137.110:81",
    "TABLE_CONFIG_COOKIE": "__RequestVerificationToken=x1HVWw4XHu2J-MOi2YdeFFCdxtE1cyXP0MpMiZxXaWDkZhI2H3-o-0omkiut66yo8j3gfvCI82f0aaxQ7DjNzeX7hRZ9_NKmTfFoNCPbJdE1; ASP.NET_SessionId=vfqjvf4snhhoc1tgptzkbzic; .AspNet.ApplicationCookie=G9FNtsRNFyjjdtGMvgrvEUSht_YxPX5ok6pPaMW1MUgfYW7NaWANUExzePekBOQhDA4tzbnwiQ8SlUPS6bD6LmuSCsdHxQmVjLDD0bm_Ht4RljAxG5uyffOgxiDQpv6Nq1oP6iaegAsNbcU2eC3VQ0dgbii8lahNtW8kCcu8S096GBDk0qWa_g-T4QNWTGwcXH-fTkgkm8k6PHM9qoytNhgQRH5KoIRB1ot7MWyeWMl2I2Ws4zOj1A9OOvnJQG72XAXP5Y8jk8J_PeZ-rRGJYQoaQjJyiGWTpJmup46c9PGsuYSnOSnZP4hxdbhvcyzhczk3SSt4tfH50bZGUgJOuw; JSESSIONID=913A8EF395179BEB13454B2C88C86089",  # expires; use env TABLE_CONFIG_COOKIE to override
    # Analytics
    "timezone": "America/Los_Angeles",
    # Auth (debug area): SMTP send-only, session TTL
    "AUTH_SESSION_TTL_MINUTES": "30",
    "SMTP_HOST": "",
    "SMTP_PORT": "587",
    "SMTP_USER": "",
    "SMTP_PASSWORD": "",
    "SMTP_USE_TLS": "true",
}

# Optional per-site overrides. Set SITE=taiwan (etc.) to use. Add new sites here.
SITE_PROFILES = {
    "taiwan": {
        "SFC_BASE_URL": "http://10.16.137.110",  # replace with Taiwan SFC URL when known
        "VALID_LOCATION": "Taiwan",
        "timezone": "Asia/Taipei",
        # Add SSH hosts, Crabber URL, etc. when known for Taiwan
    },
}


def get_default(key: str):
    """Return default for key: SITE_PROFILES[SITE][key] if set, else DEFAULT[key]. Env overrides are applied by callers."""
    site = os.environ.get("SITE", "default")
    profile = SITE_PROFILES.get(site, {})
    if key in profile:
        return profile[key]
    return DEFAULT.get(key)
