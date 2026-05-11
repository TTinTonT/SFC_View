# -*- coding: utf-8 -*-
from repair_module.core.db import get_conn
from repair_module.sql.reason_code_sql import REASON_CODE_DEBUG_LIST


def list_debug_reason_codes():
    """Same as GET /api/debug/repair/debug-reason-codes."""
    try:
        conn = get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(REASON_CODE_DEBUG_LIST)
                rows = cur.fetchall()
                return {
                    "ok": True,
                    "reason_codes": [{"code": row[0], "desc": row[1] or ""} for row in rows],
                }
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
