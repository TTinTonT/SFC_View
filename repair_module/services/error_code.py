# -*- coding: utf-8 -*-
from repair_module.core.db import get_conn
from repair_module.core.sfis_sp import validate_error_code


def validate_error_code_service(error_code: str):
    """Same as POST /api/debug/repair/validate-error-code body { error_code }."""
    ec = (error_code or "").strip()
    if not ec:
        return {"ok": False, "error": "error_code required"}
    try:
        conn = get_conn()
        try:
            valid = validate_error_code(conn, ec)
            return {"ok": True, "valid": valid}
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
