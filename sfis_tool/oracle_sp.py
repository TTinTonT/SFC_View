# -*- coding: utf-8 -*-
"""Oracle stored-procedure wrappers for Repair fail input flow."""

import oracledb

from .sql_queries import REPAIR_VALIDATE_ERROR_CODE


def validate_error_code(conn, error_code):
    """Validate error code in C_ERROR_CODE_T with normalized spaces."""
    cur = conn.cursor()
    try:
        cur.execute(REPAIR_VALIDATE_ERROR_CODE, {"ec": (error_code or "").strip()})
        row = cur.fetchone()
        return bool(row and row[0] and int(row[0]) > 0)
    finally:
        cur.close()


def call_new_test_input_z(conn, sn, error_code, emp, line, section, w_station, mygroup):
    """
    Call SFIS1.NEW_TEST_INPUT_Z and commit only when RES='OK'.
    Returns (ok: bool, res: str).
    """
    cur = conn.cursor()
    try:
        v_res = cur.var(oracledb.DB_TYPE_VARCHAR, size=4000)
        cur.callproc(
            "SFIS1.NEW_TEST_INPUT_Z",
            [
                (emp or "").strip(),
                (line or "").strip(),
                (section or "").strip(),
                (w_station or "").strip(),
                (error_code or "").strip(),
                (sn or "").strip().upper(),
                (mygroup or "").strip(),
                v_res,
            ],
        )
        res = (v_res.getvalue() or "").strip()
        if res == "OK":
            conn.commit()
            return True, res
        conn.rollback()
        return False, res or "RES is empty"
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
