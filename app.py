# -*- coding: utf-8 -*-
"""
SFC_View: Flask app on port 5556.
User picks start/end datetime -> Apply Filter -> SFC API (with -2h/+2h) -> parse HTML -> filter -> analytics.
Also includes bonepile upload and disposition.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from flask import Flask, jsonify, render_template, request, send_file
import io

from sfc.client import request_fail_result
from sfc.parser import parse_fail_result_html, rows_to_csv
from analytics.compute import compute_all
from analytics.sn_list import compute_sn_list
from bonepile_disposition import (
    ensure_db_ready, RawState, _bonepile_status_payload, _save_uploaded_bonepile_file,
    _copy_for_parse, new_job_id, set_job, run_bonepile_parse_job,
    _load_bonepile_workbook, _find_header_row, _read_header_map, _auto_mapping_from_headers,
    _mapping_errors, _close_and_release_workbook, _remove_temp_file,
    _parse_ca_input_datetime, utc_ms, compute_disposition_stats, compute_disposition_sn_list,
    BONEPILE_UPLOAD_PATH, BONEPILE_ALLOWED_SHEETS, ANALYTICS_CACHE_DIR, scan_lock, jobs_lock, jobs
)

app = Flask(__name__)

# Cache last query result for sn-list drill-down
_last_query_lock = threading.Lock()
_last_query_result: Optional[Dict[str, Any]] = None


def _parse_datetime(s: Optional[str], is_end: bool = False) -> Optional[datetime]:
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
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


@app.route("/")
def index():
    """Serve analytics dashboard."""
    return render_template("analytics_dashboard.html")


@app.route("/api/query", methods=["POST"])
def api_query():
    """
    Apply Filter: Body { start_datetime, end_datetime, aggregation?: daily|weekly|monthly }
    Calls SFC API, parses HTML, computes analytics. Caches result for sn-list.
    """
    global _last_query_result
    payload = request.json or {}
    start_s = (payload.get("start_datetime") or "").strip()
    end_s = (payload.get("end_datetime") or "").strip()
    aggregation = (payload.get("aggregation") or "daily").strip().lower()
    if aggregation not in ("daily", "weekly", "monthly"):
        aggregation = "daily"

    user_start = _parse_datetime(start_s, is_end=False)
    user_end = _parse_datetime(end_s, is_end=True)
    if user_start is None or user_end is None:
        return jsonify({"error": "start_datetime and end_datetime required (YYYY-MM-DD HH:MM)"}), 400
    if user_end < user_start:
        return jsonify({"error": "end must be after start"}), 400

    ok, html = request_fail_result(user_start, user_end)
    if not ok:
        return jsonify({"error": "SFC API request failed (login or fail_result)"}), 502

    rows = parse_fail_result_html(html, user_start=user_start, user_end=user_end)
    computed = compute_all(rows, aggregation=aggregation)

    with _last_query_lock:
        _last_query_result = computed

    out = {
        "ok": True,
        "summary": computed["summary"],
        "tray_summary": computed["tray_summary"],
        "sku_rows": computed["sku_rows"],
        "breakdown_rows": computed["breakdown_rows"],
        "test_flow": computed["test_flow"],
        "rows": computed["rows"],
    }
    return jsonify(out)


@app.route("/api/sn-list", methods=["POST"])
def api_sn_list():
    """
    Drill-down SN list. Body: { metric, sku?, period?, station?, outcome?, aggregation? }
    Uses last query result from /api/query.
    """
    payload = request.json or {}
    metric = (payload.get("metric") or "total").strip().lower()
    sku = (payload.get("sku") or "").strip() or None
    period = (payload.get("period") or "").strip() or None
    station = (payload.get("station") or "").strip() or None
    outcome = (payload.get("outcome") or "").strip().lower() or None
    if outcome and outcome not in ("pass", "fail"):
        outcome = None
    aggregation = (payload.get("aggregation") or "daily").strip().lower()
    if aggregation not in ("daily", "weekly", "monthly"):
        aggregation = "daily"

    with _last_query_lock:
        computed = _last_query_result

    if not computed:
        return jsonify({"error": "Apply filter first", "count": 0, "rows": []}), 400

    try:
        rows = compute_sn_list(
            computed,
            metric=metric,
            sku=sku,
            period=period,
            station=station,
            outcome=outcome,
            aggregation=aggregation,
        )
        return jsonify({"ok": True, "count": len(rows), "rows": rows})
    except Exception as e:
        return jsonify({"error": str(e), "count": 0, "rows": []}), 500


@app.route("/api/fail_result", methods=["POST"])
def api_fail_result():
    """Legacy: returns rows + csv. Prefer /api/query."""
    payload = request.json or {}
    start_s = (payload.get("start_datetime") or "").strip()
    end_s = (payload.get("end_datetime") or "").strip()

    user_start = _parse_datetime(start_s, is_end=False)
    user_end = _parse_datetime(end_s, is_end=True)
    if user_start is None or user_end is None:
        return jsonify({"error": "start_datetime and end_datetime required (YYYY-MM-DD HH:MM)"}), 400
    if user_end < user_start:
        return jsonify({"error": "end must be after start"}), 400

    ok, html = request_fail_result(user_start, user_end)
    if not ok:
        return jsonify({"error": "SFC API request failed (login or fail_result)"}), 502

    rows = parse_fail_result_html(html, user_start=user_start, user_end=user_end)
    csv_str = rows_to_csv(rows, include_bp=False)

    return jsonify({
        "ok": True,
        "rows": rows,
        "csv": csv_str,
        "count": len(rows),
    })


@app.route("/api/export", methods=["POST"])
@app.route("/api/export/csv", methods=["POST"])
def api_export_csv():
    """Export CSV with BP column. Body: { start_datetime, end_datetime }."""
    payload = request.json or {}
    start_s = (payload.get("start_datetime") or "").strip()
    end_s = (payload.get("end_datetime") or "").strip()

    user_start = _parse_datetime(start_s, is_end=False)
    user_end = _parse_datetime(end_s, is_end=True)
    if user_start is None or user_end is None:
        return jsonify({"error": "start_datetime and end_datetime required"}), 400
    if user_end < user_start:
        return jsonify({"error": "end must be after start"}), 400

    ok, html = request_fail_result(user_start, user_end)
    if not ok:
        return jsonify({"error": "SFC API request failed"}), 502

    rows = parse_fail_result_html(html, user_start=user_start, user_end=user_end)
    from analytics.bp_check import add_bp_to_rows
    rows = add_bp_to_rows(rows)
    csv_str = rows_to_csv(rows, include_bp=True)
    filename = f"fail_result_{user_start.strftime('%Y%m%d_%H%M')}_to_{user_end.strftime('%Y%m%d_%H%M')}.csv"

    buf = io.BytesIO(csv_str.encode("utf-8-sig"))
    return send_file(
        buf,
        mimetype="text/csv; charset=utf-8-sig",
        as_attachment=True,
        download_name=filename,
    )


# -----------------------------
# Bonepile Upload & Disposition Routes (copied from Bonepile_view)
# -----------------------------


@app.route("/api/job/<job_id>")
def api_job(job_id: str):
    """Get job status."""
    with jobs_lock:
        data = jobs.get(job_id)
    if not data:
        return jsonify({"error": "job not found"}), 404
    return jsonify(data)


@app.route("/api/bonepile/status")
def api_bonepile_status():
    """Get bonepile upload/parse status."""
    ensure_db_ready()
    state = RawState.load()
    return jsonify(_bonepile_status_payload(state))


@app.route("/api/bonepile/upload", methods=["POST"])
def api_bonepile_upload():
    """
    Upload NV/IGS workbook. The backend stores only the latest file (replaces previous).
    After upload, automatically parse all allowed sheets with auto-detect.
    """
    try:
        ensure_db_ready()
        try:
            import openpyxl
        except ImportError:
            openpyxl = None
        if openpyxl is None:
            return jsonify({"error": "openpyxl not installed; cannot accept XLSX"}), 500
        if "file" not in request.files:
            return jsonify({"error": "file is required"}), 400
        f = request.files["file"]
        if not f or not getattr(f, "filename", ""):
            return jsonify({"error": "no file selected"}), 400
        name = str(f.filename)
        if not name.lower().endswith(".xlsx"):
            return jsonify({"error": "only .xlsx is supported for bonepile upload"}), 400

        with scan_lock:
            state = RawState.load()
            meta = _save_uploaded_bonepile_file(f)
            state.bonepile_file = meta
            state.bonepile_sheet_status = state.bonepile_sheet_status or {}
            state.save()

        job_id = new_job_id()
        parse_copy = os.path.join(ANALYTICS_CACHE_DIR, "bonepile_parse_" + job_id + ".xlsx")
        if not _copy_for_parse(parse_copy):
            return jsonify({"error": "Upload ok but could not start parse (file in use?)"}), 500
        set_job(job_id, status="queued", message="Auto-parsing all sheets with auto-detect...")
        t = threading.Thread(target=run_bonepile_parse_job, args=(job_id, None), kwargs={"path": parse_copy}, daemon=True)
        t.start()
        return jsonify({"ok": True, "job_id": job_id, "bonepile_file": meta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bonepile/sheets")
def api_bonepile_sheets():
    """Return sheet list."""
    try:
        import openpyxl
    except ImportError:
        openpyxl = None
    if openpyxl is None:
        return jsonify({"error": "openpyxl not installed; cannot read XLSX"}), 500
    state = RawState.load()
    if not os.path.exists(BONEPILE_UPLOAD_PATH):
        return jsonify({"ok": True, "has_file": False, "allowed": BONEPILE_ALLOWED_SHEETS, "ignored": [], "sheets": {}})
    import shutil
    fd, copy_path = tempfile.mkstemp(suffix=".xlsx", prefix="bonepile_sheets_", dir=ANALYTICS_CACHE_DIR)
    os.close(fd)
    wb = None
    try:
        shutil.copy2(BONEPILE_UPLOAD_PATH, copy_path)
        wb = _load_bonepile_workbook(copy_path)
        all_sheets = list(wb.sheetnames)
        ignored = [s for s in all_sheets if s not in BONEPILE_ALLOWED_SHEETS]
        out: dict = {}
        for sheet in BONEPILE_ALLOWED_SHEETS:
            if sheet not in all_sheets:
                out[sheet] = {"present": False}
                continue
            ws = wb[sheet]
            header_row = _find_header_row(ws) or 0
            header_map = _read_header_map(ws, header_row) if header_row else {}
            auto_map = _auto_mapping_from_headers(header_map) if header_map else {}
            errs = _mapping_errors(auto_map, header_map) if header_map else ["Header row not found (SN)"]
            out[sheet] = {
                "present": True,
                "header_row": int(header_row) if header_row else None,
                "headers": list(header_map.keys())[:80],
                "auto_columns": auto_map,
                "auto_errors": errs,
                "saved_mapping": (state.bonepile_mapping or {}).get(sheet),
                "status": (state.bonepile_sheet_status or {}).get(sheet),
            }
        return jsonify({"ok": True, "has_file": True, "allowed": BONEPILE_ALLOWED_SHEETS, "ignored": ignored, "sheets": out})
    except Exception as e:
        return jsonify({"error": "Failed to read workbook: " + str(e)}), 500
    finally:
        if wb is not None:
            _close_and_release_workbook(wb)
            wb = None
        _remove_temp_file(copy_path)


@app.route("/api/bonepile/mapping", methods=["POST"])
def api_bonepile_mapping():
    """
    Save mapping for a single sheet:
      { sheet, header_row, columns: {sn, nv_disposition, status, pic, igs_action, igs_status, nvpn?} }
    """
    payload = request.json or {}
    sheet = str(payload.get("sheet") or "").strip()
    if sheet not in BONEPILE_ALLOWED_SHEETS:
        return jsonify({"error": "invalid sheet"}), 400
    header_row = int(payload.get("header_row") or 0)
    columns = payload.get("columns") if isinstance(payload.get("columns"), dict) else {}
    if header_row <= 0:
        return jsonify({"error": "header_row must be >= 1"}), 400

    with scan_lock:
        state = RawState.load()
        if state.bonepile_mapping is None:
            state.bonepile_mapping = {}
        state.bonepile_mapping[sheet] = {"header_row": int(header_row), "columns": columns}
        state.save()

    job_id = new_job_id()
    parse_copy = os.path.join(ANALYTICS_CACHE_DIR, "bonepile_parse_" + job_id + ".xlsx")
    if not os.path.exists(BONEPILE_UPLOAD_PATH) or not _copy_for_parse(parse_copy):
        return jsonify({"error": "Could not copy workbook for parse (file missing or in use)"}), 500
    set_job(job_id, status="queued", message=f"Parsing {sheet}...")
    t = threading.Thread(target=run_bonepile_parse_job, args=(job_id, [sheet]), kwargs={"path": parse_copy}, daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/bonepile/parse", methods=["POST"])
def api_bonepile_parse():
    """Trigger parse job (all sheets or a single sheet)."""
    ensure_db_ready()
    payload = request.json or {}
    sheet = str(payload.get("sheet") or "").strip() if payload.get("sheet") is not None else ""
    sheets: Optional[list] = None
    if sheet:
        if sheet not in BONEPILE_ALLOWED_SHEETS:
            return jsonify({"error": "invalid sheet"}), 400
        sheets = [sheet]
    job_id = new_job_id()
    parse_copy = os.path.join(ANALYTICS_CACHE_DIR, "bonepile_parse_" + job_id + ".xlsx")
    if not os.path.exists(BONEPILE_UPLOAD_PATH) or not _copy_for_parse(parse_copy):
        return jsonify({"error": "Could not copy workbook for parse (file missing or in use)"}), 500
    set_job(job_id, status="queued", message="Bonepile parse queued")
    t = threading.Thread(target=run_bonepile_parse_job, args=(job_id, sheets), kwargs={"path": parse_copy}, daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/bonepile/disposition")
def api_bonepile_disposition():
    """
    NV Disposition stats from bonepile_entries.
    Query: aggregation=daily|weekly|monthly (default daily), start_datetime, end_datetime (optional).
    Returns: summary { total, waiting_igs, complete }, by_sku, by_period.
    """
    ensure_db_ready()
    aggregation = request.args.get("aggregation", "daily").strip().lower()
    if aggregation not in ("daily", "weekly", "monthly"):
        aggregation = "daily"
    start_dt = request.args.get("start_datetime")
    end_dt = request.args.get("end_datetime")
    start_ca_ms = None
    end_ca_ms = None
    if start_dt:
        start_ca = _parse_ca_input_datetime(start_dt, is_end=False)
        if start_ca:
            start_ca_ms = utc_ms(start_ca)
    if end_dt:
        end_ca = _parse_ca_input_datetime(end_dt, is_end=True)
        if end_ca:
            end_ca_ms = utc_ms(end_ca)
    try:
        data = compute_disposition_stats(aggregation=aggregation, start_ca_ms=start_ca_ms, end_ca_ms=end_ca_ms)
        return jsonify({"ok": True, **data})
    except sqlite3.OperationalError:
        return jsonify({
            "ok": True,
            "summary": {"total": 0, "waiting_igs": 0, "complete": 0, "unique_trays_bp": 0, "all_pass_trays": 0},
            "by_sku": [],
            "by_period": [],
            "tray_by_sku": [],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bonepile/disposition/sn-list", methods=["POST"])
def api_bonepile_disposition_sn_list():
    """
    SN list for disposition drill-down.
    Body: { metric: total|waiting|complete, sku?: string, period?: string, aggregation?: daily|weekly|monthly, start_datetime?, end_datetime? }.
    """
    ensure_db_ready()
    payload = request.json or {}
    metric = str(payload.get("metric") or "total").strip().lower()
    if metric not in ("total", "waiting", "complete", "trays_bp", "all_pass_trays"):
        metric = "total"
    sku = (payload.get("sku") or "").strip() or None
    period = (payload.get("period") or "").strip() or None
    aggregation = str(payload.get("aggregation") or "daily").strip().lower()
    if aggregation not in ("daily", "weekly", "monthly"):
        aggregation = "daily"
    start_dt = payload.get("start_datetime")
    end_dt = payload.get("end_datetime")
    start_ca_ms = None
    end_ca_ms = None
    if start_dt:
        start_ca = _parse_ca_input_datetime(start_dt, is_end=False)
        if start_ca:
            start_ca_ms = utc_ms(start_ca)
    if end_dt:
        end_ca = _parse_ca_input_datetime(end_dt, is_end=True)
        if end_ca:
            end_ca_ms = utc_ms(end_ca)
    try:
        rows = compute_disposition_sn_list(metric=metric, sku=sku, period=period, aggregation=aggregation, start_ca_ms=start_ca_ms, end_ca_ms=end_ca_ms)
        return jsonify({"ok": True, "count": len(rows), "rows": rows})
    except sqlite3.OperationalError:
        return jsonify({"ok": True, "count": 0, "rows": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5556, debug=True)
