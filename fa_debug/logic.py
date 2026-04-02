# -*- coding: utf-8 -*-
"""
FA Debug logic: aggregate rows for KPIs and timeline.
Rows come from parse_fail_result_html; compute_all provides summary.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from analytics.bp_check import add_bp_to_rows
from crabber.client import tier_from_crabber_station


def prepare_debug_rows(rows: List[dict]) -> List[dict]:
    """
    Add is_bonepile, sort by test_time_dt desc (newest first).
    Returns list suitable for timeline and drill-down.
    """
    rows = add_bp_to_rows(rows)
    out = [r for r in rows if r.get("test_time_dt") is not None]
    out.sort(key=lambda r: r["test_time_dt"] or datetime.min, reverse=True)
    return out


def strip_system_station(station: str) -> str:
    """Remove only the SYSTEM_ prefix (7 chars); keep the rest of the station code intact."""
    s = (station or "").strip()
    prefix = "SYSTEM_"
    if len(s) >= len(prefix) and s.upper().startswith(prefix):
        return s[len(prefix):]
    return s


def parse_crabber_log_time_iso(s: str) -> Optional[datetime]:
    raw = (s or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def format_timeline_time(dt: datetime) -> str:
    if dt.tzinfo:
        dt = dt.astimezone()
    return dt.strftime("%Y/%m/%d %H:%M:%S")


def timeline_row_from_crabber_proc(item: dict, offline: bool) -> Optional[dict]:
    """
    Build one timeline row dict from search_log_items row or fetch_test_history row.
    """
    if not isinstance(item, dict):
        return None
    sn = str(item.get("sn") or item.get("SN") or "").strip()
    if not sn:
        return None
    station_raw = str(item.get("station") or item.get("Station") or "").strip()
    if tier_from_crabber_station(station_raw) != "L10":
        return None
    log_iso = str(
        item.get("log_time")
        or item.get("LogTime")
        or item.get("test_time")
        or ""
    ).strip()
    dt = parse_crabber_log_time_iso(log_iso)
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo:
        dt_naive = dt.astimezone().replace(tzinfo=None)
    else:
        dt_naive = dt
    pn_name = str(
        item.get("pn_name")
        or item.get("pnName")
        or item.get("pn")
        or item.get("PN")
        or ""
    ).strip()
    part_number = (item.get("part_number") or "").strip() or pn_name
    res_label = "TESTING (OFFLINE)" if offline else "TESTING"
    return {
        "serial_number": sn,
        "work_order": "",
        "part_number": part_number,
        "station": strip_system_station(station_raw),
        "test_time": format_timeline_time(dt),
        "test_time_dt": dt_naive,
        "result": res_label,
        "error_code": "",
        "failure_msg": "",
        "current_station": "",
        "station_instance": "",
        "crabber_proc": True,
        "crabber_offline": bool(offline),
    }


def timeline_rows_from_crabber_proc_items(items: List[dict], offline: bool) -> List[dict]:
    out: List[dict] = []
    for it in items:
        row = timeline_row_from_crabber_proc(it, offline)
        if row:
            out.append(row)
    return out


def merge_timeline_with_crabber_proc(
    base_rows: List[dict],
    proc_prod_rows: List[dict],
    proc_offline_rows: List[dict],
) -> List[dict]:
    """
    Dedupe: production PROC SNs removed from offline and from SFC base.
    Sort: prod PROC, offline PROC, then SFC rows (each block by test_time_dt desc).
    """
    prod_sns = {(r.get("serial_number") or "").strip().upper() for r in proc_prod_rows if r.get("serial_number")}
    off_filtered = [
        r
        for r in proc_offline_rows
        if (r.get("serial_number") or "").strip().upper() not in prod_sns
    ]
    off_sns = {(r.get("serial_number") or "").strip().upper() for r in off_filtered if r.get("serial_number")}
    active_sns = prod_sns | off_sns
    base_f = [
        r
        for r in base_rows
        if (r.get("serial_number") or "").strip().upper() not in active_sns
    ]

    def sort_key(r: dict) -> datetime:
        return r.get("test_time_dt") or datetime.min

    proc_prod_rows = sorted(proc_prod_rows, key=sort_key, reverse=True)
    off_filtered = sorted(off_filtered, key=sort_key, reverse=True)
    base_f = sorted(base_f, key=sort_key, reverse=True)
    merged = proc_prod_rows + off_filtered + base_f
    return add_bp_to_rows(merged)
