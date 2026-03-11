# -*- coding: utf-8 -*-
"""
Cấu hình chung: DB, Reason codes, Repair actions, Duty types.
Sửa file này khi cần đổi DSN, user, password, Oracle client path.
"""

# --- Database (Oracle) ---
CONN_USER = "sfis1"
CONN_PASSWORD = "sfis1"
CONN_DSN = "10.16.137.112:1526/SJSFC2DB"
ORACLE_CLIENT_DIR = r"C:\Users\FAswing\Downloads\instantclient_23_0"

# --- Reason codes: (code, display_label, reason_desc) ---
REASON_CODES = [
    ("RC36", "RC36 - Default", "Component Fail"),
    ("RC500", "RC500 - R_xxx jump", "Bypass for inline retest"),
]

# --- Repair actions ---
REPAIR_ACTIONS = [
    "REPROGRAM",
    "REPLACE",
    "RETEST",
    "RELABEL",
    "RESEAT & RETEST",
]

# --- Duty types ---
DUTY_TYPES = [
    "ASSEMBLY",
    "MATERIAL",
    "MATERIAL-CABLE",
    "NDF",
    "OTHER",
    "PRODUCT",
    "TEST FIXTURE",
    "TEST PROGRAM",
    "RETEST",
]

# --- Repair action -> RECORD_TYPE (1 ký tự) ---
REPAIR_ACTION_RECORD_MAP = {
    "REPROGRAM": "P",
    "REPLACE": "R",
    "RETEST": "T",
    "RELABEL": "L",
    "RESEAT & RETEST": "S",
}
