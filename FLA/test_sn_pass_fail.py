#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple interactive test for SN -> WIP station/error_flag -> (optional) set ERROR_FLAG or move routing.

It is intended as a lightweight analogue of the IT_TOOLS flow:
- Query current WIP by SN from SFISM4.R_WIP_TRACKING_T (ERROR_FLAG, station/group).
- If SN is not found in R_WIP_TRACKING_T: allow/skip.
- Otherwise, depending on user selection:
  1) Move (jump routing) to next route group (sets ERROR_FLAG=0 via existing sql).
  2) PASS (jump) roi Fail: T05 UPDATE ERROR_FLAG + Log T05 + log chi tiet; ERROR_DESC o log [6] toi da 100 ky tu.
  3) (Optional) Fail-jump to *_RI station is not implemented here.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import oracledb

# Ensure repo root is on sys.path so `import sfis_tool` works reliably.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from sfis_tool.db import get_conn
from sfis_tool.sql_queries import JUMP_GET_WIP, JUMP_GET_ROUTE_LIST, JUMP_GET_GROUP_INFO
from sfis_tool.repair_ok import get_group_info, jump_routing


def _escape_sql_string(s: str) -> str:
    # Oracle string literal escaping: ' -> ''
    return s.replace("'", "''")


def log_record_15(conn, params15: Sequence[str]) -> None:
    """
    Insert into SFISM4.LOG_ITTOOLS_T using DBAccess.cs logic:
      INSERT INTO SFISM4.LOG_ITTOOLS_T SELECT {vals} FROM DUAL
    where params contain literal tokens like 'SYSDATE' or 'NULL' which must not be quoted.
    """
    if len(params15) != 15:
        raise ValueError(f"params15 must have length 15, got {len(params15)}")

    tokens: List[str] = []
    for p in params15:
        if p is None:
            tokens.append("NULL")
            continue
        ps = str(p)
        if ps.upper() in ("SYSDATE", "NULL"):
            tokens.append(ps.upper())
        else:
            tokens.append(f"'{_escape_sql_string(ps)}'")

    sql = f"INSERT INTO SFISM4.LOG_ITTOOLS_T SELECT {','.join(tokens)} FROM DUAL"
    cur = conn.cursor()
    try:
        cur.execute(sql)
        conn.commit()
    finally:
        cur.close()


def log_t05_update_error_flag(conn, sn: str, error_flag_value: str, emp: str, login_ip: str) -> None:
    """
    Giong DBAccess.UpdateErrorFlag (T05): sau UPDATE ERROR_FLAG, ghi LOG_ITTOOLS_T.
    error_flag_value = gia tri da SET len R_WIP_TRACKING_T.ERROR_FLAG (1 ky tu).
    """
    params15 = [
        "UPDATE",
        "T05",
        "WIP查進退",
        "修改ERRO_FLAG",
        "SYSDATE",
        sn,
        "NULL",
        "NULL",
        "SFISM4.R_WIP_TRACKING_T",
        "ERROR_FLAG",
        "NULL",
        error_flag_value,
        emp,
        emp,
        login_ip,
    ]
    log_record_15(conn, params15)


def trim_error_desc_100(desc: Optional[str], max_len: int = 100) -> str:
    """Cat ERROR_DESC cho vua cot log ~100 ky tu (vd MO_NUMBER)."""
    s = (desc or "").strip()
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    if max_len <= 3:
        return s[:max_len]
    return s[: max_len - 3] + "..."


def pass_before_fail(
    conn,
    sn: str,
    line_name: str,
    current_group: str,
    next_group_name: Optional[str],
    next_station_name: Optional[str],
    current_station: str,
    emp: str,
) -> bool:
    """
    PASS truoc FAIL: jump_routing (next group neu co, khong thi current) -> ERROR_FLAG=0.
    Neu tram hien tai FILL_COOLANT -> dung station_name fill_coolant cho buoc PASS.
    """
    grp = (next_group_name or "").strip() or (current_group or "").strip()
    if not grp:
        return False
    info = get_group_info(conn, line_name, grp)
    if not info:
        return False
    cur_norm = (current_station or "").strip().upper().replace("-", "_").replace(" ", "_")
    st = (next_station_name or "").strip()
    if cur_norm == "FILL_COOLANT":
        st = "fill_coolant"
    target_station = st or (info.get("STATION_NAME") or "").strip() or grp
    return jump_routing(
        conn,
        sn=sn,
        v_line=info["LINE_NAME"],
        v_section=info["SECTION_NAME"],
        v_group=info["GROUP_NAME"],
        v_station=target_station,
        emp=emp,
    )


def log_fail_full_detail(
    conn,
    sn: str,
    user_ec: str,
    desc_100: str,
    mapped_flag: str,
    emp: str,
    login_ip: str,
) -> bool:
    """
    Log bo sung: [6] = ERROR_DESC toi da 100 ky tu; [11] = FLAG + EC (ngan).
    """
    desc_slot = trim_error_desc_100(desc_100, 100)
    col6 = desc_slot if desc_slot else "NULL"
    part = f"FLAG={mapped_flag} | EC={user_ec}"
    params15 = [
        "UPDATE",
        "T05",
        "WIP查進退",
        "ERROR_FULL_LOG",
        "SYSDATE",
        sn,
        col6,
        "NULL",
        "FLA_SCRIPT_FAIL",
        "ERROR_CODE+DESC",
        "NULL",
        part,
        emp,
        emp,
        login_ip,
    ]
    try:
        log_record_15(conn, params15)
        return True
    except Exception as e:
        print(f"Canh bao: log chi tiet (day du) khong ghi duoc DB: {e}")
        return False


def fetch_error_codes(conn, limit: int = 50) -> List[str]:
    """
    Fetch a generic list of ERROR_CODE for user selection.
    NOTE: In production, ERROR_CODE validity may depend on ERROR_CLASS and the current station/group.
    Here we use a broad query for usability in a test harness.
    """
    sql = "SELECT ERROR_CODE FROM SFIS1.C_ERROR_CODE_T ORDER BY ERROR_CODE"
    cur = conn.cursor()
    try:
        cur.execute(sql)
        rows = cur.fetchmany(limit)
        return [str(r[0]) for r in rows]
    finally:
        cur.close()


def validate_error_code_exists(conn, error_code: str) -> bool:
    sql = "SELECT COUNT(0) FROM SFIS1.C_ERROR_CODE_T WHERE ERROR_CODE = :ec"
    cur = conn.cursor()
    try:
        cur.execute(sql, {"ec": error_code})
        return (cur.fetchone()[0] or 0) > 0
    finally:
        cur.close()


def fetch_error_desc(conn, error_code: str) -> Optional[str]:
    """
    Fetch ERROR_DESC/ERROR_DESC2 for showing to user.
    Keep logic simple: prefer ERROR_DESC, fall back to ERROR_DESC2.
    """
    sql = """
        SELECT ERROR_DESC, ERROR_DESC2
          FROM SFIS1.C_ERROR_CODE_T
         WHERE ERROR_CODE = :ec
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, {"ec": error_code})
        row = cur.fetchone()
        if not row:
            return None
        desc = row[0]
        desc2 = row[1]
        desc_s = ("" if desc is None else str(desc)).strip()
        desc2_s = ("" if desc2 is None else str(desc2)).strip()
        if desc_s:
            return desc_s
        if desc2_s:
            return desc2_s
        return None
    finally:
        cur.close()

def query_wip(conn, sn: str) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    try:
        cur.execute(JUMP_GET_WIP, {"sn": sn})
        row = cur.fetchone()
        if not row:
            return None
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))
    finally:
        cur.close()


def query_route_list(conn, sn: str) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    try:
        cur.execute(JUMP_GET_ROUTE_LIST, {"sn": sn})
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(dict(zip(cols, r)))
        return out
    finally:
        cur.close()


def get_next_group_and_station_name(
    conn,
    sn: str,
    current_group: str,
    line_name: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Compute next GROUP_NAME and its STATION_NAME from route list order.
    """
    routes = query_route_list(conn, sn)
    if not routes:
        return None, None

    order: List[str] = []
    for r in routes:
        grp = (r.get("GROUP_NAME") or "").strip()
        if grp:
            order.append(grp)

    current_group = (current_group or "").strip()
    if not current_group or current_group not in order:
        return None, None

    idx = order.index(current_group)
    if idx + 1 >= len(order):
        return None, None

    next_group = order[idx + 1]
    if not next_group:
        return None, None

    info = get_group_info(conn, line_name, next_group)
    if not info:
        return next_group, next_group
    return next_group, info.get("STATION_NAME") or next_group


def update_error_flag(conn, sn: str, error_code: str) -> int:
    sql = """
        UPDATE SFISM4.R_WIP_TRACKING_T
           SET ERROR_FLAG = :ec
         WHERE SERIAL_NUMBER = :sn
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, {"ec": error_code, "sn": sn})
        conn.commit()
        return cur.rowcount
    finally:
        cur.close()


def get_error_flag_1char_from_error_code(conn, error_code: str) -> str:
    """
    Map SFIS1.C_ERROR_CODE_T.ERROR_CODE (string) -> SFISM4.R_WIP_TRACKING_T.ERROR_FLAG (char(1)).
    From runtime evidence: ERROR_FLAG is constrained to length 1.
    Candidate 1-char columns observed in C_ERROR_CODE_T:
      - ERROR_DEGREE (example: '1')
      - ERROR_TYPE (example: 'E')
      - ERROR_CODE_AWS (often empty)
    We pick the first non-empty candidate with len <= 1.
    """
    sql = """
        SELECT ERROR_DEGREE, ERROR_TYPE, ERROR_ITEM, ERROR_CODE_AWS
          FROM SFIS1.C_ERROR_CODE_T
         WHERE ERROR_CODE = :ec
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, {"ec": error_code})
        row = cur.fetchone()
        if not row:
            raise ValueError(f"No row in C_ERROR_CODE_T for ERROR_CODE={error_code!r}")
        cols = [d[0] for d in cur.description]
        d = dict(zip(cols, row))

        candidates = [
            ("ERROR_DEGREE", d.get("ERROR_DEGREE")),
            ("ERROR_TYPE", d.get("ERROR_TYPE")),
            ("ERROR_ITEM", d.get("ERROR_ITEM")),
            ("ERROR_CODE_AWS", d.get("ERROR_CODE_AWS")),
        ]
        for name, val in candidates:
            if val is None:
                continue
            s = str(val).strip()
            if s and len(s) <= 1:
                return s

        raise ValueError(
            f"Cannot map ERROR_CODE={error_code!r} to a 1-char ERROR_FLAG. "
            f"Observed: { {k: v for k, v in d.items()} }"
        )
    finally:
        cur.close()


def main() -> None:
    print("=== SN Pass/Fail Test Harness (FLA) ===")
    try:
        conn = get_conn()
    except Exception as e:
        print("DB connect error:", e)
        return

    try:
        sn = input("Enter SN (serial_number): ").strip().upper()
        if not sn:
            print("SN empty. Exit.")
            return

        wip = query_wip(conn, sn)
        if not wip:
            print("No WIP in SFISM4.R_WIP_TRACKING_T for this SN.")
            print("=> Allow/skip next step (per your requirement).")
            return

        # WIP fields from JUMP_GET_WIP
        current_group = str(wip.get("GROUP_NAME") or "").strip()
        current_station = str(wip.get("STATION_NAME") or "").strip()
        current_error_flag = str(wip.get("ERROR_FLAG") or "").strip()
        line = str(wip.get("LINE_NAME") or "").strip()

        next_group_name, next_station_name = get_next_group_and_station_name(
            conn, sn=sn, current_group=current_group, line_name=line
        )

        print("\n--- Current WIP ---")
        print(f"SN: {sn}")
        print(f"LINE_NAME: {line}")
        print(f"GROUP_NAME: {current_group}")
        print(f"ERROR_FLAG: {current_error_flag}")
        print(f"NEXT_STATION: {next_station_name or '(none)'}")

        emp = input("Enter EMP_NO for logging/jump (default SCRIPT): ").strip() or "SCRIPT"
        # Keep behavior consistent with other harness scripts: don't require user to enter IP.
        login_ip = "127.0.0.1"
        reason = input("Enter reason text for logging: ").strip() or "TEST"

        print("\nChoose action:")
        print("  [1] Move/jump routing (sets ERROR_FLAG=0)")
        print("  [2] PASS roi Fail (T05 UPDATE + log; ERROR_DESC log toi da 100 ky tu o cot [6])")
        choice = input("Select [1/2]: ").strip()

        if choice == "1":
            routes = query_route_list(conn, sn)
            if not routes:
                print("No available route steps (state_flag=0).")
                return
            print("\n--- Available routes (FLAG=0) ---")
            for i, r in enumerate(routes):
                grp = (r.get("GROUP_NAME") or "").strip()
                nxt = (r.get("GROUP_NEXT") or "").strip()
                state_flag = (r.get("FLAG") or "").strip()
                mark = " <- [current]" if grp == current_group else ""
                print(f"  [{i:2}] to GROUP_NAME={grp} GROUP_NEXT={nxt} FLAG={state_flag}{mark}")

            idx_s = input("Select route index: ").strip()
            try:
                idx = int(idx_s)
            except ValueError:
                print("Invalid index.")
                return
            if idx < 0 or idx >= len(routes):
                print("Index out of range.")
                return

            chosen = routes[idx]
            target_group = str(chosen.get("GROUP_NAME") or "").strip()
            v_line = line

            info = get_group_info(conn, v_line, target_group)
            if not info:
                print("GetGroupInfo returned no target (cannot move).")
                return

            ok = jump_routing(
                conn,
                sn=sn,
                v_line=info["LINE_NAME"],
                v_section=info["SECTION_NAME"],
                v_group=info["GROUP_NAME"],
                v_station=info["STATION_NAME"],
                emp=emp,
            )
            if not ok:
                print("Jump routing affected no rows.")
                return

            # LogRecord (copy pattern from DBAccess.JumpRouting)
            # DBAccess uses:
            # array[0]=UPDATE, [1]=T11, [2]=Routing Jump, [3]=Routing Jump, [4]=SYSDATE,
            # [5]=V_SN + ":" + V_Reason, [6]=NULL, [7]=NULL, [8]=SFISM4.R_WIP_TRACKING_T,
            # [9]=GROUP_NAME, [10]=text(current group), [11]=V_Group(target group),
            # [12]=LoginUser, [13]=LoginUser, [14]=LoginIP
            params15 = [
                "UPDATE",
                "T11",
                "Routing Jump",
                "Routing Jump",
                "SYSDATE",
                f"{sn}:{reason}",
                "NULL",
                "NULL",
                "SFISM4.R_WIP_TRACKING_T",
                "GROUP_NAME",
                current_group or "NULL",
                info["GROUP_NAME"],
                emp,
                emp,
                login_ip,
            ]
            log_record_15(conn, params15)
            print("OK: moved + LogRecord inserted.")

        elif choice == "2":
            # Fetch errors and ask user to choose/enter error_code
            codes = fetch_error_codes(conn, limit=80)
            print("\n--- ERROR_CODE list (sample) ---")
            for i, ec in enumerate(codes[:30]):
                print(f"  [{i:2}] {ec}")

            user_ec = input("Enter ERROR_CODE to set (or pick from list): ").strip().upper()
            if not user_ec:
                print("Empty ERROR_CODE. Exit.")
                return

            # Allow user to input an index like "5"
            if user_ec.isdigit():
                idx = int(user_ec)
                if 0 <= idx < len(codes):
                    user_ec = codes[idx]

            if not validate_error_code_exists(conn, user_ec):
                print(f"ERROR_CODE '{user_ec}' does not exist in SFIS1.C_ERROR_CODE_T.")
                return

            # Show ERROR_CODE + ERROR_DESC; user must confirm before any DB write.
            desc = fetch_error_desc(conn, user_ec) or ""
            print(f"\n--- Ban se cap nhat loi sau ---")
            print(f"ERROR_CODE: {user_ec}")
            if desc:
                print(f"ERROR_DESC:\n{desc}\n")
            else:
                print("(Khong co ERROR_DESC trong C_ERROR_CODE_T)\n")

            confirm = input(
                'Go "yes" de xac nhan: PASS (jump) -> UPDATE ERROR_FLAG + Log T05 + log chi tiet: '
            ).strip().lower()
            if confirm != "yes":
                print("Da huy. Khong ghi DB.")
                return

            ok_pass = pass_before_fail(
                conn,
                sn=sn,
                line_name=line,
                current_group=current_group,
                next_group_name=next_group_name,
                next_station_name=next_station_name,
                current_station=current_station,
                emp=emp,
            )
            if not ok_pass:
                print("PASS truoc fail that bai (jump_routing). Khong cap nhat ERROR_FLAG.")
                return
            print("PASS OK (ERROR_FLAG=0 tai group/station da jump).")

            desc_100 = trim_error_desc_100(desc, 100)

            # Giong T05: ERROR_FLAG tren WIP = 1 ky tu (map tu C_ERROR_CODE_T).
            mapped_flag = get_error_flag_1char_from_error_code(conn, user_ec)

            rows = update_error_flag(conn, sn, mapped_flag)
            if rows <= 0:
                print("ERROR_FLAG update affected no rows.")
                return

            # 1) LogRecord y chang DBAccess.UpdateErrorFlag (T05)
            log_t05_update_error_flag(conn, sn, mapped_flag, emp, login_ip)

            # 2) Log chi tiet: [6]=ERROR_DESC <=100, [11]=FLAG|EC
            ok_detail = log_fail_full_detail(conn, sn, user_ec, desc_100, mapped_flag, emp, login_ip)
            if ok_detail:
                print("OK: ERROR_FLAG updated + LogRecord T05 + log chi tiet.")
            else:
                print("OK: ERROR_FLAG updated + LogRecord T05 (log chi tiet khong ghi duoc).")
        else:
            print("Unknown choice. Exit.")

    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

