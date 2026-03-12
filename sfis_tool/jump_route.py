#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jump Route (T11): nhập SN -> hiển thị route -> chọn route -> nhập lý do -> jump R_WIP_TRACKING_T.
"""
from .db import get_conn
from .repair_ok import get_group_info, jump_routing
from .sql_queries import JUMP_GET_WIP, JUMP_GET_ROUTE_LIST, JUMP_CHECK_JUMP_STATION, JUMP_CHECK_ASSY


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


def check_jump_station(conn, target_group, sn):
    """CheckJumpStation (ASSY_VIP): True = cho phép, False = chặn."""
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


def msg(en, vi):
    print(en)
    print(vi)


def main():
    conn = get_conn()
    sn = input("Enter SN / Nhập SN: ").strip().upper()
    if not sn:
        msg("SN is empty.", "SN trống.")
        return

    wip_cols, wip_rows = get_wip(conn, sn)
    if not wip_rows:
        msg("No WIP for this SN.", "Không có WIP cho SN này.")
        conn.close()
        return
    wip = dict(zip(wip_cols, wip_rows[0]))
    msg("--- Current WIP ---", "--- WIP hiện tại ---")
    for k, v in wip.items():
        print(f"  {k}: {v}")

    current_group = wip.get("GROUP_NAME") or wip.get("CURRENT_GROUP") or ""
    if current_group in ("PACKING", "SHIPPING"):
        msg("SN is at PACKING/SHIPPING; jump not allowed.", "SN đang ở PACKING/SHIPPING, không được jump.")
        conn.close()
        return

    route_cols, route_rows = get_route_list(conn, sn)
    if not route_rows:
        msg("No selectable route (FLAG=0).", "Không có route có thể chọn (FLAG=0).")
        conn.close()
        return
    msg("--- Các route có thể chọn (chỉ FLAG=0) ---", "--- Available routes (FLAG=0 only) ---")
    print()
    print("  [WIP] CURRENT_GROUP:", current_group)
    print()
    print("  " + "-" * 50)
    for i, row in enumerate(route_rows):
        d = dict(zip(route_cols, row))
        grp = d.get("GROUP_NAME") or ""
        nxt = d.get("GROUP_NEXT") or ""
        mark = "  <- [current]" if grp == current_group else ""
        print(f"  [{i:2}]  Nhảy đến / Jump to: {nxt:<20}{mark}")
    print("  " + "-" * 50)
    print("  (Chọn số = SN nhảy đến group tương ứng)")
    print()

    idx = input("Select index (0-based) / Chọn số thứ tự: ").strip()
    try:
        idx = int(idx)
    except ValueError:
        msg("Invalid input.", "Không hợp lệ.")
        conn.close()
        return
    if idx < 0 or idx >= len(route_rows):
        msg("Index out of range.", "Ngoài phạm vi.")
        conn.close()
        return

    chosen = dict(zip(route_cols, route_rows[idx]))
    target_group = chosen.get("GROUP_NAME")
    v_line = wip.get("LINE_NAME") or ""

    info = get_group_info(conn, v_line, target_group)
    if not info:
        msg("GetGroupInfo returned no target; cannot jump.", "GetGroupInfo không trả về target (không jump được).")
        conn.close()
        return
    print("Target jump / Đích jump:", info)

    do_check = input("Check JumpStation (ASSY_VIP)? (y/n, default n): ").strip().lower() == "y"
    if do_check and not check_jump_station(conn, target_group, sn):
        msg("CheckJumpStation: not allowed (kitting/assy).", "CheckJumpStation: không cho phép (kitting/assy).")
        conn.close()
        return

    reason = input("Enter jump reason (required) / Nhập lý do jump (bắt buộc): ").strip()
    if not reason:
        msg("Reason is required; abort.", "Lý do trống, không thực hiện.")
        conn.close()
        return

    confirm = input(f"Confirm jump SN {sn} -> {target_group}? (yes/no): ").strip().lower()
    if confirm != "yes":
        msg("Cancelled.", "Đã hủy.")
        conn.close()
        return

    login_user = input("Enter EMP_NO (e.g. A12345): ").strip() or "SCRIPT"
    ok = jump_routing(conn, sn, info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"], login_user, in_station_time=None)
    if ok:
        msg("Jump routing succeeded.", "Jump routing thành công (đã cập nhật R_WIP_TRACKING_T).")
    else:
        msg("UPDATE affected no rows.", "UPDATE không ảnh hưởng dòng nào.")
    conn.close()


if __name__ == "__main__":
    main()
