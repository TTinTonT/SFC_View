# -*- coding: utf-8 -*-
"""
Compute SN list for drill-down modal.
Uses pre-computed result from compute_all.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from config.app_config import CA_TZ
from analytics.pass_fail import is_sn_passed


def _norm(s: Any) -> str:
    return (str(s) if s is not None else "").strip().upper()


def _row_to_ca_date(dt) -> Optional[date]:
    if dt is None:
        return None
    if CA_TZ and isinstance(dt, datetime):
        try:
            ca_dt = CA_TZ.localize(dt)
            return ca_dt.date()
        except Exception:
            return dt.date() if hasattr(dt, "date") else None
    return dt.date() if hasattr(dt, "date") else None


def _date_to_period(d: date, aggregation: str) -> str:
    if aggregation == "monthly":
        return d.strftime("%Y-%m")
    if aggregation == "weekly":
        days_since_sunday = (d.weekday() + 1) % 7
        week_start = d - timedelta(days=days_since_sunday)
        week_end = week_start + timedelta(days=6)
        return f"{week_start.strftime('%Y-%m-%d')}~{week_end.strftime('%Y-%m-%d')}"
    return d.strftime("%Y-%m-%d")


def compute_sn_list(
    computed: Dict[str, Any],
    metric: str,
    sku: Optional[str] = None,
    period: Optional[str] = None,
    station: Optional[str] = None,
    outcome: Optional[str] = None,
    aggregation: str = "daily",
) -> List[Dict[str, Any]]:
    """
    Return list of SN details for the given metric bucket.
    Each item: { sn, part_number, status, last_station, last_test_time, is_bonepile, ... }
    """
    sn_tests = computed.get("_sn_tests") or {}
    sn_pass = computed.get("_sn_pass") or {}
    sn_is_bp = computed.get("_sn_is_bp") or {}
    sn_latest_part = computed.get("_sn_latest_part") or {}
    sn_latest_dt = computed.get("_sn_latest_dt") or {}
    rows = computed.get("rows") or []

    # Build per-SN latest row for display
    sn_latest_row: Dict[str, dict] = {}
    for r in rows:
        sn = (r.get("serial_number") or "").strip()
        if not sn:
            continue
        dt_val = r.get("test_time_dt")
        existing = sn_latest_row.get(sn)
        if existing is None:
            sn_latest_row[sn] = dict(r)
            continue
        exist_dt = existing.get("test_time_dt")
        if dt_val and (exist_dt is None or dt_val > exist_dt):
            sn_latest_row[sn] = dict(r)

    def get_last_failure_msg(sn: str) -> str:
        """Return last failure_msg for SN, optionally at given station."""
        tests = sn_tests.get(sn) or []
        fail_rows = [r for r in tests if _norm(r.get("result")) == "FAIL"]
        if station:
            st = _norm(station)
            fail_rows = [r for r in fail_rows if _norm(r.get("station")) == st]
        if not fail_rows:
            return ""
        latest = max(
            fail_rows,
            key=lambda r: r.get("test_time_dt") or datetime.min,
        )
        return (latest.get("failure_msg") or "").strip()

    def make_sn_item(sn: str) -> Dict[str, Any]:
        latest = sn_latest_row.get(sn) or {}
        return {
            "sn": sn,
            "part_number": sn_latest_part.get(sn, "Unknown") or "Unknown",
            "status": "PASS" if sn_pass.get(sn) else "FAIL",
            "last_station": (latest.get("station") or "").strip(),
            "last_test_time": (latest.get("test_time") or "").strip(),
            "is_bonepile": bool(sn_is_bp.get(sn)),
            "last_failure_msg": get_last_failure_msg(sn),
        }

    # Metric: total, pass, fail, test_flow
    if metric in ("total", "tested"):
        candidates = list(sn_tests.keys())
    elif metric == "pass":
        candidates = [sn for sn in sn_tests if sn_pass.get(sn)]
    elif metric == "fail":
        candidates = [sn for sn in sn_tests if not sn_pass.get(sn)]
    elif metric == "test_flow":
        # Start with all; will filter by station+outcome below
        candidates = list(sn_tests.keys())
    else:
        candidates = []

    # Tray summary metrics
    if metric.startswith("tray_"):
        parts = metric.split("_")
        if len(parts) >= 3:
            seg = parts[1]  # tested, pass, fail
            bp_seg = parts[2]  # bp, fresh, total
            if seg == "tested":
                candidates = list(sn_tests.keys())
            elif seg == "pass":
                candidates = [sn for sn in sn_tests if sn_pass.get(sn)]
            elif seg == "fail":
                candidates = [sn for sn in sn_tests if not sn_pass.get(sn)]
            else:
                candidates = []
            if bp_seg == "bp":
                candidates = [sn for sn in candidates if sn_is_bp.get(sn)]
            elif bp_seg == "fresh":
                candidates = [sn for sn in candidates if not sn_is_bp.get(sn)]
            # total: no filter

    # SKU filter
    if sku and sku != "__TOTAL__":
        candidates = [sn for sn in candidates if (sn_latest_part.get(sn) or "Unknown") == sku]

    # Period filter (for breakdown)
    if period and period != "__TOTAL__":
        filtered = []
        for sn in candidates:
            tests = sn_tests.get(sn) or []
            for r in tests:
                dt_val = r.get("test_time_dt")
                if dt_val is None:
                    continue
                ca_date = _row_to_ca_date(dt_val)
                if ca_date is None:
                    continue
                p = _date_to_period(ca_date, aggregation)
                if p == period:
                    filtered.append(sn)
                    break
        candidates = filtered

    # Breakdown bonepile/fresh: filter by is_bonepile
    if metric == "breakdown_bonepile":
        candidates = [sn for sn in candidates if sn_is_bp.get(sn)]
    elif metric == "breakdown_fresh":
        candidates = [sn for sn in candidates if not sn_is_bp.get(sn)]

    # Test flow: filter by station + outcome when both provided
    if station and outcome:
        st = _norm(station)
        want_pf = "P" if outcome == "pass" else "F"
        filtered = []
        for sn in candidates:
            tests = sn_tests.get(sn) or []
            for r in tests:
                if _norm(r.get("station")) != st:
                    continue
                res = _norm(r.get("result"))
                if (want_pf == "P" and res == "PASS") or (want_pf == "F" and res == "FAIL"):
                    filtered.append(sn)
                    break
        candidates = filtered
        if sku and sku != "__TOTAL__":
            candidates = [sn for sn in candidates if (sn_latest_part.get(sn) or "Unknown") == sku]

    out = [make_sn_item(sn) for sn in sorted(candidates)]
    return out
