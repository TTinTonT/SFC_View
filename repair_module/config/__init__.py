# -*- coding: utf-8 -*-
"""Repair module configuration (DB + form dropdowns)."""

from .db_config import CONN_USER, CONN_PASSWORD, CONN_DSN, ORACLE_CLIENT_DIR
from .repair_config import (
    REASON_CODES,
    REPAIR_ACTIONS,
    DUTY_TYPES,
    REPAIR_ACTION_RECORD_MAP,
)

__all__ = [
    "CONN_USER",
    "CONN_PASSWORD",
    "CONN_DSN",
    "ORACLE_CLIENT_DIR",
    "REASON_CODES",
    "REPAIR_ACTIONS",
    "DUTY_TYPES",
    "REPAIR_ACTION_RECORD_MAP",
]
