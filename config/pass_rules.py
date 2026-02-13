# -*- coding: utf-8 -*-
"""
Pass station rules by part number.
Logic from Bonepile_view/analytics_server.py.
"""

from typing import List

# Part numbers that pass at FCT (explicit list)
PASS_AT_FCT_PART_NUMBERS = frozenset({"675-24109-0010-TS2", "675-24109-0020-TS2"})


def get_pass_station_for_part_number(part_number: str) -> str:
    """
    Return the station where a part number is considered "passed".
    - 675-24109-0010-TS2, 675-24109-0020-TS2 -> FCT
    - Part number contains "TS2" -> NVL
    - Others -> FCT
    """
    pn = "" if part_number is None else str(part_number).strip().upper()
    if pn in PASS_AT_FCT_PART_NUMBERS:
        return "FCT"
    if "TS2" in pn:
        return "NVL"
    return "FCT"


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
