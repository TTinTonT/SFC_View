# -*- coding: utf-8 -*-
"""
Compute analytics from SFC rows: summary, tray_summary, sku_rows,
breakdown_rows, test_flow.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from config.app_config import CA_TZ, STATIONS_ORDER
from analytics.pass_fail import is_sn_passed
from analytics.bp_check import add_bp_to_rows


def _norm(s: Any) -> str:
    return (str(s) if s is not None else "").strip().upper()


def _ts_group_from_part_number(part_number: str) -> str:
    pn = "" if part_number is None else str(part_number).upper()
    m = re.search(r"\bTS(\d+)\b", pn)
    if m:
        return f"TS{int(m.group(1))}"
    return "TS?"


def _row_to_ca_date(dt: Optional[datetime]) -> Optional[date]:
    """Convert naive datetime to CA date (assume CA local)."""
    if dt is None:
        return None
    if CA_TZ:
        try:
            ca_dt = CA_TZ.localize(dt)
            return ca_dt.date()
        except Exception:
            return dt.date()
    return dt.date()


def _date_to_period(d: date, aggregation: str) -> str:
    if aggregation == "monthly":
        return d.strftime("%Y-%m")
    if aggregation == "weekly":
        days_since_sunday = (d.weekday() + 1) % 7
        week_start = d - timedelta(days=days_since_sunday)
        week_end = week_start + timedelta(days=6)
        return f"{week_start.strftime('%Y-%m-%d')}~{week_end.strftime('%Y-%m-%d')}"
    return d.strftime("%Y-%m-%d")


def _row_result_to_pf(result: str) -> Optional[str]:
    """Map SFC RESULT (PASS/FAIL) to P/F for test_flow compatibility."""
    r = _norm(result)
    if r == "PASS":
        return "P"
    if r == "FAIL":
        return "F"
    return None


def compute_all(
    rows: List[dict],
    aggregation: str = "daily",
) -> Dict[str, Any]:
    """
    Compute full analytics from SFC rows.
    Rows must have: serial_number, part_number, station, result, test_time_dt.
    Adds is_bonepile to each row.
    """
    if not rows:
        return _empty_result(aggregation)

    rows = add_bp_to_rows(rows)

    # Group by SN
    sn_tests: Dict[str, List[dict]] = {}
    for r in rows:
        sn = (r.get("serial_number") or "").strip()
        if not sn:
            continue
        sn_tests.setdefault(sn, []).append(r)

    sn_is_bp: Dict[str, bool] = {}
    sn_pass: Dict[str, bool] = {}
    sn_latest_part: Dict[str, str] = {}
    sn_latest_dt: Dict[str, Optional[datetime]] = {}

    for sn, tests in sn_tests.items():
        is_bp = any(r.get("is_bonepile") for r in tests)
        sn_is_bp[sn] = is_bp
        sn_pass[sn] = is_sn_passed(tests)
        best_dt: Optional[datetime] = None
        best_pn = "Unknown"
        for r in tests:
            dt_val = r.get("test_time_dt")
            if dt_val is not None:
                if best_dt is None or dt_val > best_dt:
                    best_dt = dt_val
                    best_pn = (r.get("part_number") or "").strip() or "Unknown"
        sn_latest_part[sn] = best_pn
        sn_latest_dt[sn] = best_dt

    tested_total = len(sn_tests)
    pass_total = sum(1 for v in sn_pass.values() if v)
    fail_total = tested_total - pass_total

    tested_bp = sum(1 for v in sn_is_bp.values() if v)
    tested_fresh = tested_total - tested_bp
    pass_bp = sum(1 for sn in sn_tests if sn_is_bp.get(sn) and sn_pass.get(sn))
    pass_fresh = pass_total - pass_bp
    fail_bp = tested_bp - pass_bp
    fail_fresh = tested_fresh - pass_fresh

    summary = {"total": tested_total, "pass": pass_total, "fail": fail_total}

    tray_summary = {
        "tested": {"bp": tested_bp, "fresh": tested_fresh, "total": tested_total},
        "pass": {"bp": pass_bp, "fresh": pass_fresh, "total": pass_total},
        "fail": {"bp": fail_bp, "fresh": fail_fresh, "total": fail_total},
    }

    # SKU rows
    sku_stats: Dict[str, Dict[str, int]] = {}
    for sn in sn_tests:
        sku = sn_latest_part.get(sn, "Unknown") or "Unknown"
        sku_stats.setdefault(sku, {"pass": 0, "fail": 0, "tested": 0})
        sku_stats[sku]["tested"] += 1
        if sn_pass.get(sn):
            sku_stats[sku]["pass"] += 1
        else:
            sku_stats[sku]["fail"] += 1
    sku_rows = [
        {"sku": sku, "tested": s["tested"], "pass": s["pass"], "fail": s["fail"]}
        for sku, s in sku_stats.items()
    ]
    sku_rows.sort(key=lambda x: (-x["tested"], x["sku"]))

    # Breakdown per period
    bucket_sn_tests: Dict[str, Dict[str, List[dict]]] = {}
    for r in rows:
        sn = (r.get("serial_number") or "").strip()
        if not sn:
            continue
        dt_val = r.get("test_time_dt")
        if dt_val is None:
            continue
        ca_date = _row_to_ca_date(dt_val)
        if ca_date is None:
            continue
        period = _date_to_period(ca_date, aggregation)
        bucket_sn_tests.setdefault(period, {}).setdefault(sn, []).append(r)

    breakdown_rows: List[Dict[str, Any]] = []
    for period, sn_map in bucket_sn_tests.items():
        tested = len(sn_map)
        passed = sum(1 for sn, tests in sn_map.items() if is_sn_passed(tests))
        bp = sum(1 for sn, tests in sn_map.items() if any(t.get("is_bonepile") for t in tests))
        fresh = tested - bp
        pass_rate = (passed / tested) if tested else 0.0
        breakdown_rows.append({
            "period": period,
            "tested": tested,
            "passed": passed,
            "bonepile": bp,
            "fresh": fresh,
            "pass_rate": pass_rate,
        })
    breakdown_rows.sort(key=lambda x: x["period"])

    # Test flow
    stations = list(STATIONS_ORDER)
    total_sets: Dict[str, Dict[str, set]] = {st: {"pass": set(), "fail": set()} for st in stations}
    sku_sets: Dict[str, Dict[str, Dict[str, set]]] = {}

    for sn, tests in sn_tests.items():
        sku = sn_latest_part.get(sn, "Unknown") or "Unknown"
        sku_sets.setdefault(sku, {st: {"pass": set(), "fail": set()} for st in stations})
        for r in tests:
            st = _norm(r.get("station") or "")
            if st not in total_sets:
                continue
            pf = _row_result_to_pf(r.get("result") or "")
            if pf == "P":
                total_sets[st]["pass"].add(sn)
                sku_sets[sku][st]["pass"].add(sn)
            elif pf == "F":
                total_sets[st]["fail"].add(sn)
                sku_sets[sku][st]["fail"].add(sn)

    totals = {
        st: {"pass": len(total_sets[st]["pass"]), "fail": len(total_sets[st]["fail"])}
        for st in stations
    }

    def ts_sort_key(ts: str) -> Tuple[int, int]:
        m = re.match(r"TS(\d+)$", ts)
        if m:
            return (0, int(m.group(1)))
        return (1, 999)

    test_flow_rows: List[Dict[str, Any]] = []
    for sku in sorted(sku_sets.keys()):
        ts = _ts_group_from_part_number(sku)
        test_flow_rows.append({
            "ts": ts,
            "sku": sku,
            "stations": {
                st: {"pass": len(sku_sets[sku][st]["pass"]), "fail": len(sku_sets[sku][st]["fail"])}
                for st in stations
            },
        })
    test_flow_rows.sort(key=lambda r: (ts_sort_key(r["ts"]), r["sku"]))

    test_flow = {"stations": stations, "totals": totals, "rows": test_flow_rows}

    return {
        "summary": summary,
        "tray_summary": tray_summary,
        "sku_rows": sku_rows,
        "breakdown_rows": breakdown_rows,
        "test_flow": test_flow,
        "rows": rows,
        "_sn_tests": sn_tests,
        "_sn_pass": sn_pass,
        "_sn_is_bp": sn_is_bp,
        "_sn_latest_part": sn_latest_part,
        "_sn_latest_dt": sn_latest_dt,
    }


def _empty_result(aggregation: str) -> Dict[str, Any]:
    return {
        "summary": {"total": 0, "pass": 0, "fail": 0},
        "tray_summary": {
            "tested": {"bp": 0, "fresh": 0, "total": 0},
            "pass": {"bp": 0, "fresh": 0, "total": 0},
            "fail": {"bp": 0, "fresh": 0, "total": 0},
        },
        "sku_rows": [],
        "breakdown_rows": [],
        "test_flow": {
            "stations": list(STATIONS_ORDER),
            "totals": {st: {"pass": 0, "fail": 0} for st in STATIONS_ORDER},
            "rows": [],
        },
        "rows": [],
        "_sn_tests": {},
        "_sn_pass": {},
        "_sn_is_bp": {},
        "_sn_latest_part": {},
        "_sn_latest_dt": {},
    }
