# -*- coding: utf-8 -*-
"""Repair form options and action-to-record-type mapping."""

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

# --- Repair action -> RECORD_TYPE (single char) ---
REPAIR_ACTION_RECORD_MAP = {
    "REPROGRAM": "P",
    "REPLACE": "R",
    "RETEST": "T",
    "RELABEL": "L",
    "RESEAT & RETEST": "S",
}
