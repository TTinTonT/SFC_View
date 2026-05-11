# -*- coding: utf-8 -*-
from repair_module.core.db import get_conn
from repair_module.core.wip import get_station_and_next
from repair_module.core.repair_actions import get_group_info
from repair_module.core.sfis_sp import call_new_test_input_z
from repair_module.core.flow_state import get_dido_suffix_from_node
from repair_module.sql.reason_code_sql import REASON_CODE_DEBUG_VALIDATE
from repair_module.core.wip_serialize import WIP_KEYS, serialize_wip


def do_fail(sn: str, base: str, reason_code: str, emp: str = ""):
    """Same as POST /api/debug/repair/do-fail."""
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
            line = wip.get("LINE_NAME") or ""
            info = get_group_info(conn, line, current_node)
            if not info:
                return {"ok": False, "error": "Cannot resolve station for fail input."}
            ok, res = call_new_test_input_z(
                conn,
                sn,
                reason_code,
                emp,
                info["LINE_NAME"],
                info["SECTION_NAME"],
                info["STATION_NAME"],
                info["GROUP_NAME"],
            )
            if not ok:
                return {"ok": False, "error": res or "NEW_TEST_INPUT_Z failed"}
            row2 = get_station_and_next(conn, sn)
            wip2 = dict(zip(WIP_KEYS, row2)) if row2 else None
            return {
                "ok": True,
                "message": "Fail input updated.",
                "res": res,
                "wip": serialize_wip(wip2),
            }
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
