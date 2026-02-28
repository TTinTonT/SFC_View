# -*- coding: utf-8 -*-
"""Error stats: fail by station, top K errors, station×error matrix, TTC buckets."""
from __future__ import annotations

import hashlib
import statistics
from typing import Any, Dict, List, Optional, Tuple

from config.app_config import STATIONS_ORDER
from config.analytics_config import get_error_stats_p90, get_error_stats_ttc_buckets


def _norm(s: Any) -> str:
    return (str(s) if s is not None else "").strip().upper()


def _station_group(station: str) -> str:
    """R_AST -> AST, R_FLB -> FLB; else return normalized station."""
    st = _norm(station)
    if st.startswith("R_") and len(st) > 2:
        return st[2:]
    return st


def _error_key(row: dict) -> str:
    """Primary: error_code. Fallback: stable key from failure_msg prefix (~80 chars)."""
    ec = (row.get("error_code") or "").strip()
    if ec:
        return _norm(ec)
    msg = (row.get("failure_msg") or "").strip()
    if not msg:
        return "_NO_MSG"
    prefix = msg[:80].strip()
    if len(prefix) < 20:
        return prefix or "_EMPTY"
    h = hashlib.sha256(prefix.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"msg_{h}"


def normalize_rows(rows: List[dict]) -> List[dict]:
    """Add station_group and error_key to each row."""
    out = []
    for r in rows:
        row = dict(r)
        row["station_group"] = _station_group(row.get("station") or "")
        row["error_key"] = _error_key(row)
        out.append(row)
    return out


def _station_sort_key(st: str) -> Tuple[int, str]:
    """Order: STATIONS_ORDER first, then alphabetical."""
    try:
        idx = STATIONS_ORDER.index(st)
        return (0, idx)
    except ValueError:
        return (1, st)


def infer_clear_times(rows: List[dict]) -> List[dict]:
    """
    For each FAIL, set clear_time from next PASS (same tray_sn + station_group) or open=True.
    Mutates rows in place (adds clear_time, open, ttc_minutes); returns normalized rows.
    """
    norm_rows = normalize_rows(rows)
    fail_rows = [r for r in norm_rows if _norm(r.get("result") or "") == "FAIL"]
    pass_rows = [r for r in norm_rows if _norm(r.get("result") or "") == "PASS"]

    # Index PASS by (tray_sn, station_group) -> sorted by test_time_dt
    pass_by_key: Dict[Tuple[str, str], List[dict]] = {}
    for r in pass_rows:
        sn = (r.get("serial_number") or "").strip()
        sg = r.get("station_group") or ""
        if not sn or not sg:
            continue
        k = (sn, sg)
        pass_by_key.setdefault(k, []).append(r)

    for lst in pass_by_key.values():
        lst.sort(key=lambda x: (x.get("test_time_dt") or __import__("datetime").datetime.min))

    for r in fail_rows:
        sn = (r.get("serial_number") or "").strip()
        sg = r.get("station_group") or ""
        fail_time = r.get("test_time_dt")
        r["open"] = True
        r["clear_time"] = None
        r["ttc_minutes"] = None

        if not sn or not sg or fail_time is None:
            continue

        passes = pass_by_key.get((sn, sg)) or []
        for p in passes:
            pt = p.get("test_time_dt")
            if pt and pt > fail_time:
                r["clear_time"] = pt
                r["open"] = False
                delta = (pt - fail_time).total_seconds() / 60.0
                r["ttc_minutes"] = round(delta, 2)
                break

    return norm_rows


def compute_fail_summary_by_station(fail_rows: List[dict]) -> List[dict]:
    """A) Fail summary by station_group."""
    by_st: Dict[str, Dict[str, Any]] = {}
    for r in fail_rows:
        sg = r.get("station_group") or ""
        if not sg:
            continue
        if sg not in by_st:
            by_st[sg] = {"fail_events": 0, "trays": set()}
        by_st[sg]["fail_events"] += 1
        sn = (r.get("serial_number") or "").strip()
        if sn:
            by_st[sg]["trays"].add(sn)

    total = sum(d["fail_events"] for d in by_st.values())
    out = []
    for sg in sorted(by_st.keys(), key=_station_sort_key):
        d = by_st[sg]
        pct = (100.0 * d["fail_events"] / total) if total else 0.0
        out.append({
            "station_group": sg,
            "fail_events": d["fail_events"],
            "unique_tray": len(d["trays"]),
            "pct_fail_events": round(pct, 1),
        })
    return out


def compute_top_k_errors(fail_rows: List[dict], top_k: int) -> List[dict]:
    """B) Top K errors overall. Sort: fail_events desc, unique_tray desc."""
    by_err: Dict[str, Dict[str, Any]] = {}
    for r in fail_rows:
        ek = r.get("error_key") or "_UNK"
        msg = (r.get("failure_msg") or "").strip() or (r.get("error_code") or "")
        if ek not in by_err:
            by_err[ek] = {"fail_events": 0, "trays": set(), "messages": {}}
        by_err[ek]["fail_events"] += 1
        sn = (r.get("serial_number") or "").strip()
        if sn:
            by_err[ek]["trays"].add(sn)
        if msg:
            by_err[ek]["messages"][msg] = by_err[ek]["messages"].get(msg, 0) + 1

    # Station with highest count per error
    by_err_st: Dict[str, Dict[str, int]] = {}
    for r in fail_rows:
        ek = r.get("error_key") or "_UNK"
        sg = r.get("station_group") or ""
        if ek not in by_err_st:
            by_err_st[ek] = {}
        by_err_st[ek][sg] = by_err_st[ek].get(sg, 0) + 1

    rows = []
    for ek, d in by_err.items():
        top_st = ""
        if ek in by_err_st:
            st_counts = by_err_st[ek]
            if st_counts:
                top_st = max(st_counts, key=st_counts.get)
        rep_msg = ""
        if d["messages"]:
            rep_msg = max(d["messages"], key=d["messages"].get)
        rows.append({
            "error_code": ek,
            "representative_error_message": rep_msg,
            "fail_events": d["fail_events"],
            "unique_tray": len(d["trays"]),
            "top_station_group": top_st,
        })

    rows.sort(key=lambda x: (-x["fail_events"], -x["unique_tray"]))
    return rows[:top_k]


def compute_station_error_matrix(
    fail_rows: List[dict],
    top_k_errors: List[dict],
    station_order: List[str],
) -> Tuple[List[dict], List[str]]:
    """C) Station × Error matrix. Returns (rows, top_k_error_codes)."""
    top_codes = [e["error_code"] for e in top_k_errors]
    stations_set = set()
    for r in fail_rows:
        sg = r.get("station_group") or ""
        if sg:
            stations_set.add(sg)
    ordered_stations = sorted(
        [s for s in station_order if s in stations_set],
        key=_station_sort_key,
    )
    others = sorted([s for s in stations_set if s not in station_order])
    all_stations = ordered_stations + others

    # Count by (station, error)
    counts: Dict[Tuple[str, str], int] = {}
    trays: Dict[Tuple[str, str], set] = {}
    for r in fail_rows:
        sg = r.get("station_group") or ""
        ek = r.get("error_key") or ""
        if sg and ek in top_codes:
            k = (sg, ek)
            counts[k] = counts.get(k, 0) + 1
            sn = (r.get("serial_number") or "").strip()
            if sn:
                trays.setdefault(k, set()).add(sn)

    out = []
    for sg in all_stations:
        row = {"station_group": sg}
        for ek in top_codes:
            c = counts.get((sg, ek), 0)
            row[ek] = c
        out.append(row)

    return out, top_codes


def compute_station_instance_hotspots(fail_rows: List[dict]) -> List[dict]:
    """D) Station-instance hot spots (only if station_instance present)."""
    has_instance = any((r.get("station_instance") or "").strip() for r in fail_rows)
    if not has_instance:
        return []

    by_inst: Dict[str, Dict[str, Any]] = {}
    for r in fail_rows:
        si = (r.get("station_instance") or "").strip()
        if not si:
            continue
        sg = r.get("station_group") or ""
        if si not in by_inst:
            by_inst[si] = {"station_group": sg, "fail_events": 0, "trays": set(), "errors": {}}
        by_inst[si]["fail_events"] += 1
        sn = (r.get("serial_number") or "").strip()
        if sn:
            by_inst[si]["trays"].add(sn)
        ek = r.get("error_key") or ""
        if ek:
            by_inst[si]["errors"][ek] = by_inst[si]["errors"].get(ek, 0) + 1

    out = []
    for si, d in by_inst.items():
        top_err = max(d["errors"], key=d["errors"].get) if d["errors"] else ""
        out.append({
            "station_instance": si,
            "station_group": d["station_group"],
            "fail_events": d["fail_events"],
            "unique_tray": len(d["trays"]),
            "top_error_code": top_err,
        })
    out.sort(key=lambda x: -x["fail_events"])
    return out


def _ttc_bucket(minutes: float) -> str:
    buckets = get_error_stats_ttc_buckets()
    b0 = buckets[0] if len(buckets) >= 1 else 5
    b1 = buckets[1] if len(buckets) >= 2 else 15
    b2 = buckets[2] if len(buckets) >= 3 else 60
    if minutes <= b0:
        return "<=5m"
    if minutes <= b1:
        return "5-15m"
    if minutes <= b2:
        return "15-60m"
    return ">60m"


def compute_ttc_overall(resolved_rows: List[dict], open_rows: List[dict]) -> dict:
    """E) TTC summary overall. Open count = unique trays (not raw fail events)."""
    ttc_vals = [r["ttc_minutes"] for r in resolved_rows if r.get("ttc_minutes") is not None]
    buckets = {"<=5m": 0, "5-15m": 0, "15-60m": 0, ">60m": 0}
    for m in ttc_vals:
        buckets[_ttc_bucket(m)] = buckets.get(_ttc_bucket(m), 0) + 1

    open_trays = set()
    for r in open_rows:
        sn = (r.get("serial_number") or "").strip()
        if sn:
            open_trays.add(sn)

    return {
        "resolved_fail_events": len(resolved_rows),
        "open_fail_events": len(open_rows),
        "open_unique_trays": len(open_trays),
        "median_ttc_minutes": round(statistics.median(ttc_vals), 2) if ttc_vals else None,
        "mean_ttc_minutes": round(statistics.mean(ttc_vals), 2) if ttc_vals else None,
        "p90_ttc_minutes": round(
            sorted(ttc_vals)[min(int(len(ttc_vals) * get_error_stats_p90()), len(ttc_vals) - 1)] if ttc_vals else 0,
            2,
        ) if ttc_vals else None,
        "bucket_leq5m": buckets["<=5m"],
        "bucket_5_15m": buckets["5-15m"],
        "bucket_15_60m": buckets["15-60m"],
        "bucket_gt60m": buckets[">60m"],
    }


def compute_ttc_by_station(
    resolved_rows: List[dict],
    open_rows: List[dict],
    station_order: List[str],
) -> List[dict]:
    """F) TTC by station_group."""
    by_st: Dict[str, List[dict]] = {}
    for r in resolved_rows:
        sg = r.get("station_group") or ""
        if sg:
            by_st.setdefault(sg, []).append(r)
    for r in open_rows:
        sg = r.get("station_group") or ""
        if sg:
            lst = by_st.setdefault(sg, [])
            lst.append(r)

    stations_set = set(by_st.keys())
    ordered = sorted([s for s in station_order if s in stations_set], key=_station_sort_key)
    others = sorted([s for s in stations_set if s not in station_order])
    all_st = ordered + others

    out = []
    for sg in all_st:
        rows = by_st.get(sg) or []
        with_ttc = [r for r in rows if r.get("ttc_minutes") is not None]
        open_rows = [r for r in rows if r.get("open", False)]
        open_count = len(set((r.get("serial_number") or "").strip() for r in open_rows if (r.get("serial_number") or "").strip()))
        ttc_vals = [r["ttc_minutes"] for r in with_ttc]
        total_ttc = sum(ttc_vals)
        out.append({
            "station_group": sg,
            "resolved_count": len(with_ttc),
            "open_count": open_count,
            "median_ttc": round(statistics.median(ttc_vals), 2) if ttc_vals else None,
            "mean_ttc": round(statistics.mean(ttc_vals), 2) if ttc_vals else None,
            "max_ttc": round(max(ttc_vals), 2) if ttc_vals else None,
            "total_ttc_minutes": round(total_ttc, 2),
        })
    return out


def compute_ttc_by_error(
    resolved_rows: List[dict],
    top_k_errors: List[dict],
) -> List[dict]:
    """G) TTC by error_code (Top K or all)."""
    top_codes = {e["error_code"] for e in top_k_errors}
    by_err: Dict[str, List[dict]] = {}
    for r in resolved_rows:
        ek = r.get("error_key") or ""
        if ek in top_codes:
            by_err.setdefault(ek, []).append(r)

    out = []
    for ek in top_k_errors:
        code = ek["error_code"]
        rows = by_err.get(code) or []
        with_ttc = [r for r in rows if r.get("ttc_minutes") is not None]
        ttc_vals = [r["ttc_minutes"] for r in with_ttc]
        total_ttc = sum(ttc_vals)
        out.append({
            "error_code": code,
            "resolved_count": len(with_ttc),
            "median_ttc": round(statistics.median(ttc_vals), 2) if ttc_vals else None,
            "total_ttc_minutes": round(total_ttc, 2),
        })
    return out


def compute_error_stats(rows: List[dict], top_k: int = 5) -> Dict[str, Any]:
    """Main entry: compute all tables A-G."""
    norm = infer_clear_times(rows)
    fail_rows = [r for r in norm if _norm(r.get("result") or "") == "FAIL"]
    resolved = [r for r in fail_rows if not r.get("open") and r.get("ttc_minutes") is not None]
    open_fails = [r for r in fail_rows if r.get("open")]

    top_k_errors = compute_top_k_errors(fail_rows, top_k)
    station_order = list(STATIONS_ORDER)

    fail_by_station = compute_fail_summary_by_station(fail_rows)
    matrix_rows, matrix_cols = compute_station_error_matrix(fail_rows, top_k_errors, station_order)
    station_instance = compute_station_instance_hotspots(fail_rows)
    ttc_overall = compute_ttc_overall(resolved, open_fails)
    ttc_by_station = compute_ttc_by_station(resolved, open_fails, station_order)
    ttc_by_error = compute_ttc_by_error(resolved, top_k_errors)

    return {
        "fail_by_station": fail_by_station,
        "top_k_errors": top_k_errors,
        "station_error_matrix": matrix_rows,
        "station_error_matrix_cols": matrix_cols,
        "station_instance_hotspots": station_instance,
        "ttc_overall": ttc_overall,
        "ttc_by_station": ttc_by_station,
        "ttc_by_error": ttc_by_error,
        "_fail_rows": fail_rows,
        "_top_k": top_k,
    }


def compute_error_stats_sn_list(
    result: Dict[str, Any],
    metric: str,
    station_group: Optional[str] = None,
    error_code: Optional[str] = None,
    ttc_bucket: Optional[str] = None,
    station_instance: Optional[str] = None,
    drill_type: Optional[str] = None,
) -> List[dict]:
    """Drill-down: return FAIL records matching metric filters."""
    fail_rows = result.get("_fail_rows") or []
    out = []
    for r in fail_rows:
        if metric == "fail_by_station":
            if (station_group or "").strip() and r.get("station_group") != _norm(station_group or ""):
                continue
        elif metric == "top_errors":
            if (error_code or "").strip() and r.get("error_key") != _norm(error_code or ""):
                continue
        elif metric == "station_error":
            if (station_group or "").strip() and r.get("station_group") != _norm(station_group or ""):
                continue
            if (error_code or "").strip() and r.get("error_key") != _norm(error_code or ""):
                continue
        elif metric == "station_instance":
            si = (r.get("station_instance") or "").strip()
            want_si = (station_instance or "").strip()
            if not want_si or si != want_si:
                continue
        elif metric == "ttc_overall":
            if ttc_bucket:
                if ttc_bucket == "open":
                    if not r.get("open"):
                        continue
                    # Open drill-down: return one row per unique tray with last error (handled below)
                elif ttc_bucket == "resolved":
                    if r.get("open") or r.get("ttc_minutes") is None:
                        continue
                else:
                    if r.get("open") or r.get("ttc_minutes") is None:
                        continue
                    b = _ttc_bucket(r["ttc_minutes"])
                    if b != ttc_bucket:
                        continue
            else:
                pass
        elif metric == "ttc_by_station":
            if (station_group or "").strip() and r.get("station_group") != _norm(station_group or ""):
                continue
            if r.get("open") or r.get("ttc_minutes") is None:
                continue
        elif metric == "ttc_by_station_open":
            if (station_group or "").strip() and r.get("station_group") != _norm(station_group or ""):
                continue
            if not r.get("open"):
                continue
        elif metric == "ttc_by_error":
            if (error_code or "").strip() and r.get("error_key") != _norm(error_code or ""):
                continue
            if r.get("open") or r.get("ttc_minutes") is None:
                continue
        else:
            continue

        out.append({
            "sn": (r.get("serial_number") or "").strip(),
            "part_number": (r.get("part_number") or "").strip(),
            "station": (r.get("station") or "").strip(),
            "station_group": r.get("station_group") or "",
            "error_code": r.get("error_key") or "",
            "error_message": (r.get("failure_msg") or "").strip(),
            "test_time": (r.get("test_time") or "").strip(),
            "ttc_minutes": r.get("ttc_minutes"),
            "open": r.get("open"),
            "_test_time_dt": r.get("test_time_dt"),
        })
    # Unique trays: one row per unique SN with last error (fail_by_station, top_errors, station_instance)
    unique_trays = (drill_type or "").strip().lower() == "unique_trays"
    if unique_trays and metric in ("fail_by_station", "top_errors", "station_instance") and out:
        by_sn: Dict[str, dict] = {}
        for row in out:
            sn = row.get("sn") or ""
            if not sn:
                continue
            dt = row.get("_test_time_dt")
            existing = by_sn.get(sn)
            if existing is None or (dt and (existing.get("_test_time_dt") or __import__("datetime").datetime.min) < dt):
                r2 = {k: v for k, v in row.items() if k != "_test_time_dt"}
                r2["_test_time_dt"] = dt
                by_sn[sn] = r2
        out = [{"sn": r["sn"], "part_number": r["part_number"], "station": r["station"],
                "error_code": r["error_code"], "error_message": r["error_message"],
                "test_time": r["test_time"]} for r in by_sn.values()]
    # Open drill-down: one row per unique tray with last error (ttc_overall open or ttc_by_station_open)
    elif (metric == "ttc_overall" and ttc_bucket == "open" or metric == "ttc_by_station_open") and out:
        by_sn: Dict[str, dict] = {}
        for row in out:
            sn = row.get("sn") or ""
            if not sn:
                continue
            dt = row.get("_test_time_dt")
            existing = by_sn.get(sn)
            if existing is None or (dt and (existing.get("_test_time_dt") or __import__("datetime").datetime.min) < dt):
                r2 = {k: v for k, v in row.items() if k != "_test_time_dt"}
                r2["_test_time_dt"] = dt
                by_sn[sn] = r2
        out = [{"sn": r["sn"], "part_number": r["part_number"], "station": r["station"],
                "error_code": r["error_code"], "error_message": r["error_message"],
                "test_time": r["test_time"]} for r in by_sn.values()]
    else:
        out = [{k: v for k, v in row.items() if k != "_test_time_dt"} for row in out]
    return out
