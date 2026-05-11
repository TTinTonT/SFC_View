# -*- coding: utf-8 -*-
"""L10 FA Crabber dashboard: group L10 / PROC rows with FA_* machine suffix across SJ + SV."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from crabber.client import normalize_search_log_item_to_row, tier_from_crabber_station

FA_SLOTS_PER_ETF = 13
_FA_SLOT_TAIL_RE = re.compile(r"(?:_FA_|FA_)(\d+)\s*$", re.IGNORECASE)


def parse_global_slot_fa_machine(machine: str) -> Optional[int]:
    """
    Map machine name like VR-...ETF-AST_FA_013 -> global slot index 13.
    Requires substring 'FA' and a trailing FA_<digits> segment.
    Slots 1-13 belong to ETF 1, 14-26 ETF 2, etc. (see build_fa_etf_fixture_list).
    """
    m = (machine or "").strip()
    if "FA" not in m.upper():
        return None
    mo = _FA_SLOT_TAIL_RE.search(m)
    if not mo:
        return None
    try:
        return int(mo.group(1))
    except ValueError:
        return None


def _log_time_sort_key(row: Dict[str, Any]) -> str:
    return str(row.get("log_time") or row.get("test_time") or "")


def iter_fa_l10_proc_normalized_rows_from_items(
    items: Optional[List[Any]],
    *,
    max_scan: int = 800,
) -> List[Dict[str, Any]]:
    """Flatten search_log_items into normalized rows; filter L10 PROC with parsable FA machine slot."""
    out: List[Dict[str, Any]] = []
    if not items:
        return out
    n = 0
    for it in items:
        if n >= max_scan:
            break
        row = normalize_search_log_item_to_row(it)
        if row is None:
            continue
        n += 1
        if str(row.get("node_log_event") or "").strip().upper() != "PROC":
            continue
        if tier_from_crabber_station(str(row.get("station") or "")) != "L10":
            continue
        machine = str(row.get("machine") or "")
        gsi = parse_global_slot_fa_machine(machine)
        if gsi is None:
            continue
        enriched = dict(row)
        enriched["global_slot"] = gsi
        out.append(enriched)
    return out


def dedupe_fa_rows_by_global_slot(rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Keep newest log_time per global_slot."""
    best: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        gs = r.get("global_slot")
        try:
            gi = int(gs)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        prev = best.get(gi)
        if prev is None or _log_time_sort_key(r) > _log_time_sort_key(prev):
            best[gi] = r
    return best


def build_fa_etf_fixture_list(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build [{ fixture_label, etf_index, slots: [...13 cells...] }, ...] sorted by etf_index.
    Each slot: global_slot, slot_within_etf, occupied, plus Crabber fields when occupied.
    """
    by_gs = dedupe_fa_rows_by_global_slot(rows)
    if not by_gs:
        return []

    max_gs = max(by_gs.keys())
    max_etf = (max_gs - 1) // FA_SLOTS_PER_ETF + 1
    fixtures: List[Dict[str, Any]] = []

    for etf_idx in range(1, max_etf + 1):
        slots_out: List[Dict[str, Any]] = []
        for pos in range(1, FA_SLOTS_PER_ETF + 1):
            global_slot = (etf_idx - 1) * FA_SLOTS_PER_ETF + pos
            r = by_gs.get(global_slot)
            if r:
                slots_out.append(
                    {
                        "occupied": True,
                        "etf_index": etf_idx,
                        "global_slot": global_slot,
                        "slot_within_etf": pos,
                        "sn": str(r.get("sn") or "").strip(),
                        "machine": str(r.get("machine") or ""),
                        "station": str(r.get("station") or ""),
                        "result": str(r.get("result") or ""),
                        "log_time": str(r.get("log_time") or ""),
                        "pn_name": str(r.get("pn_name") or ""),
                        "node_log_event": str(r.get("node_log_event") or ""),
                    }
                )
            else:
                slots_out.append(
                    {
                        "occupied": False,
                        "etf_index": etf_idx,
                        "global_slot": global_slot,
                        "slot_within_etf": pos,
                        "sn": "",
                        "machine": "",
                        "station": "",
                        "result": "",
                        "log_time": "",
                        "pn_name": "",
                        "node_log_event": "",
                    }
                )
        fixtures.append(
            {
                "fixture_no": f"FA ETF {etf_idx}",
                "etf_index": etf_idx,
                "slots": slots_out,
            }
        )
    return fixtures
