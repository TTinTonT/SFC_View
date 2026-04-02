# -*- coding: utf-8 -*-
"""Auth helpers: session, token, password, lockout, IP check."""

from __future__ import annotations

import secrets
import time
from typing import Any, Dict, Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

from config.app_config import AUTH_SESSION_TTL_MINUTES
from fa_debug.auth_db import connect_auth_db, ensure_auth_db, get_app_setting

SESSION_TTL_SECONDS = (AUTH_SESSION_TTL_MINUTES or 30) * 60
LOCKOUT_FAIL_COUNT = 3


def _parse_ttl_minutes(val: Optional[str]) -> Optional[int]:
    """Parse TTL value: None = use default, None return = unlimited, int = seconds."""
    if val is None:
        return (AUTH_SESSION_TTL_MINUTES or 30) * 60
    s = (val or "").strip().lower()
    if s in ("", "0", "unlimited"):
        return None
    try:
        minutes = int(s)
        return max(1, min(minutes, 10080)) * 60
    except ValueError:
        return (AUTH_SESSION_TTL_MINUTES or 30) * 60


def get_session_ttl_seconds(conn, user_id: Optional[int] = None) -> Optional[int]:
    """Session TTL in seconds. If user_id given, use user's session_ttl_minutes first; else global. None = unlimited."""
    if user_id is not None:
        cur = conn.execute("SELECT session_ttl_minutes FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if row is not None and row["session_ttl_minutes"] is not None and str(row["session_ttl_minutes"]).strip():
            return _parse_ttl_minutes(str(row["session_ttl_minutes"]))
    val = get_app_setting(conn, "session_ttl_minutes")
    return _parse_ttl_minutes(val)


LOCKOUT_SECONDS = 3600  # 1 hour


def _now_ts() -> int:
    return int(time.time())


def hash_password(password: str) -> str:
    return generate_password_hash(password, method="scrypt")


def check_password(user_row: Any, password: str) -> bool:
    if not user_row or not password:
        return False
    pw_hash = user_row["password_hash"] if hasattr(user_row, "keys") else user_row.get("password_hash")
    return bool(pw_hash and check_password_hash(pw_hash, password))


def is_user_locked(conn, user_id: int) -> bool:
    """True if user is locked (3 fails in last 1h)."""
    cur = conn.execute(
        "SELECT locked_until_ts FROM users WHERE id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    if not row or row["locked_until_ts"] is None:
        return False
    return _now_ts() < row["locked_until_ts"]


def record_login_attempt(conn, user_id: Optional[int], username: Optional[str], ip: str, success: bool) -> None:
    conn.execute(
        "INSERT INTO login_log (user_id, username, ip, success, created_at_ts) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, ip, 1 if success else 0, _now_ts()),
    )
    conn.commit()


def maybe_lock_user(conn, user_id: int) -> None:
    """If 3+ failed logins in last 1h, set locked_until_ts."""
    cur = conn.execute(
        """SELECT COUNT(*) AS c FROM login_log
           WHERE user_id = ? AND success = 0 AND created_at_ts >= ?""",
        (user_id, _now_ts() - LOCKOUT_SECONDS),
    )
    row = cur.fetchone()
    if row and row["c"] >= LOCKOUT_FAIL_COUNT:
        conn.execute(
            "UPDATE users SET locked_until_ts = ?, updated_at_ts = ? WHERE id = ?",
            (_now_ts() + LOCKOUT_SECONDS, _now_ts(), user_id),
        )
        conn.commit()


def unlock_user(conn, user_id: int) -> None:
    conn.execute("UPDATE users SET locked_until_ts = NULL, updated_at_ts = ? WHERE id = ?", (_now_ts(), user_id))
    conn.commit()


def is_ip_allowed(conn, user_id: int, ip: str) -> bool:
    cur = conn.execute("SELECT allow_all_ip FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return False
    if row["allow_all_ip"]:
        return True
    cur = conn.execute("SELECT 1 FROM user_allowed_ips WHERE user_id = ? AND ip = ?", (user_id, ip))
    return cur.fetchone() is not None


def add_user_ip(conn, user_id: int, ip: str) -> None:
    conn.execute("INSERT OR IGNORE INTO user_allowed_ips (user_id, ip) VALUES (?, ?)", (user_id, ip))
    conn.commit()


def in_allowed_time_window(user_row: Any) -> bool:
    """True if current time is within user's allowed_login_start/end. 0:00–0:00 or empty = 24/7."""
    start = user_row.get("allowed_login_start_time") if hasattr(user_row, "get") else (user_row["allowed_login_start_time"] if hasattr(user_row, "keys") else None)
    end = user_row.get("allowed_login_end_time") if hasattr(user_row, "get") else (user_row["allowed_login_end_time"] if hasattr(user_row, "keys") else None)
    if not start and not end:
        return True
    if (start == "0:00" or start == "00:00") and (end == "0:00" or end == "00:00"):
        return True
    from datetime import datetime
    now = datetime.now().time()
    try:
        if start:
            s = datetime.strptime(start.replace(" ", ""), "%H:%M").time()
        else:
            s = None
        if end:
            e = datetime.strptime(end.replace(" ", ""), "%H:%M").time()
        else:
            e = None
        if s is not None and e is not None:
            if e <= s:
                # Window spans midnight (e.g. 15:00–00:00): in window iff now >= start OR now <= end
                return now >= s or now <= e
            else:
                # Normal window: in window iff start <= now <= end
                return now >= s and now <= e
        if s is not None and now < s:
            return False
        if e is not None and now > e:
            return False
    except Exception:
        return True
    return True


def get_user_by_username(conn, username: str) -> Optional[Dict]:
    cur = conn.execute("SELECT * FROM users WHERE LOWER(TRIM(username)) = LOWER(TRIM(?))", (username,))
    row = cur.fetchone()
    if not row:
        return None
    return dict(row)


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = _now_ts()
    conn.execute(
        "INSERT INTO sessions (user_id, token, last_activity_at_ts, created_at_ts) VALUES (?, ?, ?, ?)",
        (user_id, token, now, now),
    )
    conn.commit()
    return token


def get_user_by_token(conn, token: str) -> Optional[Dict]:
    if not token:
        return None
    cur = conn.execute(
        "SELECT sessions.user_id, sessions.last_activity_at_ts FROM sessions WHERE token = ?",
        (token,),
    )
    row = cur.fetchone()
    if not row:
        return None
    now = _now_ts()
    ttl_sec = get_session_ttl_seconds(conn, user_id=row["user_id"])
    if ttl_sec is not None and (now - row["last_activity_at_ts"]) > ttl_sec:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        return None
    conn.execute("UPDATE sessions SET last_activity_at_ts = ? WHERE token = ?", (now, token))
    conn.commit()
    cur = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],))
    u = cur.fetchone()
    return dict(u) if u else None


def delete_session(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def login_flow(username: str, password: str, ip: str) -> Tuple[bool, Optional[str], Optional[Dict]]:
    """
    Returns (success, error_message, user_dict).
    On success, caller should create session and set cookie.
    """
    ensure_auth_db()
    conn = connect_auth_db()
    try:
        user = get_user_by_username(conn, username)
        if not user:
            record_login_attempt(conn, None, username, ip, False)
            return False, "Invalid username or password", None
        is_admin = (user.get("role") or "").lower() == "admin"
        if not is_admin and is_user_locked(conn, user["id"]):
            record_login_attempt(conn, user["id"], username, ip, False)
            return False, "Account locked. Contact admin or wait 1 hour.", None
        if not check_password(user, password):
            record_login_attempt(conn, user["id"], username, ip, False)
            if not is_admin:
                maybe_lock_user(conn, user["id"])
            return False, "Invalid username or password", None
        if not in_allowed_time_window(user):
            record_login_attempt(conn, user["id"], username, ip, False)
            return False, "Login not allowed at this time.", None
        if not is_ip_allowed(conn, user["id"], ip):
            record_login_attempt(conn, user["id"], username, ip, False)
            return False, "IP not allowed. Contact admin to add your IP.", None
        record_login_attempt(conn, user["id"], username, ip, True)
        # First successful login: if no IPs yet, add this IP (unless allow_all_ip)
        if not user.get("allow_all_ip"):
            cur = conn.execute("SELECT 1 FROM user_allowed_ips WHERE user_id = ?", (user["id"],))
            if cur.fetchone() is None:
                add_user_ip(conn, user["id"], ip)
        return True, None, user
    finally:
        conn.close()


VALID_PAGE_KEYS = frozenset({"debug", "repair", "jump-station", "kitting-sql", "testing", "trial-run"})


def get_user_page_permissions(conn, user_id: int) -> set:
    """Return set of page_key strings the user is allowed to access."""
    cur = conn.execute(
        "SELECT page_key FROM user_page_permissions WHERE user_id = ?",
        (user_id,),
    )
    return {row["page_key"] for row in cur.fetchall() if row["page_key"] in VALID_PAGE_KEYS}


def set_user_page_permissions(conn, user_id: int, page_keys: list) -> None:
    """Replace user's page permissions. page_keys: list of page_key strings."""
    conn.execute("DELETE FROM user_page_permissions WHERE user_id = ?", (user_id,))
    for pk in page_keys:
        pk = (pk or "").strip().lower()
        if pk in VALID_PAGE_KEYS:
            conn.execute(
                "INSERT OR IGNORE INTO user_page_permissions (user_id, page_key) VALUES (?, ?)",
                (user_id, pk),
            )
    conn.commit()


def get_current_user(request) -> Optional[Dict]:
    """Get user from auth_token cookie; refresh session TTL. Returns None if invalid/expired."""
    token = request.cookies.get("auth_token") or (request.headers.get("Authorization") or "").replace("Bearer ", "").strip()
    if not token:
        return None
    ensure_auth_db()
    conn = connect_auth_db()
    try:
        return get_user_by_token(conn, token)
    finally:
        conn.close()


def default_emp_for_ui(user: Optional[Dict]) -> str:
    """Default EMP / employee ID for form fields: profile employee_id, else username, else SJOP."""
    if not user:
        return "SJOP"
    eid = (user.get("employee_id") or "").strip()
    if eid:
        return eid
    un = (user.get("username") or "").strip()
    if un:
        return un
    return "SJOP"


def resolve_sfis_emp(request, explicit: Optional[str] = None, *, last_resort: str = "SJOP") -> str:
    """
    EMP for Oracle/SFIS actions. Non-empty explicit (e.g. from JSON body) wins so the user can override.
    Otherwise logged-in user's employee_id, then username, then last_resort.
    """
    if explicit is not None:
        t = (explicit or "").strip()
        if t:
            return t
    u = getattr(request, "current_user", None) or {}
    eid = (u.get("employee_id") or "").strip()
    if eid:
        return eid
    un = (u.get("username") or "").strip()
    if un:
        return un
    return last_resort
