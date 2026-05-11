# -*- coding: utf-8 -*-
from repair_module.core.db import get_conn
from repair_module.core.wip import get_station_and_next, validate_next_station_r
from repair_module.core.repair_actions import check_has_unrepaired
from repair_module.core.wip_serialize import WIP_KEYS, serialize_wip


def get_repair_wip(sn: str):
    """Same as GET /api/debug/repair/wip?sn=..."""
    sn = (sn or "").strip()
    if not sn:
        return {"ok": False, "error": "sn required"}
    try:
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return {"ok": False, "error": "No WIP for this SN"}
            wip = dict(zip(WIP_KEYS, row))
            next_station = wip.get("NEXT_STATION")
            valid, msg = validate_next_station_r(next_station)
            if not valid:
                return {"ok": False, "error": msg}
            if not check_has_unrepaired(conn, sn):
                return {"ok": False, "error": "No un-repaired record (r_repair_t with repair_time IS NULL)"}
            return {"ok": True, "wip": serialize_wip(wip)}
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
