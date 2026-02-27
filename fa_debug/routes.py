# -*- coding: utf-8 -*-
"""FA Debug Place Flask blueprint: /debug route, /api/debug-query, /api/debug-data, background poller."""

import json
import os
import threading
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request

from analytics.compute import compute_all
from config.app_config import ANALYTICS_CACHE_DIR
from config.debug_config import LOOKBACK_HOURS, POLL_INTERVAL_SEC
from fa_debug.logic import prepare_debug_rows
from sfc.client import request_fail_result
from sfc.parser import parse_fail_result_html

bp = Blueprint("fa_debug", __name__, url_prefix="", template_folder="../templates")

_upload_history_path = os.path.join(ANALYTICS_CACHE_DIR, "agent_upload_history.json")
_upload_history_lock = threading.Lock()

_debug_cache_lock = threading.Lock()
_debug_cache = None
_poller_started = False


def _parse_dt(s, is_end=False):
    if not s or not str(s).strip():
        return None
    s = str(s).strip()[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%Y-%m-%d" and is_end:
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif fmt == "%Y-%m-%d":
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return dt
        except ValueError:
            continue
    return None


def _fetch_debug_data(user_start, user_end):
    ok, html = request_fail_result(user_start, user_end)
    if not ok:
        return None
    rows = parse_fail_result_html(html, user_start=user_start, user_end=user_end)
    computed = compute_all(rows, aggregation="daily")
    prepared = prepare_debug_rows(computed["rows"])
    return {"summary": computed["summary"], "rows": prepared}


def _run_poller():
    global _debug_cache
    while True:
        try:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(hours=LOOKBACK_HOURS)
            data = _fetch_debug_data(start_dt, end_dt)
            if data:
                with _debug_cache_lock:
                    _debug_cache = {"summary": data["summary"], "rows": data["rows"], "start": start_dt.isoformat(), "end": end_dt.isoformat()}
        except Exception:
            pass
        threading.Event().wait(POLL_INTERVAL_SEC)


def _ensure_poller():
    global _poller_started
    if _poller_started:
        return
    with _debug_cache_lock:
        if _poller_started:
            return
        t = threading.Thread(target=_run_poller, daemon=True)
        t.start()
        _poller_started = True


@bp.route("/debug")
def debug_page():
    """Serve FA Debug Place page."""
    from config.debug_config import UPLOAD_URL, WS_TERMINAL_URL
    return render_template("fa_debug.html", ws_terminal_url=WS_TERMINAL_URL, upload_url=UPLOAD_URL)


def _load_upload_history():
    if not os.path.isfile(_upload_history_path):
        return {"entries": []}
    try:
        with open(_upload_history_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"entries": []}


def _append_upload_history(entries: list):
    with _upload_history_lock:
        data = _load_upload_history()
        data["entries"] = (data.get("entries") or []) + entries
        os.makedirs(os.path.dirname(_upload_history_path), exist_ok=True)
        with open(_upload_history_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


@bp.route("/api/fa-debug/agent-upload", methods=["POST"])
def api_fa_debug_agent_upload():
    """Proxy file upload to agent server (avoids CORS). Saves to upload history cache."""
    from config.debug_config import UPLOAD_FIELD_NAME, UPLOAD_URL
    import requests

    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        return jsonify({"error": "No files"}), 400
    row_key = (request.form.get("row_key") or "").strip()
    try:
        field = UPLOAD_FIELD_NAME
        req_files = [(field, (f.filename or "file", f.stream, f.content_type or "application/octet-stream")) for f in files]
        r = requests.post(UPLOAD_URL, files=req_files, timeout=60)
        if not r.ok:
            try:
                err_body = r.json()
            except Exception:
                err_body = {"detail": r.text[:500] if r.text else str(r.status_code)}
            return jsonify({"error": str(r.status_code), "detail": err_body}), r.status_code
        ct = r.headers.get("content-type", "")
        data = r.json() if "application/json" in ct else {"ok": True}

        # Save to upload history (new API: success, path, filename)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        to_append = []
        if isinstance(data, dict) and data.get("success") and data.get("path"):
            fn = data.get("filename") or (files[0].filename if files else "file")
            to_append.append({
                "filename": fn,
                "path": data.get("path") or "",
                "uploaded_at": now,
                "row_key": row_key or "",
            })
        if to_append:
            _append_upload_history(to_append)

        return jsonify(data)
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/api/fa-debug/upload-history", methods=["GET"])
def api_fa_debug_upload_history():
    """Return list of uploaded files (from cache)."""
    data = _load_upload_history()
    entries = data.get("entries") or []
    entries = list(reversed(entries))  # newest first
    return jsonify({"ok": True, "entries": entries})


@bp.route("/api/fa-debug/upload-history-clear", methods=["POST", "DELETE"])
def api_fa_debug_upload_history_clear():
    """Clear upload history cache (local only). Use when purge API is unavailable."""
    try:
        with _upload_history_lock:
            data = {"entries": []}
            os.makedirs(os.path.dirname(_upload_history_path), exist_ok=True)
            with open(_upload_history_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/fa-debug/upload-purge", methods=["DELETE"])
def api_fa_debug_upload_purge():
    """Proxy to AI server: purge all uploads. Query: delete_db_records, delete_minio, delete_agent_uploads (default true)."""
    from config.debug_config import AI_ADMIN_BASE_URL
    import requests

    if not AI_ADMIN_BASE_URL:
        return jsonify({"error": "AI_ADMIN_BASE_URL not configured"}), 500
    delete_db = request.args.get("delete_db_records", "true").lower() == "true"
    delete_minio = request.args.get("delete_minio", "true").lower() == "true"
    delete_agent = request.args.get("delete_agent_uploads", "true").lower() == "true"
    url = f"{AI_ADMIN_BASE_URL}/api/admin/uploads/purge-all"
    url += f"?delete_db_records={str(delete_db).lower()}&delete_minio={str(delete_minio).lower()}&delete_agent_uploads={str(delete_agent).lower()}"
    try:
        r = requests.delete(url, timeout=60)
        if not r.ok:
            return jsonify({"error": str(r.status_code), "detail": r.text[:500]}), r.status_code
        return jsonify(r.json() if r.content else {"ok": True})
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/api/debug-query", methods=["POST"])
def api_debug_query():
    """Query SFC with optional start/end. Returns summary + rows sorted by time desc."""
    payload = request.json or {}
    start_s = (payload.get("start_datetime") or "").strip()
    end_s = (payload.get("end_datetime") or "").strip()
    if start_s or end_s:
        user_start = _parse_dt(start_s, False)
        user_end = _parse_dt(end_s, True)
        if user_start is None or user_end is None:
            return jsonify({"error": "start_datetime and end_datetime required (YYYY-MM-DD HH:MM)"}), 400
        if user_end < user_start:
            return jsonify({"error": "end must be after start"}), 400
        data = _fetch_debug_data(user_start, user_end)
        if data is None:
            return jsonify({"error": "SFC API request failed"}), 502
    else:
        _ensure_poller()
        with _debug_cache_lock:
            data = _debug_cache
        if data is None:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(hours=LOOKBACK_HOURS)
            data = _fetch_debug_data(start_dt, end_dt)
            if data is None:
                return jsonify({"error": "SFC API request failed"}), 502
    return jsonify({"ok": True, "summary": data["summary"], "rows": data["rows"]})


@bp.route("/api/debug/log-path-debug", methods=["GET"])
def api_debug_log_path_debug():
    """Debug Crabber API: ?sn=XXX - returns step-by-step result to diagnose 404."""
    sn = (request.args.get("sn") or "").strip()
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    try:
        from crabber.client import fetch_log_report_path_debug
        result = fetch_log_report_path_debug(sn)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/log-path", methods=["GET"])
def api_debug_log_path():
    """Fetch Log Report File Path for SN via Crabber API. Query: ?sn=XXX"""
    sn = (request.args.get("sn") or "").strip()
    if not sn:
        return jsonify({"ok": False, "error": "sn required", "path": None}), 400
    try:
        from crabber.client import fetch_log_report_path
        path = fetch_log_report_path(sn)
        if path is None:
            return jsonify({"ok": False, "error": "Not found or Crabber API disabled", "path": None}), 404
        return jsonify({"ok": True, "path": path})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "path": None}), 502


@bp.route("/api/debug-data", methods=["GET"])
def api_debug_data():
    """Return cached poller data. Starts poller if not running."""
    _ensure_poller()
    with _debug_cache_lock:
        data = _debug_cache
    if data is None:
        return jsonify({"ok": True, "summary": {"total": 0, "pass": 0, "fail": 0}, "rows": []})
    return jsonify({"ok": True, "summary": data["summary"], "rows": data["rows"]})
