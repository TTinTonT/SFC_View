# -*- coding: utf-8 -*-
from repair_module.core.db import get_conn
from repair_module.core.wip import get_station_and_next
from repair_module.core.repair_actions import get_group_info
from repair_module.core.sfis_sp import validate_error_code, call_new_test_input_z
from repair_module.core.wip_serialize import WIP_KEYS, serialize_wip


def submit_fail_input(sn: str, error_code: str, emp: str = ""):
    """Same as POST /api/debug/repair/fail-input."""
    sn = (sn or "").strip().upper()
    ec = (error_code or "").strip()
    emp = (emp or "").strip()
    if not sn or not ec:
        return {"ok": False, "error": "sn and error_code required"}
    try:
        conn = get_conn()
        try:
            if not validate_error_code(conn, ec):
                return {"ok": False, "error": f"EC invalid/not allowed => [{ec}]"}
            row = get_station_and_next(conn, sn)
            if not row:
                return {"ok": False, "error": "No WIP for this SN"}
            wip = dict(zip(WIP_KEYS, row))
            line = wip.get("LINE_NAME") or ""
            ui_current = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            info = get_group_info(conn, line, ui_current)
            if not info:
                return {"ok": False, "error": "Cannot resolve line/section/station/group for fail input"}
            ok, res = call_new_test_input_z(
                conn,
                sn,
                ec,
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
