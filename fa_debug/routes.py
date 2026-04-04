# -*- coding: utf-8 -*-
"""FA Debug Place Flask blueprint: /debug route, /api/debug-query, /api/debug-data, background poller."""

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import datetime, timedelta
from typing import List

from flask import Blueprint, jsonify, redirect, render_template, request

from analytics.service import run_analytics_query
from config.app_config import ANALYTICS_CACHE_DIR
from config.debug_config import (
    CRABBER_PAGE_TIMEOUT_SEC,
    CRABBER_PROC_RECONCILE_MAX_SN,
    CRABBER_RECONCILE_TIMEOUT_SEC,
    LOOKBACK_HOURS,
    POLL_INTERVAL_MS,
    POLL_INTERVAL_SEC,
)
from fa_debug.auth import (
    default_emp_for_ui,
    get_current_user,
    get_user_page_permissions,
    resolve_sfis_emp,
    set_user_page_permissions,
)
from fa_debug.auth_db import connect_auth_db, ensure_auth_db
from fa_debug.logic import (
    merge_timeline_with_crabber_proc,
    prepare_debug_rows,
    timeline_rows_from_crabber_proc_items,
)

bp = Blueprint("fa_debug", __name__, url_prefix="", template_folder="../templates")
_logger = logging.getLogger(__name__)

# (prefix, frozenset of page_key values — user needs ANY of these, unless admin)
_URL_ACCESS_RULES = [
    ("/debug/repair", frozenset({"repair"})),
    ("/api/debug/repair/", frozenset({"repair", "testing"})),
    ("/debug/jump-station", frozenset({"jump-station"})),
    ("/api/debug/jump-station/", frozenset({"jump-station"})),
    ("/debug/kitting", frozenset({"kitting-sql"})),
    ("/debug/kitting-sql", frozenset({"kitting-sql"})),
    ("/api/debug/kitting-sql/", frozenset({"kitting-sql"})),
    ("/debug/testing", frozenset({"testing"})),
    ("/api/debug/testing/", frozenset({"testing"})),
    ("/api/debug-query", frozenset({"debug"})),
    ("/api/debug-data", frozenset({"debug"})),
    ("/api/fa-debug/", frozenset({"debug", "testing"})),
    ("/api/etf/online-test/", frozenset({"debug", "testing"})),
    ("/api/debug/log-path-debug", frozenset({"debug"})),
    ("/api/debug/log-path", frozenset({"debug", "testing"})),
    ("/debug", frozenset({"debug"})),
]


def _url_required_page_keys(path: str) -> frozenset | None:
    """Return required page_key set for path, or None if no permission check (my-settings, setting, unknown)."""
    if path in ("/debug/my-settings", "/debug/setting"):
        return None
    for prefix, keys in _URL_ACCESS_RULES:
        if path == prefix or (len(path) > len(prefix) and path.startswith(prefix)):
            return keys
    return None


@bp.before_request
def require_auth():
    """All fa_debug routes require valid auth token. Check page permissions. Redirect to /login or 401/403."""
    user = get_current_user(request)
    if user is None:
        accept = request.headers.get("Accept") or ""
        if "text/html" in accept:
            return redirect("/login")
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    request.current_user = user
    path = (request.path or "").rstrip("/") or "/"
    required_keys = _url_required_page_keys(path)
    is_admin = (user.get("role") or "").lower() == "admin"
    ensure_auth_db()
    conn = connect_auth_db()
    try:
        allowed_pages = get_user_page_permissions(conn, user["id"]) if not is_admin else {
            "debug",
            "repair",
            "jump-station",
            "kitting-sql",
            "testing",
        }
    finally:
        conn.close()
    request.allowed_pages = allowed_pages
    if required_keys is not None and not is_admin and not (allowed_pages & required_keys):
        accept = request.headers.get("Accept") or ""
        if "text/html" in accept:
            return redirect("/debug")
        return jsonify({"ok": False, "error": "Permission denied for this page"}), 403
    return None

_upload_history_path = os.path.join(ANALYTICS_CACHE_DIR, "agent_upload_history.json")
_upload_history_lock = threading.Lock()

_default_online_test_pn_bases = [
    "VR200_L10",
]
_crabber_test_pn_path = os.path.join(ANALYTICS_CACHE_DIR, "crabber_test_pns.json")


def _load_custom_pn_bases():
    if not os.path.isfile(_crabber_test_pn_path):
        return []
    try:
        with open(_crabber_test_pn_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
        return [str(x).strip() for x in (data.get("custom") or data.get("extra") or []) if str(x).strip()]
    except Exception:
        return []


def _save_custom_pn_bases(custom_list):
    os.makedirs(os.path.dirname(_crabber_test_pn_path), exist_ok=True)
    with open(_crabber_test_pn_path, "w", encoding="utf-8") as f:
        json.dump({"custom": custom_list}, f, indent=2, ensure_ascii=False)


def _merge_pn_base_list():
    """Return list of dicts: [{base, is_default}, ...]."""
    custom = _load_custom_pn_bases()
    seen: set = set()
    out: list = []
    for p in _default_online_test_pn_bases:
        u = (p or "").strip()
        if u and u.upper() not in seen:
            seen.add(u.upper())
            out.append({"base": u, "is_default": True})
    for p in custom:
        u = (p or "").strip()
        if u and u.upper() not in seen:
            seen.add(u.upper())
            out.append({"base": u, "is_default": False})
    return out

_debug_cache_lock = threading.Lock()
_debug_cache = None
_poller_started = False
_prev_proc_lock = threading.Lock()
_prev_proc_sns_prod: set = set()
_prev_proc_sns_offline: set = set()
_repair_sn_locks_guard = threading.Lock()
_repair_sn_locks = {}
_repair_request_cache = {}
_REPAIR_REQ_TTL_SEC = 300


def _get_sn_lock(sn):
    key = (sn or "").strip().upper()
    with _repair_sn_locks_guard:
        lk = _repair_sn_locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _repair_sn_locks[key] = lk
        return lk


def _cache_repair_response(sn, request_id, resp_obj):
    if not request_id:
        return
    key = ((sn or "").strip().upper(), str(request_id).strip())
    now = int(time.time())
    _repair_request_cache[key] = (now + _REPAIR_REQ_TTL_SEC, resp_obj)
    expired = [k for k, v in _repair_request_cache.items() if v[0] < now]
    for k in expired:
        _repair_request_cache.pop(k, None)


def _get_cached_repair_response(sn, request_id):
    if not request_id:
        return None
    key = ((sn or "").strip().upper(), str(request_id).strip())
    now = int(time.time())
    item = _repair_request_cache.get(key)
    if not item:
        return None
    expire_ts, resp = item
    if expire_ts < now:
        _repair_request_cache.pop(key, None)
        return None
    return resp


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


def _enrich_proc_part_numbers(rows: List[dict]) -> None:
    """Fill part_number from Oracle WIP MODEL_NAME, then ETF tray cache."""
    if not rows:
        return
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next

        conn = get_conn()
        try:
            for r in rows:
                sn = (r.get("serial_number") or "").strip().upper()
                if not sn:
                    continue
                try:
                    row = get_station_and_next(conn, sn)
                    if row and len(row) > 2:
                        model = (row[2] or "").strip()
                        if model:
                            r["part_number"] = model
                except Exception:
                    pass
        finally:
            conn.close()
    except Exception:
        pass
    try:
        from etf.routes import etf_search_rows_cached

        for r in rows:
            if (r.get("part_number") or "").strip():
                continue
            sn = (r.get("serial_number") or "").strip()
            if not sn:
                continue
            try:
                for h in etf_search_rows_cached(sn):
                    pn = (h.get("pn") or "").strip()
                    if pn:
                        r["part_number"] = pn
                        break
            except Exception:
                pass
    except Exception:
        pass


def _apply_timeline_all_pass_labels(rows: List[dict]) -> None:
    """
    When Repair-style main_line_all_pass (WIP at or past T_VI), relabel only the
    **newest** PASS row per SN (by test_time_dt) to ALL PASS. Older PASS rows for
    the same SN stay PASS — current WIP must not repaint every historical line.
    Skips Crabber PROC rows.
    """
    from collections import defaultdict

    by_sn: dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        if not isinstance(r, dict) or r.get("crabber_proc"):
            continue
        if str(r.get("result") or "").strip().upper() != "PASS":
            continue
        sn = (r.get("serial_number") or "").strip().upper()
        if sn:
            by_sn[sn].append(r)
    if not by_sn:
        return
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.repair_flow import main_line_all_pass_for_sn

        conn = get_conn()
        try:
            for sn, pass_rows in by_sn.items():
                try:
                    ok = main_line_all_pass_for_sn(conn, sn)
                except Exception:
                    ok = False
                if not ok or not pass_rows:
                    continue
                best: dict | None = None
                best_dt: datetime | None = None
                for r in pass_rows:
                    dt = r.get("test_time_dt")
                    if not isinstance(dt, datetime):
                        continue
                    if best_dt is None or dt >= best_dt:
                        best_dt = dt
                        best = r
                if best is not None:
                    best["result"] = "ALL PASS"
        finally:
            conn.close()
    except Exception as e:
        _logger.warning("timeline ALL PASS labeling failed: %s", e)


def _fetch_debug_data(user_start, user_end):
    global _prev_proc_sns_prod, _prev_proc_sns_offline
    try:
        computed = run_analytics_query(user_start, user_end, aggregation="daily")
    except RuntimeError:
        return None
    prepared = prepare_debug_rows(computed["rows"])

    from crabber.client import (
        _extract_items_list,
        extract_l10_proc_first_per_sn,
        fetch_search_log_items_json,
        reconcile_l10_proc_items_for_sns,
    )

    def load_page(is_trial: bool):
        js, err = fetch_search_log_items_json(
            sn="",
            cur_page=1,
            is_trial=is_trial,
            timeout=CRABBER_PAGE_TIMEOUT_SEC,
        )
        if err:
            return [], err
        items = _extract_items_list(js) or []
        return extract_l10_proc_first_per_sn(items), None

    prod_items: list = []
    off_items: list = []
    try:
        with ThreadPoolExecutor(max_workers=2) as ex:
            fp = ex.submit(load_page, False)
            fo = ex.submit(load_page, True)
            prod_items, err_p = fp.result()
            off_items, err_o = fo.result()
        if err_p:
            _logger.warning("Crabber production search_log_items: %s", err_p)
        if err_o:
            _logger.warning("Crabber offline search_log_items: %s", err_o)
    except Exception as e:
        _logger.warning("Crabber parallel page fetch failed: %s", e)

    page_p_sns = {
        str(it.get("sn") or "").strip().upper()
        for it in prod_items
        if str(it.get("sn") or "").strip()
    }
    page_o_sns = {
        str(it.get("sn") or "").strip().upper()
        for it in off_items
        if str(it.get("sn") or "").strip()
    }

    with _prev_proc_lock:
        prev_p = set(_prev_proc_sns_prod)
        prev_o = set(_prev_proc_sns_offline)

    dropped_p = prev_p - page_p_sns
    dropped_o = prev_o - page_o_sns
    cap = max(0, CRABBER_PROC_RECONCILE_MAX_SN)
    try:
        extra_p = reconcile_l10_proc_items_for_sns(
            list(dropped_p)[:cap],
            False,
            timeout=CRABBER_RECONCILE_TIMEOUT_SEC,
        )
        extra_o = reconcile_l10_proc_items_for_sns(
            list(dropped_o)[:cap],
            True,
            timeout=CRABBER_RECONCILE_TIMEOUT_SEC,
        )
    except Exception as e:
        _logger.warning("Crabber PROC reconcile failed: %s", e)
        extra_p = []
        extra_o = []

    seen_p = set(page_p_sns)
    for it in extra_p:
        snu = str(it.get("sn") or "").strip().upper()
        if snu and snu not in seen_p:
            prod_items.append(it)
            seen_p.add(snu)
    seen_o = set(page_o_sns)
    for it in extra_o:
        snu = str(it.get("sn") or "").strip().upper()
        if snu and snu not in seen_o:
            off_items.append(it)
            seen_o.add(snu)

    final_prod_sns = {
        str(it.get("sn") or "").strip().upper()
        for it in prod_items
        if str(it.get("sn") or "").strip()
    }
    final_off_sns_raw = {
        str(it.get("sn") or "").strip().upper()
        for it in off_items
        if str(it.get("sn") or "").strip()
    }
    with _prev_proc_lock:
        _prev_proc_sns_prod = set(final_prod_sns)
        _prev_proc_sns_offline = {s for s in final_off_sns_raw if s not in final_prod_sns}

    proc_prod_rows = timeline_rows_from_crabber_proc_items(prod_items, False)
    proc_off_rows = timeline_rows_from_crabber_proc_items(off_items, True)
    try:
        _enrich_proc_part_numbers(proc_prod_rows + proc_off_rows)
    except Exception as e:
        _logger.warning("PROC part_number enrich failed: %s", e)

    try:
        merged_rows = merge_timeline_with_crabber_proc(prepared, proc_prod_rows, proc_off_rows)
    except Exception as e:
        _logger.warning("merge_timeline_with_crabber_proc failed: %s", e)
        merged_rows = prepared

    try:
        _apply_timeline_all_pass_labels(merged_rows)
    except Exception as e:
        _logger.warning("timeline ALL PASS step failed: %s", e)

    return {
        "summary": computed["summary"],
        "rows": merged_rows,
        "l11_sns": computed.get("l11_sns", []),
        # Same pass/fail per SN as KPI (analytics pass_rules); drill-down must use this, not raw PASS rows.
        "sn_pass": computed.get("_sn_pass") or {},
    }


def _run_poller():
    global _debug_cache
    while True:
        t0 = time.monotonic()
        try:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(hours=LOOKBACK_HOURS)
            data = _fetch_debug_data(start_dt, end_dt)
            if data:
                with _debug_cache_lock:
                    _debug_cache = {
                        "summary": data["summary"],
                        "rows": data["rows"],
                        "l11_sns": data.get("l11_sns", []),
                        "sn_pass": data.get("sn_pass") or {},
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat(),
                    }
        except Exception as e:
            _logger.warning("debug poller cycle failed: %s", e)
        elapsed = time.monotonic() - t0
        wait_sec = max(0.0, float(POLL_INTERVAL_SEC) - elapsed)
        threading.Event().wait(wait_sec)


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
    from crabber.log_unc_path import get_crabber_log_unc_root

    user = getattr(request, "current_user", None)
    return render_template(
        "fa_debug.html",
        ws_terminal_url=WS_TERMINAL_URL,
        upload_url=UPLOAD_URL,
        poll_interval_ms=POLL_INTERVAL_MS,
        crabber_log_unc_root=get_crabber_log_unc_root(),
        current_user=user,
        allowed_pages=getattr(request, "allowed_pages", set()),
        default_employee_id=default_emp_for_ui(user),
    )


@bp.route("/debug/repair")
def debug_repair():
    """Repair page: SN search, WIP, tree, form, execute."""
    u = getattr(request, "current_user", None)
    return render_template(
        "debug_repair.html",
        current_user=u,
        allowed_pages=getattr(request, "allowed_pages", set()),
        default_employee_id=default_emp_for_ui(u),
    )


@bp.route("/debug/jump-station")
def debug_jump_station():
    """IT Jump page: move station flow UI."""
    u = getattr(request, "current_user", None)
    return render_template(
        "debug_jump_station.html",
        current_user=u,
        allowed_pages=getattr(request, "allowed_pages", set()),
        default_employee_id=default_emp_for_ui(u),
    )


@bp.route("/debug/kitting")
def debug_kitting_redirect():
    """Old IT Kitting (table_config) removed; send users to IT Kitting SQL."""
    return redirect("/debug/kitting-sql")


@bp.route("/debug/kitting-sql")
def debug_kitting_sql():
    """IT Kitting SQL page: assy tree by direct Oracle SQL."""
    u = getattr(request, "current_user", None)
    return render_template(
        "debug_kitting_sql.html",
        current_user=u,
        allowed_pages=getattr(request, "allowed_pages", set()),
        default_employee_id=default_emp_for_ui(u),
    )


@bp.route("/debug/testing")
def debug_testing():
    """SN-centric Testing page: tray summary, Crabber history, repair flow, kitting, four terminals."""
    from config.debug_config import UPLOAD_URL, WS_TERMINAL_URL
    from crabber.log_unc_path import get_crabber_log_unc_root

    u = getattr(request, "current_user", None)
    return render_template(
        "debug_testing.html",
        ws_terminal_url=WS_TERMINAL_URL,
        upload_url=UPLOAD_URL,
        crabber_log_unc_root=get_crabber_log_unc_root(),
        current_user=u,
        allowed_pages=getattr(request, "allowed_pages", set()),
        default_employee_id=default_emp_for_ui(u),
    )


# --- IT Kitting SQL: column whitelist for selectData (update/insert) ---
_TABLE_CONFIG_COLUMNS2_KEYS = [
    "ROWID", "SERIAL_NUMBER", "MO_NUMBER", "MODEL_NAME", "REV", "FATHER_SN", "LINE_NAME", "IN_STATION_TIME",
    "SUB_MODEL_NAME", "SUB_REV", "VENDOR_SN", "CUST_PN", "CUST_REV", "ASSY_ORD", "ASSY_FLAG", "ASSY_QTY",
    "EMP_NO", "GROUP_NAME", "CUST_NO", "PRODUCT_TYPE", "LEVEL_GRADE", "PLANT_ID", "LEVEL_NO", "PPID_MODEL",
    "SUB_PPID_MODEL", "SUB_PPID", "PPID", "SLOT", "PPID_HEADER", "FACTORY_ID", "SUB_PPID_REV", "PO_LINE",
    "PO", "REV_FLAG", "DEBUG_FLAG", "ASSY_SEQ", "DATE_CODE", "REFERENCE_TIME", "STACK",
]


def _serialize_oracle_value(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        try:
            return int(v) if v == v.to_integral_value() else float(v)
        except Exception:
            return float(v)
    if isinstance(v, datetime):
        return v.strftime("%Y/%m/%d %H:%M:%S")
    if hasattr(v, "read"):
        try:
            return str(v.read())
        except Exception:
            return str(v)
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    return v


def _serialize_oracle_row(cols, row):
    out = {}
    for i, c in enumerate(cols):
        try:
            key = c[0] if isinstance(c, tuple) else c
        except Exception:
            key = c
        out[str(key).upper()] = _serialize_oracle_value(row[i] if i < len(row) else None)
    return out


def _split_rows_by_flag(rows):
    rows_y = []
    rows_n = []
    for r in rows or []:
        flag = str((r or {}).get("ASSY_FLAG") or "").upper()
        if flag == "N":
            rows_n.append(r)
        else:
            rows_y.append(r)
    return rows_y, rows_n


def _sanitize_select_data(select_data):
    allowed = set(_TABLE_CONFIG_COLUMNS2_KEYS)
    out = {}
    for k, v in (select_data or {}).items():
        ku = str(k or "").upper()
        if ku == "ROWID":
            out["ROWID"] = v
            continue
        if ku in allowed:
            out[ku] = v
    return out


@bp.route("/api/debug/kitting-sql/assy-data", methods=["GET"])
def api_kitting_sql_assy_data():
    """Fetch assy data from Oracle for IT Kitting SQL page."""
    sn = (request.args.get("sn") or "").strip().upper()
    assy_flag = (request.args.get("assy_flag") or "Y").strip().lower()
    if assy_flag not in ("y", "n", "all"):
        assy_flag = "y"
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.sql_queries import KITTING_SQL_SEARCH
        conn = get_conn()
        try:
            cur = conn.cursor()
            try:
                bind_flag = None if assy_flag == "all" else assy_flag.upper()
                cur.execute(KITTING_SQL_SEARCH, {"sn": sn, "assy_flag": bind_flag})
                cols = [d[0] for d in (cur.description or [])]
                rows = cur.fetchall() or []
                out_rows = [_serialize_oracle_row(cols, r) for r in rows]
                return jsonify({"ok": True, "rows": out_rows})
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Oracle connection failed: {e}"}), 500


@bp.route("/api/debug/kitting-sql/update", methods=["POST"])
def api_kitting_sql_update():
    """Update one assy row by ROWID for IT Kitting SQL page."""
    data = request.get_json(silent=True) or {}
    select_data_raw = data.get("selectData")
    if not select_data_raw or not isinstance(select_data_raw, dict):
        return jsonify({"ok": False, "error": "selectData required"}), 400
    select_data = _sanitize_select_data(select_data_raw)
    rowid = (select_data.get("ROWID") or "").strip()
    if not rowid:
        return jsonify({"ok": False, "error": "ROWID required"}), 400
    # DATE/TIMESTAMP columns are returned to UI as formatted strings; sending them back as plain binds can trigger ORA-01861.
    # For this page's update actions, keep DB-generated times unchanged.
    skip_update_fields = {"IN_STATION_TIME", "REFERENCE_TIME"}
    update_items = [(k, v) for k, v in select_data.items() if k != "ROWID" and k not in skip_update_fields]
    if not update_items:
        return jsonify({"ok": False, "error": "No updatable fields"}), 400
    # Use generated bind names (:b0, :b1, ...) to avoid ORA-01745 on reserved/invalid bind identifiers.
    set_parts = []
    binds = {}
    for i, (k, v) in enumerate(update_items):
        b = f"b{i}"
        set_parts.append(f"{k} = :{b}")
        binds[b] = v
    sql = f"UPDATE SFISM4.R_ASSY_COMPONENT_T SET {', '.join(set_parts)} WHERE ROWID = :b_rowid"
    binds["b_rowid"] = rowid
    try:
        from sfis_tool.db import get_conn
        conn = get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(sql, binds)
                if cur.rowcount == 0:
                    conn.rollback()
                    return jsonify({"ok": False, "error": "Row not found. Please search again."}), 404
                conn.commit()
                return jsonify({"ok": True})
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/kitting-sql/insert", methods=["POST"])
def api_kitting_sql_insert():
    """Insert one assy row for IT Kitting SQL page."""
    data = request.get_json(silent=True) or {}
    select_data_raw = data.get("selectData")
    if not select_data_raw or not isinstance(select_data_raw, dict):
        return jsonify({"ok": False, "error": "selectData required"}), 400
    select_data = _sanitize_select_data(select_data_raw)
    insert_items = [(k, v) for k, v in select_data.items() if k != "ROWID"]
    if not insert_items:
        return jsonify({"ok": False, "error": "No insert fields"}), 400
    cols_sql = ", ".join([k for k, _ in insert_items])
    bind_names = [f"b{i}" for i in range(len(insert_items))]
    vals_sql = ", ".join([f":{b}" for b in bind_names])
    sql = f"INSERT INTO SFISM4.R_ASSY_COMPONENT_T ({cols_sql}) VALUES ({vals_sql})"
    binds = {bind_names[i]: insert_items[i][1] for i in range(len(insert_items))}
    try:
        from sfis_tool.db import get_conn
        conn = get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(sql, binds)
                conn.commit()
                return jsonify({"ok": True})
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/kitting-sql/delete", methods=["POST"])
def api_kitting_sql_delete():
    """Delete one assy row by ROWID for IT Kitting SQL page."""
    data = request.get_json(silent=True) or {}
    select_data_raw = data.get("selectData")
    if not select_data_raw or not isinstance(select_data_raw, dict):
        return jsonify({"ok": False, "error": "selectData required"}), 400
    rowid = (select_data_raw.get("ROWID") or "").strip()
    if not rowid:
        return jsonify({"ok": False, "error": "ROWID required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.sql_queries import KITTING_SQL_DELETE
        conn = get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(KITTING_SQL_DELETE, {"rowid": rowid})
                if cur.rowcount == 0:
                    conn.rollback()
                    return jsonify({"ok": False, "error": "Row not found. Please search again."}), 404
                conn.commit()
                return jsonify({"ok": True})
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# --- IT Jump (Jump Station) APIs ---
_WIP_KEYS = ["SERIAL_NUMBER", "MO_NUMBER", "MODEL_NAME", "STATION_NAME", "LINE_NAME", "GROUP_NAME", "NEXT_STATION"]


def _serialize_wip(wip):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in (wip or {}).items()}


def _route_items(route_cols, route_rows):
    route = []
    for r in route_rows or []:
        d = dict(zip(route_cols, r))
        route.append({
            "step": d.get("STEP"),
            "group_name": d.get("GROUP_NAME") or "",
            "group_next": d.get("GROUP_NEXT") or "",
        })
    return route


@bp.route("/api/debug/jump-station/wip", methods=["GET"])
def api_jump_station_wip():
    """Get WIP and route list for SN. Same current-station logic as Repair (get_station_and_next)."""
    sn = (request.args.get("sn") or "").strip().upper()
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.jump_route import get_route_list
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN."})
            wip = dict(zip(_WIP_KEYS, row))
            current_group = (wip.get("GROUP_NAME") or "")
            if current_group in ("PACKING", "SHIPPING"):
                return jsonify({"ok": False, "error": "SN is at PACKING/SHIPPING; jump not allowed."})
            route_cols, route_rows = get_route_list(conn, sn)
            route = _route_items(route_cols, route_rows)
            return jsonify({"ok": True, "wip": _serialize_wip(wip), "route": route})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/testing/overview", methods=["GET"])
def api_testing_overview():
    """Aggregate tray row (ETF cache), WIP summary, and Crabber test history for Testing page."""
    sn_raw = (request.args.get("sn") or "").strip()
    if not sn_raw:
        return jsonify({"ok": False, "error": "sn required"}), 400
    sn_upper = sn_raw.upper()
    out: dict = {"ok": True, "sn": sn_raw, "tray": {}, "wip": {}, "crabber": {}}

    try:
        from etf.routes import _maybe_start_background, etf_search_rows_cached

        _maybe_start_background()
        rows = etf_search_rows_cached(sn_raw)
        best = None
        qlow = sn_raw.lower()
        for r in rows:
            if str(r.get("sn") or "").strip().lower() == qlow:
                best = r
                break
        if best is None and rows:
            best = rows[0]
        if best:
            out["tray"] = {"connected": True, "row": best, "message": ""}
        else:
            out["tray"] = {
                "connected": False,
                "row": None,
                "message": "No tray DHCP cache row found for this SN.",
            }
    except Exception as e:
        out["tray"] = {"connected": False, "row": None, "message": f"Tray cache lookup failed: {e}"}

    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next

        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn_upper)
            if row:
                wip = dict(zip(_WIP_KEYS, row))
                out["wip"] = {"ok": True, "wip": _serialize_wip(wip)}
            else:
                out["wip"] = {"ok": False, "error": "No WIP for this SN"}
        finally:
            conn.close()
    except Exception as e:
        out["wip"] = {"ok": False, "error": str(e)}

    try:
        from crabber.client import fetch_test_history_for_sn

        out["crabber"] = fetch_test_history_for_sn(sn_raw)
    except Exception as e:
        out["crabber"] = {"ok": False, "tests": [], "error": str(e)}

    return jsonify(out)


@bp.route("/api/debug/jump-station/execute", methods=["POST"])
def api_jump_station_execute():
    """Execute jump: current_group (station before target, e.g. FLA) + target_group (e.g. FLB), or target_group only. SQL uses current."""
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip().upper()
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    current_group = (data.get("current_group") or "").strip()
    target_group = (data.get("target_group") or "").strip()
    if not target_group:
        return jsonify({"ok": False, "error": "target_group required"}), 400
    reason = (data.get("reason") or "").strip()
    repair_pass = data.get("repair_pass") is True
    if not reason and not repair_pass:
        return jsonify({"ok": False, "error": "Jump reason is required."}), 400
    emp_no = resolve_sfis_emp(request, data.get("emp_no"), last_resort="WEB")
    check_jump_station = data.get("check_jump_station") is True
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.jump_route import get_station_order_and_next, check_jump_station as do_check_jump_station
        from sfis_tool.repair_ok import get_group_info, jump_routing, get_jump_param_from_route
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN."})
            wip = dict(zip(_WIP_KEYS, row))
            v_line = wip.get("LINE_NAME") or ""
            if current_group:
                order, _, _ = get_station_order_and_next(conn, sn)
                try:
                    idx = list(order).index(current_group)
                    if idx + 1 < len(order):
                        target_group = order[idx + 1]
                except (ValueError, TypeError):
                    pass
            if check_jump_station and not do_check_jump_station(conn, target_group, sn):
                return jsonify({"ok": False, "error": "CheckJumpStation: not allowed (kitting/assy)."})
            # target_group from UI = desired destination (e.g. FLA). Convert to station-before (BAT)
            # so jump lands at FLA instead of FLB (SFIS advances one step when given destination).
            jump_param = get_jump_param_from_route(conn, sn, target_group)
            info = get_group_info(conn, v_line, jump_param)
            if not info:
                return jsonify({"ok": False, "error": "GetGroupInfo returned no target; cannot jump."})
            ok = jump_routing(
                conn, sn,
                info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"],
                emp_no, in_station_time=None
            )
            if not ok:
                return jsonify({"ok": False, "error": "UPDATE affected no rows."})
            return jsonify({"ok": True})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# --- Repair (SFIS) APIs ---
@bp.route("/api/debug/repair/options", methods=["GET"])
def api_repair_options():
    """Return reason_codes, repair_actions, duty_types for dropdowns."""
    try:
        from sfis_tool.config import REASON_CODES, REPAIR_ACTIONS, DUTY_TYPES
        return jsonify({
            "ok": True,
            "reason_codes": [{"code": r[0], "label": r[1], "desc": r[2]} for r in REASON_CODES],
            "repair_actions": list(REPAIR_ACTIONS),
            "duty_types": list(DUTY_TYPES),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/debug-reason-codes", methods=["GET"])
def api_debug_reason_codes():
    """Fetch reason codes from C_REASON_CODE_T for DO station (DEBUG filter)."""
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.sql_queries import REASON_CODE_DEBUG_LIST
        conn = get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(REASON_CODE_DEBUG_LIST)
                rows = cur.fetchall()
                return jsonify({
                    "ok": True,
                    "reason_codes": [
                        {"code": row[0], "desc": row[1] or ""}
                        for row in rows
                    ],
                })
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/wip", methods=["GET"])
def api_repair_wip():
    """Check WIP for SN: get_station_and_next, validate_next_station_r, check_has_unrepaired. Returns wip dict or error."""
    sn = (request.args.get("sn") or "").strip()
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next, validate_next_station_r
        from sfis_tool.repair_ok import check_has_unrepaired
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN"})
            wip = dict(zip(_WIP_KEYS, row))
            next_station = wip.get("NEXT_STATION")
            valid, msg = validate_next_station_r(next_station)
            if not valid:
                return jsonify({"ok": False, "error": msg})
            if not check_has_unrepaired(conn, sn):
                return jsonify({"ok": False, "error": "No un-repaired record (r_repair_t with repair_time IS NULL)"})
            return jsonify({"ok": True, "wip": wip})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/flow-state", methods=["GET"])
def api_repair_flow_state():
    """Get unified flow-state for Repair UI modes."""
    sn = (request.args.get("sn") or "").strip().upper()
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.jump_route import get_route_list
        from sfis_tool.repair_ok import check_has_unrepaired
        from sfis_tool.repair_flow import (
            build_groups_ordered,
            slice_main_segment,
            detect_repair_mode,
            build_repair_chain,
            build_r_only_targets,
            get_dido_suffix_from_node,
            is_di_do_ri_ro_wip_node,
        )
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN"})
            wip = dict(zip(_WIP_KEYS, row))
            route_cols, route_rows = get_route_list(conn, sn)
            route = _route_items(route_cols, route_rows)
            groups_ordered = build_groups_ordered(route)
            main_segment, segment_found = slice_main_segment(groups_ordered, "AOI_FIN_ASSY", "T_VI")
            has_unrepaired = bool(check_has_unrepaired(conn, sn))
            mode_info = detect_repair_mode(wip) if has_unrepaired else {"ui_mode": "main_line"}
            ui_mode = mode_info.get("ui_mode") or "main_line"
            base = mode_info.get("base")
            repair_chain_nodes = build_repair_chain(base) if ui_mode == "repair_dido" else []
            r_only_targets = build_r_only_targets(base, groups_ordered) if ui_mode == "repair_r_only" else []
            current_node = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            current_dido_station = get_dido_suffix_from_node(current_node) if ui_mode == "repair_dido" else ""
            tvi_idx = groups_ordered.index("T_VI") if "T_VI" in groups_ordered else -1
            current_idx = groups_ordered.index(current_node) if current_node in groups_ordered else -1
            if is_di_do_ri_ro_wip_node(current_node):
                all_pass = False
            else:
                all_pass = bool(tvi_idx >= 0 and current_idx >= tvi_idx)
            return jsonify({
                "ok": True,
                "wip": _serialize_wip(wip),
                "route": route,
                "groups_ordered": groups_ordered,
                "segment_main": main_segment,
                "segment_found": segment_found,
                "has_unrepaired": has_unrepaired,
                "ui_mode": ui_mode,
                "repair_chain_nodes": repair_chain_nodes,
                "r_only_targets": r_only_targets,
                "current_dido_station": current_dido_station,
                "base": base or "",
                "all_pass": all_pass,
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/di-next", methods=["POST"])
def api_repair_di_next():
    """Jump DI -> DO. Requires current station to be base_DI."""
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip().upper()
    base = (data.get("base") or "").strip()
    if not sn or not base:
        return jsonify({"ok": False, "error": "sn and base required"}), 400
    emp_no = resolve_sfis_emp(request, data.get("emp_no"))
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.repair_ok import get_group_info, jump_routing
        from sfis_tool.repair_flow import get_dido_suffix_from_node
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN."})
            wip = dict(zip(_WIP_KEYS, row))
            current_node = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            if get_dido_suffix_from_node(current_node) != "DI":
                return jsonify({"ok": False, "error": "SN must be at DI station for this action."}), 400
            target_group = f"{base} DO"
            v_line = wip.get("LINE_NAME") or ""
            info = get_group_info(conn, v_line, target_group)
            if not info:
                target_group = f"{base}_DO"
                info = get_group_info(conn, v_line, target_group)
            if not info:
                return jsonify({"ok": False, "error": "GetGroupInfo not found for target; cannot jump."})
            ok = jump_routing(
                conn, sn,
                info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"],
                emp_no, in_station_time=None
            )
            if not ok:
                return jsonify({"ok": False, "error": "UPDATE affected no rows."})
            row2 = get_station_and_next(conn, sn)
            wip2 = dict(zip(_WIP_KEYS, row2)) if row2 else None
            return jsonify({"ok": True, "wip": _serialize_wip(wip2)})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/ri-next", methods=["POST"])
def api_repair_ri_next():
    """Jump RI -> RO. Requires current station to be base_RI."""
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip().upper()
    base = (data.get("base") or "").strip()
    if not sn or not base:
        return jsonify({"ok": False, "error": "sn and base required"}), 400
    emp_no = resolve_sfis_emp(request, data.get("emp_no"))
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.repair_ok import get_group_info, jump_routing
        from sfis_tool.repair_flow import get_dido_suffix_from_node
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN."})
            wip = dict(zip(_WIP_KEYS, row))
            current_node = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            if get_dido_suffix_from_node(current_node) != "RI":
                return jsonify({"ok": False, "error": "SN must be at RI station for this action."}), 400
            target_group = f"{base} RO"
            v_line = wip.get("LINE_NAME") or ""
            info = get_group_info(conn, v_line, target_group)
            if not info:
                target_group = f"{base}_RO"
                info = get_group_info(conn, v_line, target_group)
            if not info:
                return jsonify({"ok": False, "error": "GetGroupInfo not found for target; cannot jump."})
            ok = jump_routing(
                conn, sn,
                info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"],
                emp_no, in_station_time=None
            )
            if not ok:
                return jsonify({"ok": False, "error": "UPDATE affected no rows."})
            row2 = get_station_and_next(conn, sn)
            wip2 = dict(zip(_WIP_KEYS, row2)) if row2 else None
            return jsonify({"ok": True, "wip": _serialize_wip(wip2)})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/do-pass", methods=["POST"])
def api_repair_do_pass():
    """DO station Pass (outstore pass): update repair log + jump to base station."""
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip().upper()
    base = (data.get("base") or "").strip()
    reason_code = (data.get("reason_code") or "").strip()
    remark = (data.get("remark") or "").strip()
    emp = resolve_sfis_emp(request, data.get("emp"))
    if not sn or not base or not reason_code:
        return jsonify({"ok": False, "error": "sn, base, and reason_code required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.repair_ok import (
            get_group_info,
            jump_routing,
            get_jump_param_from_route,
            execute_repair_ok,
            check_has_unrepaired,
        )
        from sfis_tool.repair_flow import get_dido_suffix_from_node
        from sfis_tool.sql_queries import REASON_CODE_DEBUG_VALIDATE
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(REASON_CODE_DEBUG_VALIDATE, {"rc": reason_code})
            row = cur.fetchone()
            cur.close()
            if not row or row[0] == 0:
                return jsonify({"ok": False, "error": "Invalid reason code for DO station."}), 400

            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN."})
            wip = dict(zip(_WIP_KEYS, row))
            current_node = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            if get_dido_suffix_from_node(current_node) != "DO":
                return jsonify({"ok": False, "error": "SN must be at DO station for this action."}), 400
            if not check_has_unrepaired(conn, sn):
                return jsonify({"ok": False, "error": "No un-repaired record."})

            repair_station = wip.get("STATION_NAME") or current_node
            n, ok_repair, err, _ = execute_repair_ok(
                conn, sn, repair_station, emp, reason_code,
                duty_station="TEST FIXTURE", remark=remark or "DO Pass",
                repair_action="RETEST", duty_type="RETEST", auto_commit=False
            )
            if not ok_repair or n == 0:
                conn.rollback()
                return jsonify({"ok": False, "error": err or "Repair update failed."})
            v_line = wip.get("LINE_NAME") or ""
            jump_param = get_jump_param_from_route(conn, sn, base)
            info = get_group_info(conn, v_line, jump_param)
            if not info:
                conn.rollback()
                return jsonify({"ok": False, "error": "GetGroupInfo not found for base; cannot jump."})
            ok = jump_routing(
                conn, sn,
                info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"],
                emp, in_station_time=None, auto_commit=False
            )
            if not ok:
                conn.rollback()
                return jsonify({"ok": False, "error": "UPDATE affected no rows."})
            conn.commit()
            row2 = get_station_and_next(conn, sn)
            wip2 = dict(zip(_WIP_KEYS, row2)) if row2 else None
            return jsonify({"ok": True, "wip": _serialize_wip(wip2)})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/do-fail", methods=["POST"])
def api_repair_do_fail():
    """DO station Fail (outstore fail): fail SN via NEW_TEST_INPUT_Z, moves to RI."""
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip().upper()
    base = (data.get("base") or "").strip()
    reason_code = (data.get("reason_code") or "").strip()
    emp = resolve_sfis_emp(request, data.get("emp"))
    if not sn or not base or not reason_code:
        return jsonify({"ok": False, "error": "sn, base, and reason_code required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.repair_ok import get_group_info
        from sfis_tool.oracle_sp import call_new_test_input_z
        from sfis_tool.repair_flow import get_dido_suffix_from_node
        from sfis_tool.sql_queries import REASON_CODE_DEBUG_VALIDATE
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(REASON_CODE_DEBUG_VALIDATE, {"rc": reason_code})
            row = cur.fetchone()
            cur.close()
            if not row or row[0] == 0:
                return jsonify({"ok": False, "error": "Invalid reason code for DO station."}), 400

            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN."})
            wip = dict(zip(_WIP_KEYS, row))
            current_node = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            if get_dido_suffix_from_node(current_node) != "DO":
                return jsonify({"ok": False, "error": "SN must be at DO station for this action."}), 400
            line = wip.get("LINE_NAME") or ""
            info = get_group_info(conn, line, current_node)
            if not info:
                return jsonify({"ok": False, "error": "Cannot resolve station for fail input."}), 400
            ok, res = call_new_test_input_z(
                conn, sn, reason_code, emp,
                info["LINE_NAME"], info["SECTION_NAME"], info["STATION_NAME"], info["GROUP_NAME"]
            )
            if not ok:
                return jsonify({"ok": False, "error": res or "NEW_TEST_INPUT_Z failed"}), 400
            row2 = get_station_and_next(conn, sn)
            wip2 = dict(zip(_WIP_KEYS, row2)) if row2 else None
            return jsonify({"ok": True, "message": "Fail input updated.", "res": res, "wip": _serialize_wip(wip2)})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/ro-next", methods=["POST"])
def api_repair_ro_next():
    """RO station Next: update repair log + jump to FLA."""
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip().upper()
    base = (data.get("base") or "").strip()
    reason_code = (data.get("reason_code") or "").strip()
    remark = (data.get("remark") or "").strip()
    emp = resolve_sfis_emp(request, data.get("emp"))
    if not sn or not base:
        return jsonify({"ok": False, "error": "sn and base required"}), 400
    if not reason_code:
        return jsonify({"ok": False, "error": "reason_code required for RO Next."}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.repair_ok import (
            get_group_info,
            jump_routing,
            get_jump_param_from_route,
            execute_repair_ok,
            check_has_unrepaired,
        )
        from sfis_tool.repair_flow import get_dido_suffix_from_node
        from sfis_tool.sql_queries import REASON_CODE_DEBUG_VALIDATE
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(REASON_CODE_DEBUG_VALIDATE, {"rc": reason_code})
            row = cur.fetchone()
            cur.close()
            if not row or row[0] == 0:
                return jsonify({"ok": False, "error": "Invalid reason code for RO Next."}), 400

            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN."})
            wip = dict(zip(_WIP_KEYS, row))
            current_node = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            if get_dido_suffix_from_node(current_node) != "RO":
                return jsonify({"ok": False, "error": "SN must be at RO station for this action."}), 400
            if not check_has_unrepaired(conn, sn):
                return jsonify({"ok": False, "error": "No un-repaired record."})

            repair_station = wip.get("STATION_NAME") or current_node
            n, ok_repair, err, _ = execute_repair_ok(
                conn, sn, repair_station, emp, reason_code,
                duty_station="TEST FIXTURE", remark=remark or "RO Next",
                repair_action="RETEST", duty_type="RETEST", auto_commit=False
            )
            if not ok_repair or n == 0:
                conn.rollback()
                return jsonify({"ok": False, "error": err or "Repair update failed."})
            v_line = wip.get("LINE_NAME") or ""
            jump_param = get_jump_param_from_route(conn, sn, "FLA")
            info = get_group_info(conn, v_line, jump_param)
            if not info:
                conn.rollback()
                return jsonify({"ok": False, "error": "GetGroupInfo not found for FLA; cannot jump."})
            ok = jump_routing(
                conn, sn,
                info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"],
                emp, in_station_time=None, auto_commit=False
            )
            if not ok:
                conn.rollback()
                return jsonify({"ok": False, "error": "UPDATE affected no rows."})
            conn.commit()
            row2 = get_station_and_next(conn, sn)
            wip2 = dict(zip(_WIP_KEYS, row2)) if row2 else None
            return jsonify({"ok": True, "wip": _serialize_wip(wip2)})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/pass-jump", methods=["POST"])
def api_repair_pass_jump():
    """Pass on current node: jump using IT Jump semantics without reason input."""
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip().upper()
    target_group = (data.get("target_group") or "").strip()
    if not sn or not target_group:
        return jsonify({"ok": False, "error": "sn and target_group required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.repair_ok import get_group_info, jump_routing, get_jump_param_from_route
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN."})
            wip = dict(zip(_WIP_KEYS, row))
            v_line = wip.get("LINE_NAME") or ""
            emp_no = resolve_sfis_emp(request, data.get("emp_no"))
            jump_param = get_jump_param_from_route(conn, sn, target_group)
            info = get_group_info(conn, v_line, jump_param)
            if not info:
                return jsonify({"ok": False, "error": "GetGroupInfo returned no target; cannot jump."})
            ok = jump_routing(
                conn, sn,
                info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"],
                emp_no, in_station_time=None
            )
            if not ok:
                return jsonify({"ok": False, "error": "UPDATE affected no rows."})
            row2 = get_station_and_next(conn, sn)
            wip2 = dict(zip(_WIP_KEYS, row2)) if row2 else None
            return jsonify({"ok": True, "wip": _serialize_wip(wip2)})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _dt_to_cali(val):
    """Convert datetime to America/Los_Angeles formatted string, or return empty."""
    if val is None:
        return ""
    try:
        import pytz
        ca_tz = pytz.timezone("America/Los_Angeles")
        if hasattr(val, "isoformat"):
            dt = val
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            return dt.astimezone(ca_tz).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return str(val) if val else ""


@bp.route("/api/debug/repair/fail-history", methods=["GET"])
def api_repair_fail_history():
    """Get fail history for SN from R_REPAIR_T + C_ERROR_CODE_T."""
    sn = (request.args.get("sn") or "").strip().upper()
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.sql_queries import REPAIR_FAIL_HISTORY
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
                    item["TEST_TIME_CALI"] = _dt_to_cali(row[col_idx["TEST_TIME"]] if "TEST_TIME" in col_idx else None)
                    item["REPAIR_TIME_CALI"] = _dt_to_cali(row[col_idx["REPAIR_TIME"]] if "REPAIR_TIME" in col_idx else None)
                    rows.append(item)
                return jsonify({"ok": True, "rows": rows})
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/validate-error-code", methods=["POST"])
def api_repair_validate_error_code():
    """Validate error code against C_ERROR_CODE_T."""
    data = request.get_json(silent=True) or {}
    ec = (data.get("error_code") or "").strip()
    if not ec:
        return jsonify({"ok": False, "error": "error_code required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.oracle_sp import validate_error_code
        conn = get_conn()
        try:
            valid = validate_error_code(conn, ec)
            return jsonify({"ok": True, "valid": valid})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/fail-input", methods=["POST"])
def api_repair_fail_input():
    """Execute fail input by calling SFIS1.NEW_TEST_INPUT_Z."""
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip().upper()
    ec = (data.get("error_code") or "").strip()
    if not sn or not ec:
        return jsonify({"ok": False, "error": "sn and error_code required"}), 400
    emp = resolve_sfis_emp(request, data.get("emp"))
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.repair_ok import get_group_info
        from sfis_tool.oracle_sp import validate_error_code, call_new_test_input_z
        conn = get_conn()
        try:
            if not validate_error_code(conn, ec):
                return jsonify({"ok": False, "error": f"EC invalid/not allowed => [{ec}]"}), 400
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN"})
            wip = dict(zip(_WIP_KEYS, row))
            line = wip.get("LINE_NAME") or ""
            ui_current = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            info = get_group_info(conn, line, ui_current)
            if not info:
                return jsonify({"ok": False, "error": "Cannot resolve line/section/station/group for fail input"}), 400
            ok, res = call_new_test_input_z(
                conn, sn, ec, emp,
                info["LINE_NAME"], info["SECTION_NAME"], info["STATION_NAME"], info["GROUP_NAME"]
            )
            if not ok:
                return jsonify({"ok": False, "error": res or "NEW_TEST_INPUT_Z failed"}), 400
            row2 = get_station_and_next(conn, sn)
            wip2 = dict(zip(_WIP_KEYS, row2)) if row2 else None
            return jsonify({"ok": True, "message": "Fail input updated.", "res": res, "wip": _serialize_wip(wip2)})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/assy-tree", methods=["GET"])
def api_repair_assy_tree():
    """Fetch assy tree for SN, return serializable list for frontend."""
    sn = (request.args.get("sn") or "").strip()
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.change_ok import fetch_assy_tree, build_numbered_tree_preserve_order, validate_tree_integrity
        conn = get_conn()
        try:
            cols, rows = fetch_assy_tree(conn, sn)
            if not rows:
                return jsonify({"ok": True, "tree": []})
            ok_tree, duplicate_vendor_sns = validate_tree_integrity(conn, sn)
            numbered_list, _ = build_numbered_tree_preserve_order(cols, rows)
            tree = []
            for t in numbered_list:
                num, node_key, row, is_father, parent_num, depth = t
                sn_key, vendor_sn, father_sn = node_key
                assy_flag = (row.get("ASSY_FLAG") or "Y")
                tree.append({
                    "num": num,
                    "sn": sn_key,
                    "vendor_sn": vendor_sn,
                    "father_sn": father_sn,
                    "sub_model_name": (row.get("SUB_MODEL_NAME") or ""),
                    "model_name": (row.get("MODEL_NAME") or ""),
                    "in_station_time": (row.get("IN_STATION_TIME") or ""),
                    "stack": (row.get("STACK") or ""),
                    "assy_flag": assy_flag,
                    "assy_seq": row.get("ASSY_SEQ"),
                    "depth": depth,
                    "is_father": is_father,
                    "parent_num": parent_num,
                })
            return jsonify({
                "ok": True,
                "tree": tree,
                "invalid_duplicates": duplicate_vendor_sns,
                "tree_valid": ok_tree,
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/debug/repair/execute", methods=["POST"])
def api_repair_execute():
    """Execute repair: optional dekit+kit, then repair_ok + jump. Validates parent-before-child for kit_list."""
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip()
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    emp = resolve_sfis_emp(request, data.get("emp"))
    reason_code = (data.get("reason_code") or "RC500").strip()
    desired_target = (data.get("desired_target") or "").strip()
    repair_action = (data.get("repair_action") or "REPLACE").strip()
    duty_station = (data.get("duty_station") or "TEST FIXTURE").strip()
    remark = (data.get("remark") or "retest").strip()
    kit_list = data.get("kit_list") or []
    dekit_keys = data.get("dekit_keys") or []
    action = (data.get("action") or "repair").strip().lower()
    force_continue = data.get("force_continue") is True
    force_dekit_other_tray = data.get("force_dekit_other_tray") is True
    request_id = (data.get("request_id") or "").strip()

    cached = _get_cached_repair_response(sn, request_id)
    if cached is not None:
        return jsonify(cached)

    sn_lock = _get_sn_lock(sn)
    if not sn_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "SN is being processed. Please wait and retry."}), 409
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next, validate_next_station_r
        from sfis_tool.repair_flow import compute_rc500_jump_next_param
        from sfis_tool.repair_ok import (
            check_has_unrepaired,
            execute_repair_ok,
            get_group_info,
            jump_routing,
            resolve_jump_target,
            get_jump_param_from_route,
        )
        from sfis_tool.change_ok import (
            check_vendor_in_other_trays,
            dekit_nodes,
            dekit_vendor_from_other_tray,
            insert_assy_row,
            validate_kit_request,
            validate_tree_integrity,
            snapshot_tree,
            build_numbered_tree_preserve_order,
            fetch_assy_tree,
        )
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN"})
            wip = dict(zip(_WIP_KEYS, row))
            next_station = wip.get("NEXT_STATION")
            station_name = wip.get("STATION_NAME")
            line_name = wip.get("LINE_NAME") or ""
            group_name = wip.get("GROUP_NAME") or ""
            if action == "repair":
                valid, msg = validate_next_station_r(next_station)
                if not valid:
                    return jsonify({"ok": False, "error": msg})
            if action == "repair" and not check_has_unrepaired(conn, sn):
                return jsonify({"ok": False, "error": "No un-repaired record"})
            tree_valid, bad_duplicates = validate_tree_integrity(conn, sn)
            if not tree_valid:
                return jsonify({
                    "ok": False,
                    "error": (
                        "Cannot proceed: duplicate vendor SN found with ASSY_FLAG=Y (non-CONFIG). "
                        f"Please fix via IT Kitting first: {', '.join(bad_duplicates)}"
                    ),
                    "invalid_duplicates": bad_duplicates,
                }), 400
            before_snapshot = snapshot_tree(conn, sn)

            repair_station = (
                (next_station if (next_station and str(next_station).startswith("R_")) else None)
                or station_name or str(next_station or "")
            )

            if action == "dekit":
                keys = []
                for item in dekit_keys:
                    if not isinstance(item, dict):
                        continue
                    v = (item.get("vendor_sn") or "").strip()
                    f = item.get("father_sn")
                    f = f.strip() if isinstance(f, str) else f
                    if v:
                        keys.append((v, f))
                cols, rows = fetch_assy_tree(conn, sn)
                numbered_list, _ = build_numbered_tree_preserve_order(cols, rows)
                depth_map = {}
                for _, nk, _, _, _, depth in numbered_list:
                    depth_map[(str(nk[1]), "" if nk[2] is None else str(nk[2]))] = depth
                keys = sorted(keys, key=lambda x: depth_map.get((str(x[0]), "" if x[1] is None else str(x[1])), 999))
                total, err = dekit_nodes(conn, sn, keys, emp, auto_commit=False)
                if err:
                    conn.rollback()
                    return jsonify({"ok": False, "error": f"De-kit failed: {err}", "step": "dekit"})
                after_snapshot = snapshot_tree(conn, sn)
                for v, f in keys:
                    key = (str(v), "" if f is None else str(f))
                    row_after = after_snapshot.get(key) or {}
                    if str(row_after.get("ASSY_FLAG") or "").upper() != "N":
                        conn.rollback()
                        return jsonify({
                            "ok": False,
                            "error": (
                                f"Rollback: post-validation failed -- node {v} expected ASSY_FLAG=N but got "
                                f"{row_after.get('ASSY_FLAG')!r}. All changes reverted."
                            ),
                            "step": "dekit",
                        }), 400
                conn.commit()
                row2 = get_station_and_next(conn, sn)
                current_station = dict(zip(_WIP_KEYS, row2)) if row2 else None
                resp = {"ok": True, "message": f"De-kit OK ({total} row(s)).", "current_station": current_station}
                _cache_repair_response(sn, request_id, resp)
                return jsonify(resp)

            if kit_list:
                ok_req, errors, depth_map_raw = validate_kit_request(conn, sn, kit_list)
                if not ok_req:
                    return jsonify({"ok": False, "error": errors[0], "errors": errors}), 400

                new_vsns = [
                    (item.get("new_vendor_sn") or "").strip()
                    for item in kit_list
                    if (item.get("new_vendor_sn") or "").strip()
                ]
                cross_conflicts = check_vendor_in_other_trays(conn, new_vsns, sn)
                if cross_conflicts and not force_dekit_other_tray:
                    return jsonify({
                        "ok": False,
                        "cross_tray_conflict": True,
                        "conflicts": cross_conflicts,
                        "error": "Vendor SN already kitted in another tray.",
                    })

                other_tray_locks = []
                if cross_conflicts and force_dekit_other_tray:
                    other_tray_sns = sorted(
                        dict.fromkeys(c["tray_sn"] for c in cross_conflicts if c.get("tray_sn"))
                    )
                    for other_sn in other_tray_sns:
                        if str(other_sn).upper() == sn.upper():
                            continue
                        other_lock = _get_sn_lock(other_sn)
                        if not other_lock.acquire(blocking=False):
                            for lk in other_tray_locks:
                                try:
                                    lk.release()
                                except Exception:
                                    pass
                            return jsonify({
                                "ok": False,
                                "error": (
                                    f"Tray {other_sn} is currently being processed. "
                                    "Please try again."
                                ),
                            })
                        other_tray_locks.append(other_lock)

                    try:
                        fresh = check_vendor_in_other_trays(conn, new_vsns, sn)
                        fresh_vsns = list(
                            dict.fromkeys(c["vendor_sn"] for c in fresh if c.get("vendor_sn"))
                        )
                        fresh_trays = list(
                            dict.fromkeys(c["tray_sn"] for c in fresh if c.get("tray_sn"))
                        )
                        for ct in fresh_trays:
                            for cv in fresh_vsns:
                                _total, derr = dekit_vendor_from_other_tray(
                                    conn, ct, cv, emp, auto_commit=False
                                )
                                if derr:
                                    conn.rollback()
                                    return jsonify({
                                        "ok": False,
                                        "error": (
                                            f"Cross-tray dekit failed: {cv} in tray {ct}: {derr}"
                                        ),
                                        "step": "cross_tray_dekit",
                                    })
                    except Exception:
                        conn.rollback()
                        raise
                    finally:
                        for lk in other_tray_locks:
                            try:
                                lk.release()
                            except Exception:
                                pass

                if not force_continue:
                    from sfis_tool.qa_lock import check_ppid_lock
                    vendor_sns = list(dict.fromkeys([(item.get("old_vendor_sn") or "").strip() for item in kit_list if (item.get("old_vendor_sn") or "").strip()]))
                    locked_sns = []
                    lock_msg = ""
                    for vsn in vendor_sns:
                        is_locked, msg = check_ppid_lock(conn, vsn)
                        if is_locked:
                            locked_sns.append(vsn)
                            if msg:
                                lock_msg = msg
                    if locked_sns:
                        return jsonify({
                            "ok": False,
                            "qa_locked": True,
                            "locked_sns": locked_sns,
                            "error": lock_msg or "Part(s) are QA locked (PPID lock). Please unlock before retry."
                        })
                node_keys = [(item.get("old_vendor_sn"), item.get("old_father_sn")) for item in kit_list if (item.get("old_vendor_sn") or "").strip()]
                node_keys = sorted(
                    [(k[0], k[1]) for k in node_keys if k[0]],
                    key=lambda x: depth_map_raw.get((sn.upper(), str(x[0]), "" if x[1] is None else str(x[1])), 999),
                )
                total, err = dekit_nodes(conn, sn, node_keys, emp, auto_commit=False, skip_missing=True)
                if err:
                    conn.rollback()
                    return jsonify({"ok": False, "error": f"De-kit failed: {err}", "step": "dekit"})
                kit_sorted = sorted(
                    list(kit_list),
                    key=lambda item: depth_map_raw.get(
                        (sn.upper(), str((item.get("old_vendor_sn") or "").strip()), "" if item.get("old_father_sn") is None else str(item.get("old_father_sn")).strip()),
                        999,
                    ),
                )
                for item in kit_sorted:
                    ov = (item.get("old_vendor_sn") or "").strip()
                    of = item.get("old_father_sn")
                    nv = (item.get("new_vendor_sn") or "").strip()
                    nf = item.get("new_father_sn")
                    if not ov or not nv:
                        continue
                    ok, err = insert_assy_row(conn, sn, ov, of, nv, nf, emp, auto_commit=False)
                    if not ok:
                        conn.rollback()
                        return jsonify({"ok": False, "error": f"Kit failed: {err}", "step": "kit", "vendor_sn": ov})
                after_kit_snapshot = snapshot_tree(conn, sn)
                for item in kit_sorted:
                    ov = (item.get("old_vendor_sn") or "").strip()
                    of = item.get("old_father_sn")
                    key = (str(ov), "" if of is None else str(of))
                    row_after = after_kit_snapshot.get(key) or {}
                    if str(row_after.get("ASSY_FLAG") or "").upper() != "N":
                        conn.rollback()
                        return jsonify({
                            "ok": False,
                            "error": (
                                f"Rollback: post-validation failed -- node {ov} expected ASSY_FLAG=N but got "
                                f"{row_after.get('ASSY_FLAG')!r}. All changes reverted."
                            ),
                            "step": "post_validate",
                        }), 400
                if action == "kitting":
                    conn.commit()
                    row2 = get_station_and_next(conn, sn)
                    current_station = dict(zip(_WIP_KEYS, row2)) if row2 else None
                    resp = {
                        "ok": True,
                        "message": f"Kitting OK ({len(kit_list)} row(s)).",
                        "current_station": current_station
                    }
                    _cache_repair_response(sn, request_id, resp)
                    return jsonify(resp)
            elif action == "kitting":
                return jsonify({"ok": False, "error": "No kitting items found. Please input New SN for selected subtree."})
            rows_ok, success, err, repair_time = execute_repair_ok(
                conn, sn, repair_station, emp, reason_code, duty_station, remark, repair_action,
                duty_type=duty_station, auto_commit=False
            )
            if not success:
                conn.rollback()
                return jsonify({"ok": False, "error": err})
            if (
                action == "repair"
                and reason_code == "RC500"
                and desired_target == "__AUTO_RC500__"
            ):
                desired_target = compute_rc500_jump_next_param(
                    conn, sn, next_station, group_name
                )
            desired_target = desired_target or resolve_jump_target(reason_code, group_name)
            target_group = get_jump_param_from_route(conn, sn, desired_target)
            info = get_group_info(conn, line_name, target_group)
            jump_warning = False
            if info:
                ok = jump_routing(
                    conn, sn,
                    info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"],
                    emp, in_station_time=repair_time, auto_commit=False
                )
                if not ok:
                    jump_warning = True
            after_snapshot = snapshot_tree(conn, sn)
            if action in ("repair", "kitting") and before_snapshot == after_snapshot and kit_list:
                conn.rollback()
                return jsonify({
                    "ok": False,
                    "error": "Rollback: post-validation failed -- no tree changes detected after kit. All changes reverted.",
                    "step": "post_validate",
                }), 400
            conn.commit()
            row2 = get_station_and_next(conn, sn)
            current_station = dict(zip(_WIP_KEYS, row2)) if row2 else None
            message = "Repair OK."
            if jump_warning:
                message = "Repair OK, but jump failed (0 rows updated). Please check station manually."
            resp = {"ok": True, "message": message, "current_station": current_station, "jump_warning": jump_warning}
            _cache_repair_response(sn, request_id, resp)
            return jsonify(resp)
        finally:
            conn.close()
    except Exception as e:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        sn_lock.release()


@bp.route("/debug/my-settings")
def debug_my_settings():
    """User self-service: change password, change username."""
    return render_template("debug_my_settings.html", current_user=getattr(request, "current_user", None), allowed_pages=getattr(request, "allowed_pages", set()))


def _setting_admin():
    """Return current user if admin, else None. Use for setting-only routes."""
    user = getattr(request, "current_user", None)
    if not user or (user.get("role") or "").lower() != "admin":
        return None
    return user


@bp.route("/debug/setting")
def debug_setting():
    """Admin-only Setting: users, registrations, IPs."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    return render_template("debug_setting.html", current_user=getattr(request, "current_user", None), allowed_pages=getattr(request, "allowed_pages", set()))


@bp.route("/api/debug/setting/users", methods=["GET"])
def api_setting_users():
    """List all users (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        cur = conn.execute(
            """SELECT id, username, full_name, department, employee_id, email, role,
                      allowed_login_start_time, allowed_login_end_time, allow_all_ip, locked_until_ts,
                      session_ttl_minutes, created_at_ts
               FROM users ORDER BY username"""
        )
        users = [dict(r) for r in cur.fetchall()]
        for u in users:
            u["allow_all_ip"] = bool(u.get("allow_all_ip"))
            u["locked"] = u.get("locked_until_ts") and int(u["locked_until_ts"]) > int(__import__("time").time())
            cur2 = conn.execute("SELECT ip FROM user_allowed_ips WHERE user_id = ?", (u["id"],))
            u["allowed_ips"] = [r["ip"] for r in cur2.fetchall()]
            u["allowed_pages"] = list(get_user_page_permissions(conn, u["id"]))
        return jsonify({"ok": True, "users": users})
    finally:
        conn.close()


@bp.route("/api/debug/setting/user/permissions", methods=["GET"])
def api_setting_user_permissions_get():
    """Get user's page permissions (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    try:
        user_id = int(user_id)
    except ValueError:
        return jsonify({"error": "invalid user_id"}), 400
    conn = connect_auth_db()
    try:
        cur = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        if cur.fetchone() is None:
            return jsonify({"error": "User not found"}), 404
        pages = list(get_user_page_permissions(conn, user_id))
        return jsonify({"ok": True, "pages": sorted(pages)})
    finally:
        conn.close()


@bp.route("/api/debug/setting/user/permissions", methods=["POST"])
def api_setting_user_permissions_post():
    """Set user's page permissions (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    pages = data.get("pages")
    if user_id is None:
        return jsonify({"error": "user_id required"}), 400
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return jsonify({"error": "invalid user_id"}), 400
    if pages is None:
        pages = []
    elif not isinstance(pages, list):
        return jsonify({"error": "pages must be a list"}), 400
    conn = connect_auth_db()
    try:
        cur = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        if cur.fetchone() is None:
            return jsonify({"error": "User not found"}), 404
        set_user_page_permissions(conn, user_id, pages)
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/user/reset-password", methods=["POST"])
def api_setting_reset_password():
    """Reset user password to 123 (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    user_id = request.get_json(silent=True) or {}
    user_id = user_id.get("user_id")
    if user_id is None:
        return jsonify({"error": "user_id required"}), 400
    from fa_debug.auth import hash_password
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        pw_hash = hash_password("123")
        conn.execute("UPDATE users SET password_hash = ?, updated_at_ts = ? WHERE id = ?", (pw_hash, int(__import__("time").time()), int(user_id)))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/user/employee-id", methods=["POST"])
def api_setting_user_employee_id():
    """Update user's employee_id (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    employee_id = (data.get("employee_id") or "").strip()
    if user_id is None:
        return jsonify({"error": "user_id required"}), 400
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid user_id"}), 400
    if not employee_id:
        return jsonify({"error": "employee_id required"}), 400
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        cur = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        if not cur.fetchone():
            return jsonify({"error": "User not found"}), 404
        conn.execute(
            "UPDATE users SET employee_id = ?, updated_at_ts = ? WHERE id = ?",
            (employee_id, int(__import__("time").time()), user_id),
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/user/add-ip", methods=["POST"])
def api_setting_add_ip():
    """Set user's single allowed IP (admin only). Replaces any existing. One IP per user unless allow_all_ip."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    user_id, ip = data.get("user_id"), (data.get("ip") or "").strip()
    if not ip:
        return jsonify({"error": "user_id and ip required"}), 400
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        conn.execute("DELETE FROM user_allowed_ips WHERE user_id = ?", (user_id,))
        conn.execute("INSERT INTO user_allowed_ips (user_id, ip) VALUES (?, ?)", (user_id, ip))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/user/allow-all-ip", methods=["POST"])
def api_setting_allow_all_ip():
    """Set allow_all_ip for user (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    allow = data.get("allow", True)
    if user_id is None:
        return jsonify({"error": "user_id required"}), 400
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        conn.execute("UPDATE users SET allow_all_ip = ?, updated_at_ts = ? WHERE id = ?", (1 if allow else 0, int(__import__("time").time()), user_id))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/user/session-ttl", methods=["POST"])
def api_setting_user_session_ttl():
    """Set per-user token expiry: { user_id, minutes: 30 } or { user_id, unlimited: true } or { user_id, use_global: true } (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    if user_id is None:
        return jsonify({"error": "user_id required"}), 400
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        if data.get("use_global"):
            conn.execute("UPDATE users SET session_ttl_minutes = NULL, updated_at_ts = ? WHERE id = ?", (int(__import__("time").time()), user_id))
        elif data.get("unlimited"):
            conn.execute("UPDATE users SET session_ttl_minutes = ?, updated_at_ts = ? WHERE id = ?", ("unlimited", int(__import__("time").time()), user_id))
        else:
            minutes = data.get("minutes")
            if minutes is not None:
                try:
                    m = int(minutes)
                    m = max(1, min(m, 10080))
                except (TypeError, ValueError):
                    conn.close()
                    return jsonify({"error": "minutes must be 1–10080"}), 400
                conn.execute("UPDATE users SET session_ttl_minutes = ?, updated_at_ts = ? WHERE id = ?", (str(m), int(__import__("time").time()), user_id))
            else:
                conn.close()
                return jsonify({"error": "Send minutes, unlimited, or use_global"}), 400
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/user/unlock", methods=["POST"])
def api_setting_unlock():
    """Unlock user (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    if user_id is None:
        return jsonify({"error": "user_id required"}), 400
    from fa_debug.auth import unlock_user
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        unlock_user(conn, user_id)
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/user/time-window", methods=["POST"])
def api_setting_time_window():
    """Set allowed login time window (admin only). start_time/end_time HH:MM; 0:00-0:00 or empty = 24/7."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    start_time = (data.get("start_time") or "").strip()
    end_time = (data.get("end_time") or "").strip()
    if user_id is None:
        return jsonify({"error": "user_id required"}), 400
    if not start_time and not end_time:
        start_time = end_time = None
    elif (start_time in ("0:00", "00:00") and end_time in ("0:00", "00:00")):
        start_time = end_time = "0:00"
    else:
        for t, name in [(start_time, "start_time"), (end_time, "end_time")]:
            if t and len(t) >= 5 and t[2] == ":":
                try:
                    __import__("datetime").datetime.strptime(t[:5], "%H:%M")
                except ValueError:
                    return jsonify({"error": name + " must be HH:MM"}), 400
    from fa_debug.auth_db import connect_auth_db
    import time as _time
    conn = connect_auth_db()
    try:
        conn.execute(
            "UPDATE users SET allowed_login_start_time = ?, allowed_login_end_time = ?, updated_at_ts = ? WHERE id = ?",
            (start_time or None, end_time or None, int(_time.time()), user_id),
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/user/delete", methods=["POST", "DELETE"])
def api_setting_delete_user():
    """Delete user (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    if user_id is None:
        return jsonify({"error": "user_id required"}), 400
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        conn.execute("DELETE FROM user_page_permissions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_allowed_ips WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM login_log WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/registrations", methods=["GET"])
def api_setting_registrations():
    """List pending registration requests (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        cur = conn.execute(
            "SELECT id, full_name, username, department, employee_id, reason, email, created_at_ts FROM registration_requests WHERE status = 'pending' ORDER BY created_at_ts DESC"
        )
        rows = [dict(r) for r in cur.fetchall()]
        return jsonify({"ok": True, "registrations": rows})
    finally:
        conn.close()


@bp.route("/api/debug/setting/registrations/approve", methods=["POST"])
def api_setting_approve_registration():
    """Approve registration: create user, set status=approved (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    req_id = data.get("request_id") or data.get("id")
    if req_id is None:
        return jsonify({"error": "request_id required"}), 400
    from fa_debug.auth import hash_password
    from fa_debug.auth_db import connect_auth_db
    import time
    conn = connect_auth_db()
    try:
        cur = conn.execute("SELECT * FROM registration_requests WHERE id = ? AND status = 'pending'", (req_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Pending request not found"}), 404
        row = dict(row)
        username = row["username"]
        cur = conn.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        if cur.fetchone():
            conn.execute("UPDATE registration_requests SET status = 'rejected', reviewed_at_ts = ?, reviewed_by = ? WHERE id = ?", (int(time.time()), _setting_admin()["id"], req_id))
            conn.commit()
            return jsonify({"error": "Username already exists"}), 400
        now = int(time.time())
        conn.execute(
            """INSERT INTO users (username, password_hash, full_name, department, employee_id, email, role, allow_all_ip, created_at_ts, updated_at_ts)
               VALUES (?, ?, ?, ?, ?, ?, 'user', 0, ?, ?)""",
            (username, row["password_hash"], row["full_name"], row["department"], row["employee_id"], row.get("email"), now, now),
        )
        conn.execute("UPDATE registration_requests SET status = 'approved', reviewed_at_ts = ?, reviewed_by = ? WHERE id = ?", (now, _setting_admin()["id"], req_id))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/registrations/reject", methods=["POST"])
def api_setting_reject_registration():
    """Reject registration (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    req_id = data.get("request_id") or data.get("id")
    if req_id is None:
        return jsonify({"error": "request_id required"}), 400
    import time
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        conn.execute("UPDATE registration_requests SET status = 'rejected', reviewed_at_ts = ?, reviewed_by = ? WHERE id = ?", (int(time.time()), _setting_admin()["id"], req_id))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/familiar-ips", methods=["GET", "POST"])
def api_setting_familiar_ips():
    """List (GET) or add (POST) familiar IPs (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            name = (data.get("name") or "").strip()
            ip = (data.get("ip") or "").strip()
            if not name or not ip:
                return jsonify({"error": "name and ip required"}), 400
            conn.execute("INSERT INTO familiar_ips (name, ip) VALUES (?, ?)", (name, ip))
            conn.commit()
            return jsonify({"ok": True})
        cur = conn.execute("SELECT id, name, ip FROM familiar_ips ORDER BY name")
        return jsonify({"ok": True, "familiar_ips": [dict(r) for r in cur.fetchall()]})
    finally:
        conn.close()


@bp.route("/api/debug/setting/familiar-ips/<int:fid>", methods=["DELETE"])
def api_setting_familiar_ips_remove(fid):
    """Remove familiar IP (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        conn.execute("DELETE FROM familiar_ips WHERE id = ?", (fid,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/debug/setting/unknown-ip-log", methods=["GET"])
def api_setting_unknown_ip_log():
    """Recent logins from IPs not in user's allowed IPs and not in familiar_ips (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    from fa_debug.auth_db import connect_auth_db
    conn = connect_auth_db()
    try:
        cur = conn.execute(
            """SELECT l.id, l.user_id, l.username, l.ip, l.success, l.created_at_ts
               FROM login_log l
               LEFT JOIN users u ON u.id = l.user_id
               LEFT JOIN user_allowed_ips a ON a.user_id = l.user_id AND a.ip = l.ip
               LEFT JOIN familiar_ips f ON f.ip = l.ip
               WHERE (COALESCE(u.allow_all_ip, 0) = 0)
                 AND a.ip IS NULL AND f.ip IS NULL
               ORDER BY l.created_at_ts DESC LIMIT 100"""
        )
        rows = [dict(r) for r in cur.fetchall()]
        return jsonify({"ok": True, "entries": rows})
    finally:
        conn.close()


@bp.route("/api/debug/setting/login-history", methods=["GET"])
def api_setting_login_history():
    """Recent logins from last 7 days; user, IP, time, success; is_different_device when IP != user's allowed IP. Paginated 10 per page (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    page = max(1, int(request.args.get("page", 1)))
    per_page = max(1, min(50, int(request.args.get("per_page", 10))))
    from fa_debug.auth_db import connect_auth_db
    import time as _time
    week_ago = int(_time.time()) - 7 * 24 * 3600
    conn = connect_auth_db()
    try:
        cur = conn.execute(
            "SELECT COUNT(*) AS c FROM login_log WHERE created_at_ts >= ?",
            (week_ago,),
        )
        total = cur.fetchone()["c"]
        offset = (page - 1) * per_page
        cur = conn.execute(
            """SELECT l.id, l.user_id, l.username, l.ip, l.success, l.created_at_ts
               FROM login_log l
               WHERE l.created_at_ts >= ?
               ORDER BY l.created_at_ts DESC LIMIT ? OFFSET ?""",
            (week_ago, per_page, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["success"] = bool(r.get("success"))
            uid = r.get("user_id")
            if not uid:
                r["is_different_device"] = True
                continue
            cur2 = conn.execute("SELECT allow_all_ip FROM users WHERE id = ?", (uid,))
            u = cur2.fetchone()
            if u and u["allow_all_ip"]:
                r["is_different_device"] = False
                continue
            cur2 = conn.execute("SELECT ip FROM user_allowed_ips WHERE user_id = ?", (uid,))
            allowed = [x["ip"] for x in cur2.fetchall()]
            r["is_different_device"] = (r.get("ip") or "") not in allowed
        return jsonify({
            "ok": True,
            "entries": rows,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page if total else 0,
        })
    finally:
        conn.close()


@bp.route("/api/debug/setting/user/create", methods=["POST"])
def api_setting_create_user():
    """Create user (admin only)."""
    if _setting_admin() is None:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()
    full_name = (data.get("full_name") or "").strip()
    department = (data.get("department") or "").strip().upper()
    employee_id = (data.get("employee_id") or "").strip()
    role = (data.get("role") or "user").strip().lower()
    email = (data.get("email") or "").strip() or None
    allow_all_ip = data.get("allow_all_ip", False)
    initial_ip = (data.get("initial_ip") or "").strip() or None
    if not all([username, password, full_name, department, employee_id]):
        return jsonify({"error": "username, password, full_name, department, employee_id required"}), 400
    if department not in ("TE", "FA", "OTHER"):
        return jsonify({"error": "department must be TE, FA, or OTHER"}), 400
    if role not in ("user", "vip", "admin"):
        role = "user"
    from fa_debug.auth import hash_password
    from fa_debug.auth_db import connect_auth_db
    import time
    conn = connect_auth_db()
    try:
        cur = conn.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        if cur.fetchone():
            return jsonify({"error": "Username already exists"}), 400
        now = int(time.time())
        pw_hash = hash_password(password)
        conn.execute(
            """INSERT INTO users (username, password_hash, full_name, department, employee_id, email, role, allow_all_ip, created_at_ts, updated_at_ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (username, pw_hash, full_name, department, employee_id, email, role, 1 if allow_all_ip else 0, now, now),
        )
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        if initial_ip and not allow_all_ip:
            conn.execute("INSERT OR IGNORE INTO user_allowed_ips (user_id, ip) VALUES (?, ?)", (new_id, initial_ip))
        pages = data.get("pages")
        if isinstance(pages, list):
            set_user_page_permissions(conn, new_id, pages)
        else:
            conn.commit()
        return jsonify({"ok": True, "user_id": new_id})
    finally:
        conn.close()


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
    return jsonify(
        {
            "ok": True,
            "summary": data["summary"],
            "rows": data["rows"],
            "sn_pass": data.get("sn_pass") or {},
        }
    )


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


@bp.route("/api/etf/online-test/wip", methods=["GET"])
def api_etf_online_test_wip():
    """Tray Online Test: WIP, next station, filtered station list, repair flag."""
    sn = (request.args.get("sn") or "").strip().upper()
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.jump_route import get_route_list, filter_test_stations_between_fillcoolant_tvi
        from sfis_tool.repair_flow import build_groups_ordered
        from sfis_tool.repair_ok import check_has_unrepaired
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN."}), 404
            wip = dict(zip(_WIP_KEYS, row))
            current_group = (wip.get("GROUP_NAME") or "").strip()
            if current_group in ("PACKING", "SHIPPING"):
                return jsonify({"ok": False, "error": "SN is at PACKING/SHIPPING."}), 400
            route_cols, route_rows = get_route_list(conn, sn)
            route = _route_items(route_cols, route_rows)
            groups_ordered = build_groups_ordered(route)
            filtered_stations = filter_test_stations_between_fillcoolant_tvi(groups_ordered)
            has_unrepaired = bool(check_has_unrepaired(conn, sn))
            next_station = (wip.get("NEXT_STATION") or "").strip()
            if has_unrepaired:
                button_label = "Retest"
            elif next_station:
                button_label = f"Test {next_station}"
            else:
                button_label = "Online Test"
            default_station = next_station if next_station in filtered_stations else (
                filtered_stations[0] if filtered_stations else ""
            )
            try:
                from crabber.client import sn_has_active_crabber_test

                _active, _ = sn_has_active_crabber_test(sn)
                crabber_busy = bool(_active)
            except Exception:
                crabber_busy = False
            return jsonify({
                "ok": True,
                "wip": _serialize_wip(wip),
                "next_station": next_station,
                "group_name": wip.get("GROUP_NAME") or "",
                "line_name": wip.get("LINE_NAME") or "",
                "filtered_stations": filtered_stations,
                "default_station": default_station,
                "is_repair": has_unrepaired,
                "button_label": button_label,
                "crabber_test_in_progress": crabber_busy,
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/etf/online-test/reason-codes", methods=["GET"])
def api_etf_online_test_reason_codes():
    """DEBUG reason codes for Online Test repair step (same as repair page DO/RO)."""
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.sql_queries import REASON_CODE_DEBUG_LIST
        conn = get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(REASON_CODE_DEBUG_LIST)
                rows = cur.fetchall()
                return jsonify({
                    "ok": True,
                    "reason_codes": [{"code": row[0], "desc": row[1] or ""} for row in rows],
                })
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/etf/online-test/pn-list", methods=["GET", "POST", "DELETE"])
def api_etf_online_test_pn_list():
    """PN base list for Crabber. GET=list, POST=add base, DELETE=remove custom base."""
    if request.method == "GET":
        return jsonify({"ok": True, "bases": _merge_pn_base_list()})

    data = request.get_json(silent=True) or {}

    if request.method == "DELETE":
        base = (data.get("base") or data.get("pn") or "").strip()
        if not base:
            return jsonify({"ok": False, "error": "base required"}), 400
        custom = _load_custom_pn_bases()
        before = len(custom)
        custom = [c for c in custom if c.upper() != base.upper()]
        if len(custom) < before:
            _save_custom_pn_bases(custom)
        return jsonify({"ok": True, "bases": _merge_pn_base_list()})

    base = (data.get("base") or data.get("pn") or "").strip()
    if not base:
        return jsonify({"ok": False, "error": "base required"}), 400
    existing = {b["base"].upper() for b in _merge_pn_base_list()}
    if base.upper() in existing:
        return jsonify({"ok": True, "bases": _merge_pn_base_list()})
    custom = _load_custom_pn_bases()
    if base.upper() not in {c.upper() for c in custom}:
        custom.append(base)
        _save_custom_pn_bases(custom)
    return jsonify({"ok": True, "bases": _merge_pn_base_list()})


@bp.route("/api/etf/online-test/repair", methods=["POST"])
def api_etf_online_test_repair():
    """Close open repair and jump back for retest (DO/RO/R_only / fallback)."""
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip().upper()
    reason_code = (data.get("reason_code") or "").strip()
    remark = (data.get("remark") or "Retest").strip()
    emp = resolve_sfis_emp(request, data.get("emp"))
    if not sn or not reason_code:
        return jsonify({"ok": False, "error": "sn and reason_code required"}), 400
    sn_lock = _get_sn_lock(sn)
    if not sn_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "SN is being processed. Please wait."}), 409
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.wip import get_station_and_next
        from sfis_tool.repair_ok import (
            check_has_unrepaired,
            execute_repair_ok,
            get_group_info,
            jump_routing,
            get_jump_param_from_route,
            resolve_jump_target,
        )
        from sfis_tool.repair_flow import detect_repair_mode, get_dido_suffix_from_node
        from sfis_tool.sql_queries import REASON_CODE_DEBUG_VALIDATE
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(REASON_CODE_DEBUG_VALIDATE, {"rc": reason_code})
            vrow = cur.fetchone()
            cur.close()
            if not vrow or vrow[0] == 0:
                return jsonify({"ok": False, "error": "Invalid DEBUG reason code."}), 400
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN."}), 400
            wip = dict(zip(_WIP_KEYS, row))
            if not check_has_unrepaired(conn, sn):
                return jsonify({"ok": False, "error": "No open repair record."}), 400
            current_node = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            mode = detect_repair_mode(wip)
            suffix = get_dido_suffix_from_node(current_node)
            ui_mode = mode.get("ui_mode") or "main_line"
            base = (mode.get("base") or "").strip()
            jump_target = None
            if ui_mode == "repair_dido":
                if suffix == "DO":
                    if not base:
                        return jsonify({"ok": False, "error": "Cannot resolve repair base."}), 400
                    jump_target = base
                elif suffix == "RO":
                    jump_target = "FLA"
                else:
                    return jsonify({
                        "ok": False,
                        "error": "Use the Repair page to advance DI/RI before Retest.",
                    }), 400
            elif ui_mode == "repair_r_only":
                jump_target = resolve_jump_target(reason_code, (wip.get("GROUP_NAME") or "").strip())
            else:
                jump_target = resolve_jump_target(reason_code, (wip.get("GROUP_NAME") or "").strip())
            repair_station = wip.get("STATION_NAME") or current_node
            n, ok_repair, err, repair_time = execute_repair_ok(
                conn, sn, repair_station, emp, reason_code,
                duty_station="TEST FIXTURE", remark=remark,
                repair_action="RETEST", duty_type="RETEST", auto_commit=False
            )
            if not ok_repair or n == 0:
                conn.rollback()
                return jsonify({"ok": False, "error": err or "Repair update failed."}), 400
            v_line = wip.get("LINE_NAME") or ""
            jump_param = get_jump_param_from_route(conn, sn, jump_target)
            info = get_group_info(conn, v_line, jump_param)
            if not info:
                conn.rollback()
                return jsonify({"ok": False, "error": "GetGroupInfo failed for jump target."}), 400
            ok = jump_routing(
                conn, sn,
                info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"],
                emp, in_station_time=repair_time, auto_commit=False,
            )
            if not ok:
                conn.rollback()
                return jsonify({"ok": False, "error": "Jump updated 0 rows."}), 400
            conn.commit()
            row2 = get_station_and_next(conn, sn)
            wip2 = dict(zip(_WIP_KEYS, row2)) if row2 else None
            return jsonify({"ok": True, "wip": _serialize_wip(wip2), "jump_target": jump_target})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        try:
            sn_lock.release()
        except Exception:
            pass


@bp.route("/api/etf/online-test/prepare", methods=["POST"])
def api_etf_online_test_prepare():
    """Crabber: PN mapping, SP units, shelf scan list -> machines + shelf_proc_data."""
    data = request.get_json(silent=True) or {}
    pn_name = (data.get("pn_name") or data.get("pn") or "").strip()
    if not pn_name:
        return jsonify({"ok": False, "error": "pn_name required"}), 400
    sn_norm = (data.get("sn") or "").strip().upper()
    sn_lk = None
    if sn_norm:
        sn_lk = _get_sn_lock(sn_norm)
        if not sn_lk.acquire(blocking=False):
            return jsonify({
                "ok": False,
                "error": "Another operation is in progress for this SN. Please wait.",
            }), 409
    try:
        if sn_norm:
            from crabber.client import sn_has_active_crabber_test

            active, _ = sn_has_active_crabber_test(sn_norm)
            if active:
                return jsonify({
                    "ok": False,
                    "error": (
                        "A test is already running on Crabber for this SN (PROC/Testing). "
                        "Finish or cancel before starting another."
                    ),
                }), 409
        from config.debug_config import CRABBER_USER_ID
        from crabber.online_test import (
            check_pn_mapping,
            check_sp_units,
            get_shelf_scan_item_list,
            parse_first_pn_mapping,
            pick_default_units,
        )
        user_id = str(CRABBER_USER_ID or "41").strip()
        is_rd = bool(data.get("is_rd"))
        raw_map = check_pn_mapping(pn_name, user_id, is_rd=is_rd)
        mfg_id, opt_pn = parse_first_pn_mapping(raw_map)
        if mfg_id is None:
            return jsonify({"ok": False, "error": "check_pn_mapping: could not resolve mfg_id", "raw": raw_map}), 400
        try:
            mfg_id = int(mfg_id)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Invalid opt_mfg_id from mapping"}), 400
        sp_units = check_sp_units(pn_name, user_id, mfg_id, is_rd=is_rd)
        units = pick_default_units(sp_units)
        try:
            units = int(data.get("units") or units)
        except (TypeError, ValueError):
            units = int(units)
        shelf = get_shelf_scan_item_list(pn_name, mfg_id, user_id, units, is_rd=is_rd)
        if not isinstance(shelf, dict):
            return jsonify({"ok": False, "error": "Unexpected shelf response", "raw": shelf}), 502
        machines = shelf.get("machines") or []
        scan_items = shelf.get("scan_items") or []
        env_items = shelf.get("env_items") or []
        shelf_proc_data = shelf.get("shelf_proc_data") or {}
        sfc_ext = (
            shelf.get("sfc_ext")
            or shelf_proc_data.get("sfc_ext")
            or ((shelf.get("mfg_project") or {}).get("sfc_ext") if isinstance(shelf.get("mfg_project"), dict) else None)
            or ((shelf.get("mfg_station") or {}).get("sfc_ext") if isinstance(shelf.get("mfg_station"), dict) else None)
            or ""
        )
        return jsonify({
            "ok": True,
            "pn_name": pn_name,
            "opt_pn_name": opt_pn,
            "mfg_id": mfg_id,
            "units": units,
            "sp_units": sp_units,
            "machines": machines,
            "scan_items": scan_items,
            "env_items": env_items,
            "shelf_proc_data": shelf_proc_data,
            "sfc_ext": sfc_ext,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        if sn_lk is not None:
            try:
                sn_lk.release()
            except Exception:
                pass


@bp.route("/api/etf/online-test/start", methods=["POST"])
def api_etf_online_test_start():
    """Crabber: check machine, close terminals, process_sfc, quota, getControllers, send_list."""
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip()
    pn_name = (data.get("pn_name") or data.get("pn") or "").strip()
    emp = resolve_sfis_emp(request, data.get("emp") or data.get("employee_id"))
    machine_id = data.get("machine_id")
    shelf_proc_data = data.get("shelf_proc_data") or {}
    scan_items = data.get("scan_items") or []
    env_items = data.get("env_items") or []
    sfc_ext = data.get("sfc_ext") or ""
    units = data.get("units")
    if not sn or not pn_name:
        return jsonify({"ok": False, "error": "sn and pn_name required"}), 400
    if machine_id is None:
        return jsonify({"ok": False, "error": "machine_id required"}), 400
    try:
        machine_id = int(machine_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "machine_id must be int"}), 400
    if not isinstance(shelf_proc_data, dict) or not shelf_proc_data.get("id"):
        return jsonify({"ok": False, "error": "shelf_proc_data with id required"}), 400
    try:
        units = int(units) if units is not None else 1
    except (TypeError, ValueError):
        units = 1
    sn_norm = sn.strip().upper()
    sn_lock = _get_sn_lock(sn_norm)
    if not sn_lock.acquire(blocking=False):
        return jsonify({
            "ok": False,
            "error": "Another operation is in progress for this SN. Please wait.",
        }), 409
    try:
        from crabber.client import sn_has_active_crabber_test

        active, _ = sn_has_active_crabber_test(sn_norm)
        if active:
            return jsonify({
                "ok": False,
                "error": (
                    "A test is already running on Crabber for this SN (PROC/Testing). "
                    "Finish or cancel before starting another."
                ),
            }), 409
        from config.debug_config import CRABBER_USER_ID
        from crabber.online_test import build_scan_code_map, run_start_test_sequence
        user_id = str(CRABBER_USER_ID or "41").strip()
        scan_map = build_scan_code_map(scan_items, env_items, sn_norm, emp)
        trial_run = bool(data.get("trial_run"))
        result = run_start_test_sequence(
            machine_id=machine_id,
            shelf_proc_data=shelf_proc_data,
            units=units,
            pn_name=pn_name,
            owner=emp,
            user_id=user_id,
            scan_code_map=scan_map,
            sfc_ext=sfc_ext,
            trial_run=trial_run,
        )
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        try:
            sn_lock.release()
        except Exception:
            pass


@bp.route("/api/debug-data", methods=["GET"])
def api_debug_data():
    """Return cached poller data. Starts poller if not running."""
    _ensure_poller()
    with _debug_cache_lock:
        data = _debug_cache
    if data is None:
        return jsonify(
            {
                "ok": True,
                "summary": {"total": 0, "pass": 0, "fail": 0},
                "rows": [],
                "sn_pass": {},
            }
        )
    return jsonify(
        {
            "ok": True,
            "summary": data["summary"],
            "rows": data["rows"],
            "sn_pass": data.get("sn_pass") or {},
        }
    )
