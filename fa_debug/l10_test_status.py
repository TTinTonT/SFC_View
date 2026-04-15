# -*- coding: utf-8 -*-
"""L10 tray dashboard: classify SFC Test_Fixture_Status rows and group by test base (Fixture_No)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

UiBucket = Literal["idle", "testing", "testing_pass", "testing_fail", "on_hold", "unknown"]


def norm_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def is_na_group(group: str) -> bool:
    g = norm_str(group).upper()
    return g in ("", "N/A", "NA", "-")


def norm_status_upper(v: Any) -> str:
    return norm_str(v).upper().replace(" ", "_")


def classify_tray(item: Dict[str, Any]) -> UiBucket:
    """Classify one SFC DATA row. Priority top-to-bottom; first match wins."""
    remark = norm_str(item.get("Remark"))
    if remark:
        return "on_hold"

    status = norm_status_upper(item.get("Status"))
    group_na = is_na_group(item.get("Group_Name"))

    pass_statuses = {"PASS", "ALL_PASS", "PASSED", "PASS_ALL"}
    if status in pass_statuses and not group_na:
        return "testing_pass"

    fail_statuses = {"FAIL", "FAILED"}
    if status in fail_statuses and not group_na:
        return "testing_fail"

    if status == "VERIFY":
        return "testing"
    if status == "EMPTY" and not group_na:
        return "testing"

    if status == "EMPTY" and group_na and not remark:
        return "idle"

    return "unknown"


def _slot_sort_key(slot_no: str) -> Tuple[int, str]:
    s = norm_str(slot_no)
    digits = re.sub(r"\D", "", s)
    if digits:
        try:
            return (int(digits), s)
        except ValueError:
            pass
    return (10**9, s)


def _fixture_sort_key(fixture_no: str) -> Tuple[int, int, str]:
    """Sort MTF 1, MTF 9, MTF 10, MTF 16."""
    s = norm_str(fixture_no).upper()
    m = re.search(r"(\d+)\s*$", s)
    num = int(m.group(1)) if m else 10**9
    prefix = 0 if "MTF" in s else 1
    return (prefix, num, s)


def tray_row_from_sfc(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one SFC row to API JSON (snake_case) + ui_bucket."""
    ui_bucket = classify_tray(item)
    return {
        "fixture_no": norm_str(item.get("Fixture_No")) or None,
        "slot_no": norm_str(item.get("Slot_No")) or None,
        "serial_number": item.get("Serial_Number"),
        "build_phase": norm_str(item.get("Build_Phase")) or None,
        "group_name": norm_str(item.get("Group_Name")) or None,
        "status": norm_str(item.get("Status")) or None,
        "last_end_time": norm_str(item.get("Last_End_Time")) or None,
        "error_desc": norm_str(item.get("Error_Desc")) or None,
        "remark": norm_str(item.get("Remark")) or None,
        "ui_bucket": ui_bucket,
    }


def group_fixtures_from_sfc_payload(payload: Union[Dict[str, Any], List[Any], None]) -> List[Dict[str, Any]]:
    """
    Parse SFC JSON body (dict with DATA list). Return sorted list of:
    { "fixture_no": str, "slots": [ tray_row, ... ] }
    """
    if not isinstance(payload, dict):
        return []

    raw_list = payload.get("DATA")
    if not isinstance(raw_list, list):
        return []

    by_fixture: Dict[str, List[Dict[str, Any]]] = {}
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        fn = norm_str(item.get("Fixture_No"))
        if not fn:
            fn = "(unknown)"
        by_fixture.setdefault(fn, []).append(tray_row_from_sfc(item))

    fixtures: List[Dict[str, Any]] = []
    for fixture_no in sorted(by_fixture.keys(), key=_fixture_sort_key):
        slots = by_fixture[fixture_no]
        slots.sort(key=lambda r: _slot_sort_key(r.get("slot_no") or ""))
        fixtures.append({"fixture_no": fixture_no, "slots": slots})

    return fixtures


def sort_slots_for_display(slots: List[Dict[str, Any]], expanded: bool) -> List[Dict[str, Any]]:
    """When expanded, non-idle first by slot then idle; when collapsed order unchanged (caller filters)."""
    if not expanded:
        return list(slots)

    def bucket_order(b: str) -> int:
        return 0 if b != "idle" else 1

    return sorted(
        slots,
        key=lambda r: (bucket_order(r.get("ui_bucket") or ""), _slot_sort_key(r.get("slot_no") or "")),
    )
