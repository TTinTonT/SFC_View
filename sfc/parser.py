# -*- coding: utf-8 -*-
"""Parse SFC fail_result HTML to rows; filter by user time range; add test_time_dt."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, List, Optional

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore

IDX_SERIAL = 1
IDX_MO = 2
IDX_MODEL = 4
IDX_STATION = 5
IDX_TEST_TIME = 7
IDX_RESULT = 8
IDX_ERROR_CODE = 9  # optional; fallback to failure_msg hash in error_stats
IDX_FAILURE_MSG = 10
IDX_CURRENT_STATION = 18
IDX_STATION_INSTANCE = 19  # optional; e.g. AST_170, FLB_185


def _normalize_mo(mo: str) -> str:
    """000007019042-1 -> 7019042."""
    if not mo or not isinstance(mo, str):
        return ""
    s = mo.strip()
    if "-" in s:
        s = s.split("-")[0]
    s = s.lstrip("0") or "0"
    try:
        return str(int(s))
    except ValueError:
        return mo.strip()


def _cell_text(td) -> str:
    if td is None:
        return ""
    text = td.get_text(strip=True) if hasattr(td, "get_text") else str(td)
    return (text.replace("\xa0", " ").replace("&nbsp;", " ").strip() or "").strip()


def _parse_test_time(s: str) -> Optional[datetime]:
    """Parse '2026/02/09 00:46:40' to datetime (naive)."""
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_fail_result_html(
    html: str,
    user_start: Optional[datetime] = None,
    user_end: Optional[datetime] = None,
) -> List[dict]:
    """
    Parse fail_result HTML table into list of dicts.
    If user_start/user_end are set, only include rows where TEST TIME is in [user_start, user_end].
    Each row includes test_time_dt (datetime) for compute.
    """
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required; pip install beautifulsoup4")

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    rows = table.find_all("tr")
    out: List[dict] = []
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) <= IDX_CURRENT_STATION:
            continue
        first_text = _cell_text(tds[0]) if tds else ""
        if first_text.strip().upper() in ("#", "SERIAL NUMBER"):
            continue

        serial = _cell_text(tds[IDX_SERIAL])
        mo_raw = _cell_text(tds[IDX_MO])
        work_order = _normalize_mo(mo_raw)
        part_number = _cell_text(tds[IDX_MODEL])
        station = _cell_text(tds[IDX_STATION])
        test_time_str = _cell_text(tds[IDX_TEST_TIME])
        result = _cell_text(tds[IDX_RESULT])
        error_code = _cell_text(tds[IDX_ERROR_CODE]) if len(tds) > IDX_ERROR_CODE else ""
        failure_msg = _cell_text(tds[IDX_FAILURE_MSG])
        current_station = _cell_text(tds[IDX_CURRENT_STATION])
        station_instance = _cell_text(tds[IDX_STATION_INSTANCE]) if len(tds) > IDX_STATION_INSTANCE else ""

        test_time_dt = _parse_test_time(test_time_str)
        if user_start is not None and user_end is not None and test_time_dt is not None:
            if test_time_dt < user_start or test_time_dt > user_end:
                continue

        out.append({
            "serial_number": serial,
            "work_order": work_order,
            "part_number": part_number,
            "station": station,
            "test_time": test_time_str,
            "test_time_dt": test_time_dt,
            "result": result,
            "error_code": error_code,
            "failure_msg": failure_msg,
            "current_station": current_station,
            "station_instance": station_instance,
        })
    return out


def rows_to_csv(rows: List[dict], include_bp: bool = False) -> str:
    """Convert list of dicts to CSV string (UTF-8). If include_bp, add BP column."""
    if not rows:
        header = [
            "SERIAL NUMBER", "Work order", "Part number", "STATION",
            "TEST TIME", "RESULT", "FAILURE MSG", "CURRENT STATION",
        ]
        if include_bp:
            header.append("BP")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        return buf.getvalue()

    fieldnames = [
        "serial_number", "work_order", "part_number", "station",
        "test_time", "result", "failure_msg", "current_station",
    ]
    header = [
        "SERIAL NUMBER", "Work order", "Part number", "STATION",
        "TEST TIME", "RESULT", "FAILURE MSG", "CURRENT STATION",
    ]
    if include_bp:
        header.append("BP")
    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        row = [r.get(f, "") for f in fieldnames]
        if include_bp:
            row.append("Yes" if r.get("is_bonepile") else "No")
        w.writerow(row)
    return buf.getvalue()
