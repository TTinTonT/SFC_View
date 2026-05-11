# -*- coding: utf-8 -*-
from repair_module.core.db import get_conn
from repair_module.core.wip import get_station_and_next
from repair_module.core.repair_actions import get_group_info, jump_routing, get_jump_param_from_route
from repair_module.core.wip_serialize import WIP_KEYS, serialize_wip


def pass_jump(sn: str, target_group: str, emp_no: str = ""):
    """Same as POST /api/debug/repair/pass-jump."""
    sn = (sn or "").strip().upper()
    target_group = (target_group or "").strip()
    emp_no = (emp_no or "").strip()
    if not sn or not target_group:
        return {"ok": False, "error": "sn and target_group required"}
    try:
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return {"ok": False, "error": "No WIP for this SN."}
            wip = dict(zip(WIP_KEYS, row))
            v_line = wip.get("LINE_NAME") or ""
            jump_param = get_jump_param_from_route(conn, sn, target_group)
            info = get_group_info(conn, v_line, jump_param)
            if not info:
                return {"ok": False, "error": "GetGroupInfo returned no target; cannot jump."}
            ok = jump_routing(
                conn,
                sn,
                info["LINE_NAME"],
                info["SECTION_NAME"],
                info["GROUP_NAME"],
                info["STATION_NAME"],
                emp_no,
                in_station_time=None,
            )
            if not ok:
                return {"ok": False, "error": "UPDATE affected no rows."}
            row2 = get_station_and_next(conn, sn)
            wip2 = dict(zip(WIP_KEYS, row2)) if row2 else None
            return {"ok": True, "wip": serialize_wip(wip2)}
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
