# -*- coding: utf-8 -*-
"""
DI/DO (Debug In / Debug Out) module — standalone, copy 1 file to use in another app.

Luồng:
- InStore (Debug In): User nhập SN → fill thông tin → chọn sheet (dropdown) → remark → Confirm
  → jump WIP vào DI station. Nếu SN đã ở DI station thì báo lỗi.
- OutStore (Debug Out): Pass = jump về original station (truyền station_before để lấy GROUP_NEXT);
  Fail = chuyển sang xxx_RI (Repair-IN).

Quy tắc Pass outstore: Nhảy về station X thì truyền station ngay trước X (station_before).
  Đích jump = GROUP_NEXT của bước có GROUP_NAME = station_before trong C_ROUTE_CONTROL_T.
"""
import oracledb

# --- Config (sửa khi copy sang app khác) ---
CONN_USER = "sfis1"
CONN_PASSWORD = "sfis1"
CONN_DSN = "10.16.137.112:1526/SJSFC2DB"
ORACLE_CLIENT_DIR = r"C:\Users\FAswing\Downloads\instantclient_23_0"

# Dropdown sheet options (InStore) — map value/display
SHEET_OPTIONS = [
    ("wait_for_bga", "Wait for BGA"),
    ("wait_for_repair", "Wait for Repair"),
    ("material_shortage", "Material shortage"),
    ("good_board", "Good board"),
    ("repair_on_line", "Repair on line"),
    ("in_hpc", "In HPC"),
    ("wait_for_memory_rework", "Wait for memory rework"),
    ("lend_out", "Lend out"),
]
REASON_CODE_OUTSTORE = "DEBUG_014"
REASON_DESC_OUTSTORE = "Test-partner"

# --- SQL (tất cả trong file) ---
SQL_WIP_BY_SN = """
SELECT SERIAL_NUMBER, MO_NUMBER, MODEL_NAME, STATION_NAME, LINE_NAME, GROUP_NAME, SPECIAL_ROUTE
FROM SFISM4.R_WIP_TRACKING_T WHERE SERIAL_NUMBER = :sn
"""

SQL_DEBUGWIP_CONTROL_BY_SN = """
SELECT SERIAL_NUMBER, MODEL_NAME, MO_NUMBER, LINE_NAME, IN_STORE_TIME, REPAIR_TIME,
       ZONG_LIANG, KU_CUN, BGA_MEM, DAI_REPAIR, QIAN_LIAO, OK_BAN, ONLINE_REPAIR, REPAIR_OFFICE,
       LOCK_FLAG, REMARK, TEMP01, TEMP02, MFG_EMP, REPAIR_EMP
FROM SFISM4.R_DEBUGWIP_CONTROL_T WHERE SERIAL_NUMBER = :sn
"""

SQL_GROUP_NEXT_FROM_STATION_BEFORE = """
SELECT T1.GROUP_NEXT FROM SFIS1.C_ROUTE_CONTROL_T T1, SFISM4.R_WIP_TRACKING_T T2
WHERE T1.ROUTE_CODE = T2.SPECIAL_ROUTE AND T2.SERIAL_NUMBER = :sn
  AND T1.GROUP_NAME = :station_before AND T1.STATE_FLAG = '0' AND ROWNUM = 1
"""

SQL_GET_GROUP_INFO = """
SELECT * FROM (
    SELECT DISTINCT T3.LINE_NAME, T3.SECTION_NAME, T3.GROUP_NAME, T3.STATION_NAME, '1' AS RRR
    FROM SFIS1.C_SECTION_CONFIG_T T1
    LEFT JOIN SFIS1.C_GROUP_CONFIG_T T2 ON T1.SECTION_NAME = T2.SECTION_NAME
    LEFT JOIN SFIS1.C_STATION_CONFIG_T T3 ON T1.SECTION_NAME = T3.SECTION_NAME AND T2.GROUP_NAME = T3.GROUP_NAME
    WHERE T3.GROUP_NAME = :g AND T3.LINE_NAME LIKE '%' || REGEXP_REPLACE(:l, '[^0-9]', '') || '%'
    UNION
    SELECT DISTINCT :l AS LINE_NAME, GROUP_NAME AS SECTION_NAME, GROUP_NAME AS GROUP_NAME, GROUP_NAME AS STATION_NAME, '2' AS RRR
    FROM SFIS1.C_GROUP_CONFIG_T WHERE GROUP_NAME = :g
    ORDER BY RRR, LINE_NAME, STATION_NAME
) WHERE ROWNUM = 1
"""

SQL_JUMP_WIP_SYSDATE = """
UPDATE SFISM4.R_WIP_TRACKING_T SET
(LINE_NAME, SECTION_NAME, GROUP_NAME, STATION_NAME, ERROR_FLAG, IN_STATION_TIME, EMP_NO) =
(SELECT :v_line, :v_section, :v_group, :v_station, '0', SYSDATE, :emp FROM DUAL)
WHERE SERIAL_NUMBER = :sn
"""

SQL_UPDATE_DEBUGWIP_CONTROL_INSTORE = """
UPDATE SFISM4.R_DEBUGWIP_CONTROL_T SET
REMARK = :remark, TEMP01 = :sheet_value, IN_STORE_TIME = SYSDATE, MFG_EMP = :emp
WHERE SERIAL_NUMBER = :sn
"""

SQL_INSERT_DEBUGWIP_CONTROL = """
INSERT INTO SFISM4.R_DEBUGWIP_CONTROL_T
(SERIAL_NUMBER, MODEL_NAME, MO_NUMBER, LINE_NAME, IN_STORE_TIME, REMARK, TEMP01, MFG_EMP)
VALUES (:sn, :model_name, :mo_number, :line_name, SYSDATE, :remark, :sheet_value, :emp)
"""

SQL_INSERT_DEBUGWIP_LOG_FROM_CONTROL = """
INSERT INTO SFISM4.R_DEBUGWIP_CONTROL_LOG_T
SELECT SERIAL_NUMBER, MODEL_NAME, MO_NUMBER, LINE_NAME, ZONG_LIANG, KU_CUN, BGA_MEM, DAI_REPAIR,
       QIAN_LIAO, OK_BAN, ONLINE_REPAIR, REPAIR_OFFICE, IN_STORE_TIME, LOCK_FLAG, REMARK, TEMP01, TEMP02,
       'N/A', REPAIR_TIME, MFG_EMP, REPAIR_EMP
FROM SFISM4.R_DEBUGWIP_CONTROL_T WHERE SERIAL_NUMBER = :sn
"""

SQL_OUTSTORE_INFO = """
SELECT a.serial_number, a.model_name, a.MO_NUMBER, a.ERROR_CODE, a.out_time, a.mfg_emp,
       a.repair_emp, b.reason_code, b.error_item_code, b.duty_type, b.repairer, b.repair_time
FROM sfism4.R_DEBUGWIP_CONTROL_OUT_T a, sfism4.r_repair_t b
WHERE a.serial_number = b.serial_number AND B.GROUP_NAME = 'DEBUG' AND a.out_time = b.test_time
  AND a.serial_number = :sn
"""


def get_conn():
    """Tạo connection Oracle. Dùng config trong file. Có thể override bằng cách app khác truyền conn vào từng function."""
    try:
        oracledb.init_oracle_client(lib_dir=ORACLE_CLIENT_DIR)
    except oracledb.ProgrammingError as e:
        if "already been initialized" not in str(e).lower():
            raise
    return oracledb.connect(user=CONN_USER, password=CONN_PASSWORD, dsn=CONN_DSN)


def validate_login(conn, user, password, station):
    """
    Kiểm tra user/password và quyền vào station (e.g. FLA DI, FLB DI).
    Trả về (ok: bool, message: str).
    Hiện tại stub: luôn (True, ""). Thay bằng query bảng user/privilege khi có spec.
    """
    # Stub — chưa có bảng/API từ SOP
    return True, ""


def get_wip_for_sn(conn, sn):
    """
    Lấy thông tin WIP và DEBUGWIP control (nếu có) để fill form.
    Trả về dict với keys từ R_WIP_TRACKING_T; nếu có R_DEBUGWIP_CONTROL_T thì merge thêm.
    Trả về None nếu không có WIP.
    """
    sn = (sn or "").strip().upper()
    cur = conn.cursor()
    try:
        cur.execute(SQL_WIP_BY_SN, {"sn": sn})
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        wip = dict(zip(cols, row))
        cur.execute(SQL_DEBUGWIP_CONTROL_BY_SN, {"sn": sn})
        row2 = cur.fetchone()
        if row2:
            cols2 = [d[0] for d in cur.description]
            for i, c in enumerate(cols2):
                wip["DEBUGWIP_" + c] = row2[i]
        return wip
    finally:
        cur.close()


def check_sn_already_at_di_station(conn, sn, di_station):
    """
    Kiểm tra SN đã ở station DI chưa (GROUP_NAME = di_station).
    Trả về (already_at_di: bool, message: str).
    """
    sn = (sn or "").strip().upper()
    di_station = (di_station or "").strip()
    cur = conn.cursor()
    try:
        cur.execute(SQL_WIP_BY_SN, {"sn": sn})
        row = cur.fetchone()
        if not row:
            return False, "No WIP for SN."
        cols = [d[0] for d in cur.description]
        wip = dict(zip(cols, row))
        current_group = (wip.get("GROUP_NAME") or "").strip()
        if current_group.upper() == di_station.upper():
            return True, "SN already at DI station."
        return False, ""
    finally:
        cur.close()


def get_jump_target_from_station_before(conn, sn, station_before):
    """
    Lấy GROUP_NEXT (đích jump) từ C_ROUTE_CONTROL_T theo route của SN và GROUP_NAME = station_before.
    Trả về group name (str) hoặc None.
    """
    sn = (sn or "").strip().upper()
    station_before = (station_before or "").strip()
    cur = conn.cursor()
    try:
        cur.execute(SQL_GROUP_NEXT_FROM_STATION_BEFORE, {"sn": sn, "station_before": station_before})
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        cur.close()


def _get_group_info(conn, v_line, v_group):
    """Lấy LINE, SECTION, GROUP, STATION cho target group. Trả về dict hoặc None."""
    cur = conn.cursor()
    try:
        cur.execute(SQL_GET_GROUP_INFO, {"g": v_group, "l": v_line})
        row = cur.fetchone()
        if row:
            return {"LINE_NAME": row[0], "SECTION_NAME": row[1], "GROUP_NAME": row[2], "STATION_NAME": row[3]}
        return None
    finally:
        cur.close()


def jump_wip_to_station(conn, sn, v_line, v_section, v_group, v_station, emp, in_station_time=None):
    """
    UPDATE R_WIP_TRACKING_T — jump SN đến station (v_line, v_section, v_group, v_station).
    Trả về True nếu rowcount > 0.
    """
    cur = conn.cursor()
    try:
        if in_station_time is not None:
            sql = """
            UPDATE SFISM4.R_WIP_TRACKING_T SET
            (LINE_NAME, SECTION_NAME, GROUP_NAME, STATION_NAME, ERROR_FLAG, IN_STATION_TIME, EMP_NO) =
            (SELECT :v_line, :v_section, :v_group, :v_station, '0', :in_time, :emp FROM DUAL)
            WHERE SERIAL_NUMBER = :sn
            """
            cur.execute(sql, {"v_line": v_line, "v_section": v_section, "v_group": v_group, "v_station": v_station,
                             "emp": (emp or "").strip(), "sn": (sn or "").strip().upper(), "in_time": in_station_time})
        else:
            cur.execute(SQL_JUMP_WIP_SYSDATE, {"v_line": v_line, "v_section": v_section, "v_group": v_group,
                                               "v_station": v_station, "emp": (emp or "").strip(), "sn": (sn or "").strip().upper()})
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def instore_confirm(conn, sn, line, di_station, sheet_value, remark, emp):
    """
    Cập nhật hoặc INSERT R_DEBUGWIP_CONTROL_T (remark, sheet_value=TEMP01, IN_STORE_TIME, MFG_EMP),
    ghi log R_DEBUGWIP_CONTROL_LOG_T, rồi jump WIP về di_station.
    Trả về (success: bool, message: str).
    """
    sn = (sn or "").strip().upper()
    cur = conn.cursor()
    try:
        cur.execute(SQL_UPDATE_DEBUGWIP_CONTROL_INSTORE, {
            "sn": sn, "remark": remark or "", "sheet_value": sheet_value or "", "emp": emp or ""
        })
        if cur.rowcount == 0:
            wip = get_wip_for_sn(conn, sn)
            if not wip:
                conn.rollback()
                return False, "No WIP for SN."
            cur.execute(SQL_INSERT_DEBUGWIP_CONTROL, {
                "sn": sn,
                "model_name": wip.get("MODEL_NAME") or "",
                "mo_number": wip.get("MO_NUMBER") or "",
                "line_name": line or wip.get("LINE_NAME") or "",
                "remark": remark or "",
                "sheet_value": sheet_value or "",
                "emp": emp or "",
            })
        cur.execute(SQL_INSERT_DEBUGWIP_LOG_FROM_CONTROL, {"sn": sn})
        conn.commit()
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        cur.close()

    info = _get_group_info(conn, line or "", (di_station or "").strip())
    if not info:
        return False, "GetGroupInfo not found for di_station."
    ok = jump_wip_to_station(conn, sn, info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"], emp or "")
    if not ok:
        return False, "Jump WIP affected no rows."
    return True, ""


def get_outstore_info(conn, sn):
    """
    Lấy thông tin outstore (R_DEBUGWIP_CONTROL_OUT_T join r_repair_t) để hiển thị.
    Trả về dict hoặc None.
    """
    sn = (sn or "").strip().upper()
    cur = conn.cursor()
    try:
        cur.execute(SQL_OUTSTORE_INFO, {"sn": sn})
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    finally:
        cur.close()


def outstore_pass(conn, sn, remark, emp, station_before):
    """
    Pass outstore: cập nhật repair (reason DEBUG_014, Test-partner) nếu cần, rồi jump WIP về
    station = GROUP_NEXT ứng với GROUP_NAME = station_before (route của SN).
    Trả về (success: bool, message: str).
    """
    sn = (sn or "").strip().upper()
    station_before = (station_before or "").strip()
    target_group = get_jump_target_from_station_before(conn, sn, station_before)
    if not target_group:
        return False, "No jump target for station_before."
    wip = get_wip_for_sn(conn, sn)
    if not wip:
        return False, "No WIP for SN."
    line = wip.get("LINE_NAME") or ""
    info = _get_group_info(conn, line, target_group)
    if not info:
        return False, "GetGroupInfo not found for target."
    ok = jump_wip_to_station(conn, sn, info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"], emp or "")
    if not ok:
        return False, "Jump WIP affected no rows."
    return True, ""


def outstore_fail(conn, sn, remark, emp):
    """
    Fail outstore: chuyển SN sang station xxx_RI (Repair-IN). Derive RI group từ GROUP_NAME hiện tại
    (e.g. FLA DO -> FLA_RI hoặc FLA-RI). Update R_WIP_TRACKING_T.
    Trả về (success: bool, message: str).
    """
    sn = (sn or "").strip().upper()
    wip = get_wip_for_sn(conn, sn)
    if not wip:
        return False, "No WIP for SN."
    current_group = (wip.get("GROUP_NAME") or "").strip()
    line = wip.get("LINE_NAME") or ""
    # Derive RI: "FLA DI" / "FLA DO" -> "FLA_RI" (hoặc "FLA-RI" tùy config)
    base = current_group.replace(" DI", "").replace(" DO", "").strip()
    ri_group = base + "_RI" if base else current_group + "_RI"
    info = _get_group_info(conn, line, ri_group)
    if not info:
        ri_group_alt = base + "-RI" if base else current_group + "-RI"
        info = _get_group_info(conn, line, ri_group_alt)
    if not info:
        return False, "GetGroupInfo not found for RI station."
    ok = jump_wip_to_station(conn, sn, info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"], emp or "")
    if not ok:
        return False, "Jump WIP affected no rows."
    return True, ""


def main():
    """Test flow: get_conn, validate_login (stub), get_wip_for_sn, check_sn_already_at_di_station, get_jump_target_from_station_before."""
    print("=== DI/DO module test ===\n")
    try:
        conn = get_conn()
    except Exception as e:
        print("Connection error:", e)
        return

    try:
        ok, msg = validate_login(conn, "user", "pass", "FLA DI")
        print("validate_login(stub):", ok, msg or "OK")

        sn = input("SN (Enter to skip WIP/check): ").strip()
        if not sn:
            print("Skipped.")
            conn.close()
            return

        wip = get_wip_for_sn(conn, sn)
        if wip:
            print("get_wip_for_sn:", {k: v for k, v in wip.items() if not k.startswith("DEBUGWIP_")})
        else:
            print("get_wip_for_sn: No WIP")

        di_station = input("DI station to check (e.g. FLA DI): ").strip()
        if di_station:
            already, msg = check_sn_already_at_di_station(conn, sn, di_station)
            print("check_sn_already_at_di_station:", already, msg or "OK")

        station_before = input("station_before for jump target (e.g. FLA): ").strip()
        if station_before:
            target = get_jump_target_from_station_before(conn, sn, station_before)
            print("get_jump_target_from_station_before:", target or "(none)")

        print("\nDone (no DB write in this test).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
