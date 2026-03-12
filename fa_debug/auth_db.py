# -*- coding: utf-8 -*-
"""Auth DB: schema, seed admin, connect. Used by fa_debug auth and setting."""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Optional

from werkzeug.security import generate_password_hash

_db_lock = threading.Lock()


def get_auth_db_path() -> str:
    from config.app_config import ANALYTICS_CACHE_DIR
    path = os.environ.get("AUTH_DB_PATH") or os.path.join(ANALYTICS_CACHE_DIR, "auth.db")
    return path


def connect_auth_db() -> sqlite3.Connection:
    path = get_auth_db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db() -> None:
    """Create tables if not exist; seed admin (admin/123) if no admin."""
    with _db_lock:
        conn = connect_auth_db()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    department TEXT NOT NULL,
                    employee_id TEXT NOT NULL,
                    email TEXT,
                    role TEXT NOT NULL DEFAULT 'user',
                    allowed_login_start_time TEXT,
                    allowed_login_end_time TEXT,
                    allow_all_ip INTEGER NOT NULL DEFAULT 0,
                    locked_until_ts INTEGER,
                    session_ttl_minutes TEXT,
                    created_at_ts INTEGER NOT NULL,
                    updated_at_ts INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_allowed_ips (
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    ip TEXT NOT NULL,
                    PRIMARY KEY (user_id, ip)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS registration_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    department TEXT NOT NULL,
                    employee_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    email TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at_ts INTEGER NOT NULL,
                    reviewed_at_ts INTEGER,
                    reviewed_by INTEGER REFERENCES users(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    token TEXT UNIQUE NOT NULL,
                    last_activity_at_ts INTEGER NOT NULL,
                    created_at_ts INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS login_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    ip TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    created_at_ts INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS familiar_ips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    ip TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute(
                "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
                ("session_ttl_minutes", "30"),
            )
            conn.commit()

            import time
            now = int(time.time())
            cur = conn.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
            if cur.fetchone() is None:
                pw_hash = generate_password_hash("123", method="scrypt")
                conn.execute("""
                    INSERT INTO users (username, password_hash, full_name, department, employee_id, email, role, allow_all_ip, created_at_ts, updated_at_ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, ("admin", pw_hash, "Administrator", "OTHER", "0", None, "admin", 1, now, now))
                conn.commit()
        finally:
            conn.close()


def ensure_auth_db() -> None:
    """Call on first auth use to ensure schema and admin exist."""
    path = get_auth_db_path()
    if not os.path.isfile(path):
        init_auth_db()
        return
    with _db_lock:
        conn = connect_auth_db()
        try:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if cur.fetchone() is None:
                conn.close()
                init_auth_db()
                return
            cur = conn.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
            if cur.fetchone() is None:
                import time
                now = int(time.time())
                pw_hash = generate_password_hash("123", method="scrypt")
                conn.execute("""
                    INSERT INTO users (username, password_hash, full_name, department, employee_id, email, role, allow_all_ip, created_at_ts, updated_at_ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, ("admin", pw_hash, "Administrator", "OTHER", "0", None, "admin", 1, now, now))
                conn.commit()
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='app_settings'")
            if cur.fetchone() is None:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                conn.execute(
                    "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
                    ("session_ttl_minutes", "30"),
                )
                conn.commit()
            cur = conn.execute("PRAGMA table_info(users)")
            cols = [r[1] for r in cur.fetchall()]
            if "session_ttl_minutes" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN session_ttl_minutes TEXT")
                conn.commit()
        finally:
            conn.close()


def get_app_setting(conn: sqlite3.Connection, key: str) -> Optional[str]:
    """Return value for key from app_settings, or None if missing."""
    cur = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
    row = cur.fetchone()
    return row["value"] if row and row["value"] is not None else None


def set_app_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Set key=value in app_settings (insert or replace). Caller must commit."""
    conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, value))
