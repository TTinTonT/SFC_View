# -*- coding: utf-8 -*-
"""
QA Lock (PPID lock): check part có bị QA lock hay không.
Chỉ cần copy file này sang app khác là dùng được — không phụ thuộc config/sql_queries.
Cần: conn (oracledb connection) + sn (serial number).
"""
# SQL — sửa tại đây nếu đổi schema/table
QA_LOCK_CHECK_PPID = """
SELECT COUNT(*) FROM SFISM4.R_PPID_LOCK_T
WHERE SERIAL_NUMBER = :sn
"""


def check_ppid_lock(conn, sn):
    """
    Kiểm tra SN có trong R_PPID_LOCK_T (QA lock) hay không.
    Trả về (is_locked: bool, message: str).
    """
    cur = conn.cursor()
    try:
        cur.execute(QA_LOCK_CHECK_PPID, {"sn": (sn or "").strip().upper()})
        row = cur.fetchone()
        count = row[0] if row else 0
        if count > 0:
            return True, "Part bị QA lock (PPID lock). Không thể thực hiện Repair/Kitting."
        return False, ""
    except Exception as e:
        return False, str(e)
    finally:
        cur.close()
