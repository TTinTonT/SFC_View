# -*- coding: utf-8 -*-
"""
SFC API client: login (get session) and fetch fail_result_new.jsp HTML.
Session is cached; re-login if expired (~30 min) or on auth failure.
"""
from __future__ import annotations

import os
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Tuple

import requests

from config.app_config import EXTEND_HOURS

SFC_BASE_URL = os.environ.get("SFC_BASE_URL", "http://10.16.137.110")
LOGIN_URL = f"{SFC_BASE_URL}/System/Login.jsp"
FAIL_RESULT_URL = f"{SFC_BASE_URL}/L10_Report/Manufacture/fail_result_new.jsp"

SFC_USER = os.environ.get("SFC_USER", "SFC")
SFC_PWD = os.environ.get("SFC_PWD", "EPD2TJW")

GROUP_NAME = "'AST','FCT','FLA','FLB','FLC','FTS','IOT','NVL','PRET','RIN'"

# Session cache
_session_lock = threading.Lock()
_cached_session: Optional[requests.Session] = None
_session_obtained_at: float = 0
SESSION_TTL_SECONDS = 30 * 60  # 30 minutes


def _login(session: Optional[requests.Session] = None) -> Tuple[bool, requests.Session]:
    """POST to SFC Login.jsp; returns (success, session with cookies)."""
    sess = session or requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        r = sess.post(LOGIN_URL, data={"Uname": SFC_USER, "Pwd": SFC_PWD}, timeout=15)
        if r.status_code != 200:
            return False, sess
        return True, sess
    except Exception:
        return False, sess


def _get_session(force_new: bool = False) -> Optional[requests.Session]:
    """Return a valid session. Uses cache; re-login if expired or force_new."""
    global _cached_session, _session_obtained_at
    with _session_lock:
        now = time.time()
        if force_new or _cached_session is None or (now - _session_obtained_at) > SESSION_TTL_SECONDS:
            ok, sess = _login()
            if ok:
                _cached_session = sess
                _session_obtained_at = now
            return sess if ok else None
        return _cached_session


def _fetch_fail_result_html(
    session: requests.Session,
    from_dt: datetime,
    to_dt: datetime,
) -> Tuple[bool, str]:
    """POST fail_result_new.jsp. Returns (success, html_string)."""
    from_date = from_dt.strftime("%Y/%m/%d")
    from_time = from_dt.strftime("%H:%M")
    to_date = to_dt.strftime("%Y/%m/%d")
    to_time = to_dt.strftime("%H:%M")
    data = {
        "FromDate": from_date,
        "FromTime": from_time,
        "ToDate": to_date,
        "ToTime": to_time,
        "ModelName": "ALL",
        "MONumber": "",
        "GroupName": GROUP_NAME,
        "TestResult": "ALL",
        "SerialNumber": "",
        "StationID": "",
        "ErrorCode": "",
        "ErrorDesc": "",
    }
    try:
        r = session.post(FAIL_RESULT_URL, data=data, timeout=60)
        if r.status_code != 200:
            return False, ""
        return True, r.text
    except Exception:
        return False, ""


def request_fail_result(
    user_start: datetime,
    user_end: datetime,
    extend_hours: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Get session (cached or fresh), then fetch fail_result with range
    [user_start - extend_hours, user_end + extend_hours].
    Returns (success, html). Caller parses and filters by user_start/user_end.
    """
    hours = extend_hours if extend_hours is not None else EXTEND_HOURS
    sess = _get_session()
    if sess is None:
        return False, ""
    from_dt = user_start - timedelta(hours=hours)
    to_dt = user_end + timedelta(hours=hours)
    ok, html = _fetch_fail_result_html(sess, from_dt, to_dt)
    if not ok:
        # Try re-login once on failure
        sess = _get_session(force_new=True)
        if sess:
            ok, html = _fetch_fail_result_html(sess, from_dt, to_dt)
    return ok, html
