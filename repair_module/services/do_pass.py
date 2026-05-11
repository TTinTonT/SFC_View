# -*- coding: utf-8 -*-
from repair_module.core.db import get_conn
from repair_module.core.wip import get_station_and_next
from repair_module.core.repair_actions import (
    get_group_info,
    jump_routing,
    get_jump_param_from_route,
    execute_repair_ok,
    check_has_unrepaired,
)
from repair_module.core.flow_state import get_dido_suffix_from_node
from repair_module.sql.reason_code_sql import REASON_CODE_DEBUG_VALIDATE
from repair_module.core.wip_serialize import WIP_KEYS, serialize_wip


def do_pass(sn: str, base: str, reason_code: str, remark: str = "", emp: str = ""):
    """Same as POST /api/debug/repair/do-pass."""
    sn = (sn or "").strip().upper()
    base = (base or "").strip()
    reason_code = (reason_code or "").strip()
    emp = (emp or "").strip()
    if not sn or not base or not reason_code:
        return {"ok": False, "error": "sn, base, and reason_code required"}
    try:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(REASON_CODE_DEBUG_VALIDATE, {"rc": reason_code})
            row = cur.fetchone()
            cur.close()
            if not row or row[0] == 0:
                return {"ok": False, "error": "Invalid reason code for DO station."}

            row = get_station_and_next(conn, sn)
            if not row:
                return {"ok": False, "error": "No WIP for this SN."}
            wip = dict(zip(WIP_KEYS, row))
            current_node = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            if get_dido_suffix_from_node(current_node) != "DO":
                return {"ok": False, "error": "SN must be at DO station for this action."}
            if not check_has_unrepaired(conn, sn):
                return {"ok": False, "error": "No un-repaired record."}

            repair_station = wip.get("STATION_NAME") or current_node
            n, ok_repair, err, _ = execute_repair_ok(
                conn,
                sn,
                repair_station,
                emp,
                reason_code,
                duty_station="TEST FIXTURE",
                remark=remark or "DO Pass",
                repair_action="RETEST",
                duty_type="RETEST",
                auto_commit=False,
            )
            if not ok_repair or n == 0:
                conn.rollback()
                return {"ok": False, "error": err or "Repair update failed."}
            v_line = wip.get("LINE_NAME") or ""
            jump_param = get_jump_param_from_route(conn, sn, base)
            info = get_group_info(conn, v_line, jump_param)
            if not info:
                conn.rollback()
                return {"ok": False, "error": "GetGroupInfo not found for base; cannot jump."}
            ok = jump_routing(
                conn,
                sn,
                info["LINE_NAME"],
                info["SECTION_NAME"],
                info["GROUP_NAME"],
                info["STATION_NAME"],
                emp,
                in_station_time=None,
                auto_commit=False,
            )
            if not ok:
                conn.rollback()
                return {"ok": False, "error": "UPDATE affected no rows."}
            conn.commit()
            row2 = get_station_and_next(conn, sn)
            wip2 = dict(zip(WIP_KEYS, row2)) if row2 else None
            return {"ok": True, "wip": serialize_wip(wip2)}
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
