# -*- coding: utf-8 -*-
"""Pass station by part number; uses analytics_config pass_rules."""

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
    Return True if SN has at least one row with RESULT=PASS and station
    matching the pass rule for that row's part_number.
    SFC uses result="PASS"/"FAIL" (not P/F).
    """
    for r in rows_for_sn:
        result = (r.get("result") or "").strip().upper()
        if result != "PASS":
            continue
        station = (r.get("station") or "").strip().upper()
        part_number = (r.get("part_number") or "").strip()
        if not part_number or part_number.upper() == "UNKNOWN":
            continue
        pass_station = get_pass_station_for_part_number(part_number)
        if station == pass_station:
            return True
    return False
