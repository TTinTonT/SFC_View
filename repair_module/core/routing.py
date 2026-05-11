# -*- coding: utf-8 -*-
"""Route list and jump-station kitting checks (subset of former jump_route)."""
from repair_module.sql.jump_sql import (
    JUMP_GET_WIP,
    JUMP_GET_ROUTE_LIST,
    JUMP_CHECK_JUMP_STATION,
    JUMP_CHECK_ASSY,
)


def _run_query(conn, sql, params=None):
    cur = conn.cursor()
    try:
        cur.execute(sql, params or [])
        cols = [c[0] for c in cur.description]
        return cols, cur.fetchall()
    finally:
        cur.close()


def get_wip(conn, sn):
    cols, rows = _run_query(conn, JUMP_GET_WIP, {"sn": sn})
    return cols, rows


def get_route_list(conn, sn):
    cols, rows = _run_query(conn, JUMP_GET_ROUTE_LIST, {"sn": sn})
    return cols, rows


def filter_test_stations_between_fillcoolant_tvi(groups_ordered):
    """Route groups after FILL_COOLANT and before T_VI (exclusive)."""
    if not groups_ordered:
        return []
    groups = [(g or "").strip() for g in groups_ordered if (g or "").strip()]
    try:
        fc_idx = groups.index("FILL_COOLANT")
    except ValueError:
        fc_idx = -1
    try:
        tvi_idx = groups.index("T_VI")
    except ValueError:
        tvi_idx = len(groups)
    return groups[fc_idx + 1 : tvi_idx]


def get_station_order_and_next(conn, sn):
    """Return (order, current_group, next_group)."""
    cols, rows = get_route_list(conn, sn)
    if not rows:
        return [], None, None
    order = []
    for row in rows:
        d = dict(zip(cols, row))
        grp = (d.get("GROUP_NAME") or "").strip()
        if grp:
            order.append(grp)
    wip_cols, wip_rows = get_wip(conn, sn)
    current_group = None
    next_group = None
    if wip_rows:
        wip = dict(zip(wip_cols, wip_rows[0]))
        current_group = (wip.get("GROUP_NAME") or "").strip() or None
        if current_group and order:
            try:
                idx = order.index(current_group)
                if idx + 1 < len(order):
                    next_group = order[idx + 1]
            except ValueError:
                pass
    return order, current_group, next_group


def check_jump_station(conn, target_group, sn):
    """CheckJumpStation (ASSY): True = allow jump, False = block."""
    cur = conn.cursor()
    try:
        cur.execute(JUMP_CHECK_JUMP_STATION, {"sn": sn, "g": target_group})
        kitting_rows = cur.fetchall()
        for kr in kitting_rows:
            gname = kr[1] if len(kr) > 1 else kr[0]
            cur.execute(JUMP_CHECK_ASSY, {"sn": sn, "g": gname})
            r = cur.fetchone()
            if r and r[0] == 0:
                return False
        return True
    except Exception:
        return True
    finally:
        cur.close()
