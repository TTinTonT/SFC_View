# -*- coding: utf-8 -*-
"""L11 analytics: pass_station from Jump IT route (station before T_VI)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

T_VI = "T_VI"


def _get_route_for_sn(sn: str) -> Tuple[Optional[str], List[Tuple[int, str]]]:
    """
    Get pass_station and list of (step, group_name) for station order.
    Returns (pass_station or None, [(step, group_name), ...]).
    """
    if not (sn or "").strip():
        return None, []
    sn = sn.strip().upper()
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.jump_route import get_route_list
        conn = get_conn()
        try:
            cols, rows = get_route_list(conn, sn)
            if not rows or not cols:
                return None, []
            col_upper = {c.upper(): i for i, c in enumerate(cols)}
            idx_gn = col_upper.get("GROUP_NAME")
            idx_next = col_upper.get("GROUP_NEXT")
            idx_step = col_upper.get("STEP")
            if idx_gn is None or idx_next is None:
                return None, []
            pass_station = None
            steps: List[Tuple[int, str]] = []
            for row in rows:
                step = int(row[idx_step]) if idx_step is not None and row[idx_step] is not None else len(steps)
                gn = (row[idx_gn] or "").strip().upper()
                if gn:
                    steps.append((step, gn))
                group_next = (row[idx_next] or "").strip().upper()
                if group_next == T_VI:
                    pass_station = gn or None
            return pass_station, steps
        finally:
            conn.close()
    except Exception:
        return None, []


def get_l11_pass_station(sn: str) -> Optional[str]:
    """
    Return the pass station for L11 SN: GROUP_NAME of the step where GROUP_NEXT = T_VI.
    Uses sfis_tool get_route_list. Returns None if no route or no T_VI in route.
    """
    pass_station, _ = _get_route_for_sn(sn)
    return pass_station


def compute_l11_sn_pass_map(l11_sns: List[str]) -> Dict[str, str]:
    """
    For each SN in l11_sns, get pass_station (group_name where group_next = T_VI).
    Only SNs with a valid pass_station are included. One call per unique SN.
    """
    result: Dict[str, str] = {}
    for sn in l11_sns:
        if not (sn or "").strip():
            continue
        sn = sn.strip().upper()
        if sn in result:
            continue
        ps = get_l11_pass_station(sn)
        if ps:
            result[sn] = ps
    return result


def compute_l11_sn_pass_map_and_stations(l11_sns: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """
    Same as compute_l11_sn_pass_map but also returns stations_order_l11:
    unique GROUP_NAME from all routes, ordered by min STEP across routes.
    Returns (sn -> pass_station, ordered list of station names).
    """
    pass_map: Dict[str, str] = {}
    step_min: Dict[str, int] = {}
    for sn in l11_sns:
        if not (sn or "").strip():
            continue
        sn = sn.strip().upper()
        if sn in pass_map:
            continue
        ps, steps = _get_route_for_sn(sn)
        if ps:
            pass_map[sn] = ps
        for step, gn in steps:
            if gn and (gn not in step_min or step < step_min[gn]):
                step_min[gn] = step
    stations_order = sorted(step_min.keys(), key=lambda g: step_min[g])
    return pass_map, stations_order
