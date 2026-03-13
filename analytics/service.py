# -*- coding: utf-8 -*-
"""
Analytics service: run query, SN list, error stats.
Plain functions; no Flask. Used by app routes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sfc.client import request_fail_result
from sfc.parser import parse_fail_result_html

from crabber.client import get_sn_tier_from_crabber
from analytics.compute import compute_all
from analytics.error_stats import compute_error_stats, compute_error_stats_sn_list
from analytics.sn_list import compute_sn_list


def _filter_rows_by_valid_sns(rows: List[dict]) -> Tuple[List[dict], List[str]]:
    """Classify SNs via Crabber (station FVT->L11, SYSTEM->L10). Return (filtered_rows, l11_sns)."""
    unique_sns = {
        (r.get("serial_number") or "").strip()
        for r in rows
        if (r.get("serial_number") or "").strip()
    }
    valid_sns = set()
    l11_sns = set()
    for sn in unique_sns:
        tier = get_sn_tier_from_crabber(sn)
        if tier == "L10":
            valid_sns.add(sn)
        elif tier == "L11":
            l11_sns.add(sn)
    filtered = [
        r for r in rows
        if (r.get("serial_number") or "").strip() in valid_sns
    ]
    return (filtered, sorted(l11_sns))


def run_fail_result_rows(
    user_start: datetime,
    user_end: datetime,
) -> Dict[str, Any]:
    """Fetch SFC fail result and parse to rows. No BP or analytics computed. Returns {"rows": ..., "l11_sns": ...}."""
    ok, html = request_fail_result(user_start, user_end)
    if not ok:
        raise RuntimeError("SFC API request failed (login or fail_result)")
    rows = parse_fail_result_html(html, user_start=user_start, user_end=user_end)
    filtered, l11 = _filter_rows_by_valid_sns(rows)
    return {"rows": filtered, "l11_sns": l11}


def run_analytics_query(
    user_start: datetime,
    user_end: datetime,
    aggregation: str = "daily",
) -> Dict[str, Any]:
    """
    Fetch SFC fail result, parse HTML, compute analytics.
    Returns computed dict (summary, tray_summary, sku_rows, breakdown_rows, test_flow, rows, etc.).
    """
    ok, html = request_fail_result(user_start, user_end)
    if not ok:
        raise RuntimeError("SFC API request failed (login or fail_result)")
    rows = parse_fail_result_html(html, user_start=user_start, user_end=user_end)
    filtered, l11 = _filter_rows_by_valid_sns(rows)
    result = compute_all(filtered, aggregation=aggregation)
    result["l11_sns"] = l11
    return result


def get_sn_list(
    computed: Dict[str, Any],
    metric: str = "total",
    sku: Optional[str] = None,
    period: Optional[str] = None,
    station: Optional[str] = None,
    outcome: Optional[str] = None,
    aggregation: str = "daily",
) -> List[Dict[str, Any]]:
    """Return SN list rows for the given metric/filters from a computed result."""
    return compute_sn_list(
        computed,
        metric=metric,
        sku=sku,
        period=period,
        station=station,
        outcome=outcome,
        aggregation=aggregation,
    )


def run_error_stats(
    user_start: datetime,
    user_end: datetime,
    top_k: int = 5,
) -> Dict[str, Any]:
    """
    Fetch SFC fail result, parse, compute error stats.
    Returns result dict (top_k_errors, fail_by_station, ttc_*, etc.).
    """
    ok, html = request_fail_result(user_start, user_end)
    if not ok:
        raise RuntimeError("SFC API request failed (login or fail_result)")
    rows = parse_fail_result_html(html, user_start=user_start, user_end=user_end)
    filtered, l11 = _filter_rows_by_valid_sns(rows)
    result = compute_error_stats(filtered, top_k=top_k)
    result["l11_sns"] = l11
    return result


def get_error_stats_sn_list(
    result: Dict[str, Any],
    metric: str = "",
    station_group: Optional[str] = None,
    error_code: Optional[str] = None,
    ttc_bucket: Optional[str] = None,
    station_instance: Optional[str] = None,
    drill_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return SN list rows for error-stats drill-down."""
    return compute_error_stats_sn_list(
        result,
        metric=metric,
        station_group=station_group,
        error_code=error_code,
        ttc_bucket=ttc_bucket,
        station_instance=station_instance,
        drill_type=drill_type,
    )
