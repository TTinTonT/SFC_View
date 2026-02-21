# -*- coding: utf-8 -*-
"""
FA Debug logic: aggregate rows for KPIs and timeline.
Rows come from parse_fail_result_html; compute_all provides summary.
"""

from datetime import datetime
from typing import Any, Dict, List

from analytics.bp_check import add_bp_to_rows


def prepare_debug_rows(rows: List[dict]) -> List[dict]:
    """
    Add is_bonepile, sort by test_time_dt desc (newest first).
    Returns list suitable for timeline and drill-down.
    """
    rows = add_bp_to_rows(rows)
    out = [r for r in rows if r.get("test_time_dt") is not None]
    out.sort(key=lambda r: r["test_time_dt"] or datetime.min, reverse=True)
    return out
