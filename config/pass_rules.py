# -*- coding: utf-8 -*-
"""Pass station by part number; uses analytics_config pass_rules."""

from datetime import datetime
from typing import List

from config.analytics_config import get_pass_rules


def get_pass_station_for_part_number(part_number: str) -> str:
    """
    Return the station where a part number is considered "passed".
    - If part number is in a station's list -> that station
    - If not in any list -> unknown_station (default RIN)
    """
    pn = "" if part_number is None else str(part_number).strip().upper()
    if not pn or pn == "UNKNOWN":
        rules = get_pass_rules()
        return (rules.get("unknown_station") or "RIN").strip().upper()

    rules = get_pass_rules()
    unknown = (rules.get("unknown_station") or "RIN").strip().upper()
    for station, pns in rules.items():
        if station == "unknown_station":
            continue
        if isinstance(pns, list):
            for x in pns:
                if (x or "").strip().upper() == pn:
                    return station.strip().upper()
    return unknown


def is_sn_passed(rows_for_sn: List[dict]) -> bool:
    """
    Return True if the LATEST test (by test_time_dt) is PASS at the pass station.
    - Latest test FAIL -> FAIL
    - Latest test PASS but at wrong station (not pass rule for part) -> FAIL
    - Latest test PASS at pass station -> PASS
    SFC uses result="PASS"/"FAIL" (not P/F).
    """
    if not rows_for_sn:
        return False
    latest = max(
        rows_for_sn,
        key=lambda r: r.get("test_time_dt") or datetime.min,
    )
    result = (latest.get("result") or "").strip().upper()
    if result != "PASS":
        return False
    station = (latest.get("station") or "").strip().upper()
    part_number = (latest.get("part_number") or "").strip()
    pass_station = get_pass_station_for_part_number(part_number)
    return station == pass_station
