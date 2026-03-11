# -*- coding: utf-8 -*-
"""WIP: get_station_and_next, validate_next_station_r."""
from .sql_queries import WIP_GET_STATION_AND_NEXT


def get_station_and_next(conn, sn):
    """Lấy SN, MO, Model, STATION_NAME, LINE_NAME, GROUP_NAME, NEXT_STATION."""
    cur = conn.cursor()
    try:
        cur.execute(WIP_GET_STATION_AND_NEXT, [sn.upper()])
        return cur.fetchone()
    finally:
        cur.close()


def validate_next_station_r(next_station):
    """
    Validate next_station hợp lệ cho Repair OK.
    Trả về (valid: bool, msg: str).
    """
    if not next_station or not str(next_station).strip():
        return False, "Next station is empty. SN may not be at repair station (R_xxx)."
    return True, ""
