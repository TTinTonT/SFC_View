# -*- coding: utf-8 -*-
"""
UNC folder path for Oberon L10 log storage (Crabber test rows).

Pattern: <root>\\YYYY\\MM\\DD\\<node_log_id>  e.g.
  \\\\10.16.137.111\\Oberon\\L10\\2026\\04\\02\\105976

The folder segment is Crabber **node_log_id** (not exe_log_id). Date from log_time ISO in UTC.
Override root via CRABBER_LOG_UNC_ROOT.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from config.site_defaults import get_default


def extract_node_log_id(item: Dict[str, Any]) -> str:
    """Crabber node_log_id only — Oberon UNC folder name uses this, not exe_log_id."""
    if not isinstance(item, dict):
        return ""
    for k in ("node_log_id", "nodeLogId"):
        v = item.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def get_crabber_log_unc_root() -> str:
    """Windows UNC prefix without trailing backslash (e.g. \\\\host\\Oberon\\L10)."""
    v = os.environ.get("CRABBER_LOG_UNC_ROOT", get_default("CRABBER_LOG_UNC_ROOT") or "")
    return (v or "").strip()


def _utc_ymd_from_iso(log_time_iso: str) -> Optional[Tuple[str, str, str]]:
    raw = (log_time_iso or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return f"{dt.year:04d}", f"{dt.month:02d}", f"{dt.day:02d}"


def build_crabber_log_folder_unc(
    log_time_iso: str,
    log_id: Any,
    root: Optional[str] = None,
) -> str:
    """
    Build full UNC path. Returns "" if any part is missing or parse fails.
    """
    r = (root if root is not None else get_crabber_log_unc_root()).strip().rstrip("\\/")
    if not r:
        return ""
    lid = str(log_id).strip() if log_id is not None else ""
    if not lid:
        return ""
    ymd = _utc_ymd_from_iso(log_time_iso)
    if not ymd:
        return ""
    y, mo, d = ymd
    return f"{r}\\{y}\\{mo}\\{d}\\{lid}"
