# -*- coding: utf-8 -*-
"""FA Debug Place Flask blueprint: /debug route, /api/debug-query, /api/debug-data, background poller."""

import json
import os
import threading
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, redirect, render_template, request

from analytics.service import run_analytics_query
from config.app_config import ANALYTICS_CACHE_DIR
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
    try:
        computed = run_analytics_query(user_start, user_end, aggregation="daily")
    except RuntimeError:
        return None
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
    user = getattr(request, "current_user", None)
    return render_template("fa_debug.html", ws_terminal_url=WS_TERMINAL_URL, upload_url=UPLOAD_URL, current_user=user)


@bp.route("/debug/repair")
def debug_repair():
    """Repair page: SN search, WIP, tree, form, execute."""
    return render_template("debug_repair.html", current_user=getattr(request, "current_user", None))


# --- Repair (SFIS) APIs ---
_WIP_KEYS = ["SERIAL_NUMBER", "MO_NUMBER", "MODEL_NAME", "STATION_NAME", "LINE_NAME", "GROUP_NAME", "NEXT_STATION"]


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


@bp.route("/api/debug/repair/assy-tree", methods=["GET"])
def api_repair_assy_tree():
    """Fetch assy tree for SN (Y + N combined), return serializable list for frontend."""
    sn = (request.args.get("sn") or "").strip()
    if not sn:
        return jsonify({"ok": False, "error": "sn required"}), 400
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.change_ok import fetch_assy_tree, build_numbered_tree
        conn = get_conn()
        try:
            cols_y, rows_y = fetch_assy_tree(conn, sn, "Y")
            cols_n, rows_n = fetch_assy_tree(conn, sn, "N")
            combined = list(rows_y) + list(rows_n)
            if not combined:
                return jsonify({"ok": True, "tree": []})
            numbered_list, _ = build_numbered_tree(cols_y, combined)
            parent_num_by_key = {}
            tree = []
            for t in numbered_list:
                num, node_key, row, is_father, parent_node_key, depth = t
                vendor_sn = node_key[0]
                father_sn = node_key[1]
                assy_flag = (row.get("ASSY_FLAG") or "Y")
                group_name = (row.get("GROUP_NAME") or "")
                cust_pn = (row.get("CUST_PN") or row.get("SUB_MODEL_NAME") or "")
                cust_rev = (row.get("CUST_REV") or row.get("SUB_REV") or "N/A")
                parent_num = parent_num_by_key.get(parent_node_key) if parent_node_key else None
                tree.append({
                    "num": num,
                    "vendor_sn": vendor_sn,
                    "father_sn": father_sn,
                    "group_name": group_name,
                    "assy_flag": assy_flag,
                    "cust_pn": cust_pn,
                    "cust_rev": cust_rev,
                    "depth": depth,
                    "is_father": is_father,
                    "parent_num": parent_num,
                })
                parent_num_by_key[node_key] = num
            return jsonify({"ok": True, "tree": tree})
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
    repair_action = (data.get("repair_action") or "REPLACE").strip()
    duty_station = (data.get("duty_station") or "TEST FIXTURE").strip()
    remark = (data.get("remark") or "retest").strip()
    kit_list = data.get("kit_list") or []

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
        from sfis_tool.change_ok import dekit_nodes, insert_assy_row
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
            valid, msg = validate_next_station_r(next_station)
            if not valid:
                return jsonify({"ok": False, "error": msg})
            if not check_has_unrepaired(conn, sn):
                return jsonify({"ok": False, "error": "No un-repaired record"})

            repair_station = (
                (next_station if (next_station and str(next_station).startswith("R_")) else None)
                or station_name or str(next_station or "")
            )

            if kit_list:
                old_to_new = {}
                for item in kit_list:
                    ov = (item.get("old_vendor_sn") or "").strip()
                    nv = (item.get("new_vendor_sn") or "").strip()
                    if not ov or not nv:
                        return jsonify({"ok": False, "error": "Each kit item must have old_vendor_sn and new_vendor_sn"})
                    old_to_new[ov] = nv
                for item in kit_list:
                    of = item.get("old_father_sn")
                    of_str = (of if of is not None else "").strip() if isinstance(of, str) else (str(of).strip() if of is not None else "")
                    if of_str and of_str in old_to_new:
                        parent_new = old_to_new[of_str]
                        nf = (item.get("new_father_sn") or "").strip()
                        if nf != parent_new:
                            return jsonify({"ok": False, "error": f"Parent must be kitted before child: parent SN {of_str} -> new {parent_new}, child has new_father_sn {nf!r}"})
                node_keys = [(item.get("old_vendor_sn"), item.get("old_father_sn")) for item in kit_list if (item.get("old_vendor_sn") or "").strip()]
                total, err = dekit_nodes(conn, sn, [(k[0], k[1]) for k in node_keys if k[0]], emp)
                if err:
                    return jsonify({"ok": False, "error": f"De-kit failed: {err}", "step": "dekit"})
                for item in kit_list:
                    ov = (item.get("old_vendor_sn") or "").strip()
                    of = item.get("old_father_sn")
                    nv = (item.get("new_vendor_sn") or "").strip()
                    nf = item.get("new_father_sn")
                    if not ov or not nv:
                        continue
                    ok, err = insert_assy_row(conn, sn, ov, of, nv, nf, emp)
                    if not ok:
                        return jsonify({"ok": False, "error": f"Kit failed: {err}", "step": "kit", "vendor_sn": ov})
            rows_ok, success, err, repair_time = execute_repair_ok(
                conn, sn, repair_station, emp, reason_code, duty_station, remark, repair_action
            )
            if not success:
                return jsonify({"ok": False, "error": err})
            desired_target = resolve_jump_target(reason_code, group_name)
            target_group = get_jump_param_from_route(conn, sn, desired_target)
            info = get_group_info(conn, line_name, target_group)
            if info:
                ok = jump_routing(
                    conn, sn,
                    info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"],
                    emp, in_station_time=repair_time
                )
                if not ok:
                    pass
            row2 = get_station_and_next(conn, sn)
            current_station = dict(zip(_WIP_KEYS, row2)) if row2 else None
            return jsonify({"ok": True, "message": "Repair OK.", "current_station": current_station})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
                      allowed_login_start_time, allowed_login_end_time, allow_all_ip, locked_until_ts, created_at_ts
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
    username = (data.get("username") or "").strip()
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
