# -*- coding: utf-8 -*-
from repair_module.core.db import get_conn
from repair_module.core.wip import get_station_and_next
from repair_module.core.repair_actions import get_group_info, jump_routing
from repair_module.core.flow_state import get_dido_suffix_from_node
from repair_module.core.wip_serialize import WIP_KEYS, serialize_wip


def di_next(sn: str, base: str, emp_no: str = ""):
    """Same as POST /api/debug/repair/di-next. emp_no: SFIS employee id (caller resolves from auth)."""
    sn = (sn or "").strip().upper()
    base = (base or "").strip()
    emp_no = (emp_no or "").strip()
    if not sn or not base:
        return {"ok": False, "error": "sn and base required"}
    try:
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return {"ok": False, "error": "No WIP for this SN."}
            wip = dict(zip(WIP_KEYS, row))
            current_node = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            if get_dido_suffix_from_node(current_node) != "DI":
                return {"ok": False, "error": "SN must be at DI station for this action."}
            target_group = f"{base} DO"
            v_line = wip.get("LINE_NAME") or ""
            info = get_group_info(conn, v_line, target_group)
            if not info:
                target_group = f"{base}_DO"
                info = get_group_info(conn, v_line, target_group)
            if not info:
                return {"ok": False, "error": "GetGroupInfo not found for target; cannot jump."}
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
