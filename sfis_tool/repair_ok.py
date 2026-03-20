# -*- coding: utf-8 -*-
"""
Repair OK: execute_repair_ok, check_has_unrepaired, get_group_info, jump_routing,
resolve_jump_target, get_jump_param_from_route.
"""
import oracledb

from .config import REPAIR_ACTION_RECORD_MAP
from .sql_queries import (
    REPAIR_CHECK_UNREPAIRED,
    REPAIR_UPDATE,
    REPAIR_GET_GROUP_INFO,
    REPAIR_GET_JUMP_PARAM,
    REPAIR_JUMP_WITH_TIME,
    REPAIR_JUMP_SYSDATE,
)


def check_has_unrepaired(conn, sn):
    """SN phải có r_repair_t với repair_time IS NULL."""
    cur = conn.cursor()
    try:
        cur.execute(REPAIR_CHECK_UNREPAIRED, [sn.upper()])
        return cur.fetchone()[0] > 0
    finally:
        cur.close()


def execute_repair_ok(conn, sn, repair_station, emp, reason_code, duty_station, remark, repair_action, duty_type=None, auto_commit=True):
    """
    UPDATE r_repair_t. Trả về (rows_updated, success: bool, err_msg: str, repair_time).
    """
    repair_out = conn.cursor().var(oracledb.DB_TYPE_TIMESTAMP)
    record_type = REPAIR_ACTION_RECORD_MAP.get(
        (repair_action or "").strip().upper(),
        (repair_action or "R")[:1]
    )
    cur = conn.cursor()
    try:
        cur.execute(REPAIR_UPDATE, {
            "sn": sn.upper(),
            "reason_code": (reason_code or "").strip(),
            "duty_station": (duty_station or "").strip(),
            "duty_type": (duty_type or duty_station or "").strip(),
            "record_type": record_type,
            "repair_action": (repair_action or "").strip()[:100],
            "remark": (remark or "").strip()[:400],
            "repairer": (emp or "").strip(),
            "repair_station": (repair_station or "").strip(),
            "repair_time": repair_out,
        })
        if auto_commit:
            conn.commit()
        n = cur.rowcount
        rt = repair_out.getvalue()[0] if n else None
        return n, True, "", rt
    except Exception as e:
        if auto_commit:
            conn.rollback()
        return 0, False, str(e), None
    finally:
        cur.close()


def get_group_info(conn, v_line, v_group):
    """Lấy LINE, SECTION, GROUP, STATION cho target group (GetGroupInfo)."""
    cur = conn.cursor()
    try:
        cur.execute(REPAIR_GET_GROUP_INFO, {"g": v_group, "l": v_line})
        row = cur.fetchone()
        if row:
            return {"LINE_NAME": row[0], "SECTION_NAME": row[1], "GROUP_NAME": row[2], "STATION_NAME": row[3]}
        return None
    finally:
        cur.close()


def resolve_jump_target(reason_code, current_group):
    """RC36 -> FLA. RC500 / R_xxx -> bỏ R_."""
    rc = (reason_code or "").strip().upper()
    cg = (current_group or "").strip()
    if rc == "RC36":
        return "FLA"
    if cg.startswith("R_"):
        return cg[2:]
    return cg or "FLA"


def get_jump_param_from_route(conn, sn, desired_target):
    """Tìm GROUP_NAME trong C_ROUTE_CONTROL_T có GROUP_NEXT = desired_target."""
    cur = conn.cursor()
    try:
        cur.execute(REPAIR_GET_JUMP_PARAM, {"sn": sn.upper(), "target": desired_target})
        row = cur.fetchone()
        return row[0] if row else desired_target
    finally:
        cur.close()


def jump_routing(conn, sn, v_line, v_section, v_group, v_station, emp, in_station_time=None, auto_commit=True):
    """UPDATE R_WIP_TRACKING_T - jump station."""
    if in_station_time is not None:
        sql = REPAIR_JUMP_WITH_TIME
        params = {"v_line": v_line, "v_section": v_section, "v_group": v_group, "v_station": v_station,
                  "emp": emp, "sn": sn.upper(), "in_time": in_station_time}
    else:
        sql = REPAIR_JUMP_SYSDATE
        params = {"v_line": v_line, "v_section": v_section, "v_group": v_group, "v_station": v_station,
                  "emp": emp, "sn": sn.upper()}
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        if auto_commit:
            conn.commit()
        return cur.rowcount > 0
    finally:
        cur.close()
