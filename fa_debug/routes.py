# -*- coding: utf-8 -*-
"""FA Debug Place Flask blueprint: /debug route, /api/debug-query, /api/debug-data, background poller."""

import json
import os
import threading
import time
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, redirect, render_template, request

from analytics.service import run_analytics_query
from config.app_config import ANALYTICS_CACHE_DIR, TABLE_CONFIG_API_URL, TABLE_CONFIG_COOKIE
from config.debug_config import LOOKBACK_HOURS, POLL_INTERVAL_SEC
from fa_debug.auth import get_current_user
from fa_debug.logic import prepare_debug_rows

bp = Blueprint("fa_debug", __name__, url_prefix="", template_folder="../templates")


@bp.before_request
def require_auth():
    """All fa_debug routes require valid auth token. Redirect to /login or 401."""
    user = get_current_user(request)
    if user is not None:
        request.current_user = user
        return None
    accept = request.headers.get("Accept") or ""
    if "text/html" in accept:
        return redirect("/login")
    return jsonify({"ok": False, "error": "Authentication required"}), 401

_upload_history_path = os.path.join(ANALYTICS_CACHE_DIR, "agent_upload_history.json")
_upload_history_lock = threading.Lock()

_debug_cache_lock = threading.Lock()
_debug_cache = None
_poller_started = False
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


def _fetch_debug_data(user_start, user_end):
    conn = None
    try:
        computed = run_analytics_query(user_start, user_end, aggregation="daily")
    except RuntimeError:
        return None
    prepared = prepare_debug_rows(computed["rows"])
    return {"summary": computed["summary"], "rows": prepared, "l11_sns": computed.get("l11_sns", [])}


def _run_poller():
    global _debug_cache
    while True:
        try:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(hours=LOOKBACK_HOURS)
            data = _fetch_debug_data(start_dt, end_dt)
            if data:
                with _debug_cache_lock:
                    _debug_cache = {"summary": data["summary"], "rows": data["rows"], "l11_sns": data.get("l11_sns", []), "start": start_dt.isoformat(), "end": end_dt.isoformat()}
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
    user = getattr(request, "current_user", None)
    return render_template("fa_debug.html", ws_terminal_url=WS_TERMINAL_URL, upload_url=UPLOAD_URL, current_user=user)


@bp.route("/debug/repair")
def debug_repair():
    """Repair page: SN search, WIP, tree, form, execute."""
    return render_template("debug_repair.html", current_user=getattr(request, "current_user", None))


@bp.route("/debug/jump-station")
def debug_jump_station():
    """IT Jump page: move station flow UI."""
    return render_template("debug_jump_station.html", current_user=getattr(request, "current_user", None))


@bp.route("/debug/kitting")
def debug_kitting():
    """IT Kitting page: assy tree from external table_config API."""
    return render_template("debug_kitting.html", current_user=getattr(request, "current_user", None))


# --- IT Kitting API (proxy to external table_config_search_data) ---
_TABLE_CONFIG_COLUMNS2_KEYS = [
    "ROWID", "SERIAL_NUMBER", "MO_NUMBER", "MODEL_NAME", "REV", "FATHER_SN", "LINE_NAME", "IN_STATION_TIME",
    "SUB_MODEL_NAME", "SUB_REV", "VENDOR_SN", "CUST_PN", "CUST_REV", "ASSY_ORD", "ASSY_FLAG", "ASSY_QTY",
    "EMP_NO", "GROUP_NAME", "CUST_NO", "PRODUCT_TYPE", "LEVEL_GRADE", "PLANT_ID", "LEVEL_NO", "PPID_MODEL",
    "SUB_PPID_MODEL", "SUB_PPID", "PPID", "SLOT", "PPID_HEADER", "FACTORY_ID", "SUB_PPID_REV", "PO_LINE",
    "PO", "REV_FLAG", "DEBUG_FLAG", "ASSY_SEQ", "DATE_CODE", "REFERENCE_TIME", "STACK",
]


@bp.route("/api/debug/kitting/assy-data", methods=["GET"])
def api_kitting_assy_data():
    """Proxy to external table_config_search_data API. Returns rows for assy tree."""
    import requests
    sn = (request.args.get("sn") or "").strip().upper()
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    if not TABLE_CONFIG_API_URL:
        return jsonify({"ok": False, "error": "TABLE_CONFIG_API_URL not configured"}), 500
    columns2 = {k: "" for k in _TABLE_CONFIG_COLUMNS2_KEYS}
    columns2["SERIAL_NUMBER"] = sn
    columns2["IN_STATION_TIME"] = []
    columns2["REFERENCE_TIME"] = []
    payload = {
        "columns2": columns2,
        "tableSelected": "select a.rowid,a.* from sfism4.r_assy_component_t a where a.assy_flag ='Y'",
    }
    url = f"{TABLE_CONFIG_API_URL}/api/common/table_config_search_data"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if TABLE_CONFIG_COOKIE:
        headers["Cookie"] = TABLE_CONFIG_COOKIE
    try:
        r = requests.post(url, json=payload, timeout=30, headers=headers)
        if not r.ok:
            return jsonify({"ok": False, "error": f"External API returned {r.status_code}"}), 502
        try:
            data = r.json()
        except ValueError as je:
            ct = r.headers.get("Content-Type", "")
            hint = " (API may require auth; set TABLE_CONFIG_COOKIE from browser)" if "text/html" in ct else ""
            return jsonify({"ok": False, "error": f"External API returned invalid JSON{hint}"}), 502
        if isinstance(data, list):
            return jsonify({"ok": True, "rows": data})
        return jsonify({"ok": False, "error": "Invalid response format"}), 502
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": str(e)}), 502


_TABLE_CONFIG_UPDATE_TABLE = "select a.rowid,a.* from sfism4.r_assy_component_T a where a.assy_flag ='Y'"


@bp.route("/api/debug/kitting/table-config-update", methods=["POST"])
def api_kitting_table_config_update():
    """Proxy to external table_config_update API. Accepts selectData + tableSelected, forwards with Cookie."""
    import requests
    data = request.get_json(silent=True) or {}
    select_data = data.get("selectData")
    table_selected = data.get("tableSelected") or _TABLE_CONFIG_UPDATE_TABLE
    if not select_data or not isinstance(select_data, dict):
        return jsonify({"ok": False, "error": "selectData required"}), 400
    if not TABLE_CONFIG_API_URL:
        return jsonify({"ok": False, "error": "TABLE_CONFIG_API_URL not configured"}), 500
    payload = {"selectData": select_data, "tableSelected": table_selected}
    url = f"{TABLE_CONFIG_API_URL}/api/common/table_config_update"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if TABLE_CONFIG_COOKIE:
        headers["Cookie"] = TABLE_CONFIG_COOKIE
    try:
        r = requests.post(url, json=payload, timeout=30, headers=headers)
        if not r.ok:
            return jsonify({"ok": False, "error": f"External API returned {r.status_code}"}), 502
        try:
            resp = r.json()
        except ValueError:
            text = (r.text or "").strip().lower()
            if text == '"success"' or text == "success":
                return jsonify({"ok": True})
            return jsonify({"ok": False, "error": r.text or "Invalid response"}), 502
        if resp is True or (isinstance(resp, dict) and resp.get("ok") is True):
            return jsonify({"ok": True})
        if isinstance(resp, str) and resp.lower() == "success":
            return jsonify({"ok": True})
        return jsonify({"ok": True, "raw": resp})
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": str(e)}), 502


def _table_config_forward(endpoint):
    """Proxy to external table_config API. Same logic as table_config_update."""
    import requests
    data = request.get_json(silent=True) or {}
    select_data = data.get("selectData")
    table_selected = data.get("tableSelected") or _TABLE_CONFIG_UPDATE_TABLE
    if not select_data or not isinstance(select_data, dict):
        return jsonify({"ok": False, "error": "selectData required"}), 400
    if not TABLE_CONFIG_API_URL:
        return jsonify({"ok": False, "error": "TABLE_CONFIG_API_URL not configured"}), 500
    payload = {"selectData": select_data, "tableSelected": table_selected}
    url = f"{TABLE_CONFIG_API_URL}/api/common/{endpoint}"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if TABLE_CONFIG_COOKIE:
        headers["Cookie"] = TABLE_CONFIG_COOKIE
    try:
        r = requests.post(url, json=payload, timeout=30, headers=headers)
        if not r.ok:
            return jsonify({"ok": False, "error": f"External API returned {r.status_code}"}), 502
        try:
            resp = r.json()
        except ValueError:
            text = (r.text or "").strip().lower()
            if text == '"success"' or text == "success":
                return jsonify({"ok": True})
            return jsonify({"ok": False, "error": r.text or "Invalid response"}), 502
        if resp is True or (isinstance(resp, dict) and resp.get("ok") is True):
            return jsonify({"ok": True})
        if isinstance(resp, str) and resp.lower() == "success":
            return jsonify({"ok": True})
        return jsonify({"ok": True, "raw": resp})
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@bp.route("/api/debug/kitting/table-config-insert", methods=["POST"])
def api_kitting_table_config_insert():
    """Proxy to external table_config_insert API."""
    return _table_config_forward("table_config_insert")


@bp.route("/api/debug/kitting/table-config-delete", methods=["POST"])
def api_kitting_table_config_delete():
    """Proxy to external table_config_delete API."""
    return _table_config_forward("table_config_delete")


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
    emp_no = (data.get("emp_no") or "").strip() or (getattr(request, "current_user", None) or {}).get("username") or "WEB"
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
            tvi_idx = groups_ordered.index("T_VI") if "T_VI" in groups_ordered else -1
            current_idx = groups_ordered.index(current_node) if current_node in groups_ordered else -1
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
                "all_pass": all_pass,
            })
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
            emp_no = (data.get("emp_no") or "").strip() or "SJOP"
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
                rows = []
                for row in cur.fetchall():
                    item = {}
                    for idx, col in enumerate(cols):
                        val = row[idx]
                        item[col] = val.isoformat() if hasattr(val, "isoformat") else val
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
    emp = (data.get("emp") or "").strip() or "SJOP"
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
    emp = (data.get("emp") or "").strip() or (getattr(request, "current_user", None) or {}).get("username") or ""
    if not emp:
        return jsonify({"ok": False, "error": "emp required"}), 400
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
                total, err = dekit_nodes(conn, sn, node_keys, emp, auto_commit=False)
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
    return render_template("debug_my_settings.html", current_user=getattr(request, "current_user", None))


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
    return render_template("debug_setting.html", current_user=getattr(request, "current_user", None))


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
        return jsonify({"ok": True, "users": users})
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
