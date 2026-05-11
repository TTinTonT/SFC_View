# -*- coding: utf-8 -*-
from repair_module.core.db import get_conn
from repair_module.core.time_utils import format_time_pacific
from repair_module.sql.history_sql import REPAIR_FAIL_HISTORY


def get_fail_history(sn: str):
    """Same as GET /api/debug/repair/fail-history?sn=..."""
    sn = (sn or "").strip().upper()
    if not sn:
        return {"ok": False, "error": "sn required"}
    try:
        conn = get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(REPAIR_FAIL_HISTORY, {"sn": sn})
                cols = [d[0] for d in cur.description]
                col_idx = {c: i for i, c in enumerate(cols)}
                rows = []
                for row in cur.fetchall():
                    item = {}
                    for idx, col in enumerate(cols):
                        val = row[idx]
                        item[col] = val.isoformat() if hasattr(val, "isoformat") else val
                    item["TEST_TIME_CALI"] = format_time_pacific(
                        row[col_idx["TEST_TIME"]] if "TEST_TIME" in col_idx else None
                    )
                    item["REPAIR_TIME_CALI"] = format_time_pacific(
                        row[col_idx["REPAIR_TIME"]] if "REPAIR_TIME" in col_idx else None
                    )
                    rows.append(item)
                return {"ok": True, "rows": rows}
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
