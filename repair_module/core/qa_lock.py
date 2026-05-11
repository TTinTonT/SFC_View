# -*- coding: utf-8 -*-
"""QA Lock (PPID lock) before kitting."""

QA_LOCK_CHECK_PPID = """
SELECT COUNT(*) FROM SFISM4.R_PPID_LOCK_T
WHERE SERIAL_NUMBER = :sn
"""


def check_ppid_lock(conn, sn):
    """
    Returns (is_locked: bool, message: str).
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
