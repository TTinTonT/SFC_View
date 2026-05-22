# -*- coding: utf-8 -*-
"""
Flask routes for ETF Online Test + L10 online-queue (ported from fa_debug/routes.py).

URLs match SFC_View so the copied static/js can call the same paths after you
register this blueprint on the host app.
"""

from __future__ import annotations

from typing import Any, Tuple

import requests
from flask import Blueprint, jsonify, request

from online_test.crabber_ctx import crabber_profile_scope
from online_test.deps import resolve_sfis_emp
from online_test import pn_bases
from online_test import queue as l10q
from online_test.sn_locks import get_sn_lock
from online_test.wip_utils import WIP_KEYS, norm_l10_queue_site, route_items, serialize_wip


def _sn_has_active_crabber_test(sn: str) -> Tuple[bool, Any]:
    try:
        from crabber.client import sn_has_active_crabber_test

        return sn_has_active_crabber_test(sn)
    except Exception:
        return False, None


def _etf_online_test_wip_impl(sn: str):
    try:
        from sfis_tool.db import get_conn
        from sfis_tool.jump_route import filter_test_stations_between_fillcoolant_tvi, get_route_list
        from sfis_tool.repair_flow import build_groups_ordered
        from sfis_tool.repair_ok import check_has_unrepaired
        from sfis_tool.wip import get_station_and_next

        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return jsonify({"ok": False, "error": "No WIP for this SN."}), 404
            wip = dict(zip(WIP_KEYS, row))
            current_group = (wip.get("GROUP_NAME") or "").strip()
            if current_group in ("PACKING", "SHIPPING"):
                return jsonify({"ok": False, "error": "SN is at PACKING/SHIPPING."}), 400
            route_cols, route_rows = get_route_list(conn, sn)
            route = route_items(route_cols, route_rows)
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
            default_station = (
                next_station
                if next_station in filtered_stations
                else (filtered_stations[0] if filtered_stations else "")
            )
            try:
                _active, _ = _sn_has_active_crabber_test(sn)
                crabber_busy = bool(_active)
            except Exception:
                crabber_busy = False
            return jsonify(
                {
                    "ok": True,
                    "wip": serialize_wip(wip),
                    "next_station": next_station,
                    "group_name": wip.get("GROUP_NAME") or "",
                    "line_name": wip.get("LINE_NAME") or "",
                    "filtered_stations": filtered_stations,
                    "default_station": default_station,
                    "is_repair": has_unrepaired,
                    "button_label": button_label,
                    "crabber_test_in_progress": crabber_busy,
                }
            )
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def build_blueprint() -> Blueprint:
    bp = Blueprint("online_test_portable", __name__)

    @bp.route("/api/etf/online-test/wip", methods=["GET"])
    def api_etf_online_test_wip():
        sn = (request.args.get("sn") or "").strip().upper()
        if not sn:
            return jsonify({"ok": False, "error": "sn required"}), 400
        with crabber_profile_scope() as crabber_ok:
            if not crabber_ok:
                return jsonify({"ok": False, "error": "invalid crabber_profile"}), 400
            return _etf_online_test_wip_impl(sn)

    @bp.route("/api/etf/online-test/reason-codes", methods=["GET"])
    def api_etf_online_test_reason_codes():
        with crabber_profile_scope() as crabber_ok:
            if not crabber_ok:
                return jsonify({"ok": False, "error": "invalid crabber_profile"}), 400
            try:
                from sfis_tool.db import get_conn
                from sfis_tool.sql_queries import REASON_CODE_DEBUG_LIST

                conn = get_conn()
                try:
                    cur = conn.cursor()
                    try:
                        cur.execute(REASON_CODE_DEBUG_LIST)
                        rows = cur.fetchall()
                        return jsonify(
                            {
                                "ok": True,
                                "reason_codes": [{"code": row[0], "desc": row[1] or ""} for row in rows],
                            }
                        )
                    finally:
                        cur.close()
                finally:
                    conn.close()
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

    @bp.route("/api/etf/online-test/pn-list", methods=["GET", "POST", "DELETE"])
    def api_etf_online_test_pn_list():
        with crabber_profile_scope() as crabber_ok:
            if not crabber_ok:
                return jsonify({"ok": False, "error": "invalid crabber_profile"}), 400
            if request.method == "GET":
                return jsonify({"ok": True, "bases": pn_bases.merge_pn_base_list()})

            data = request.get_json(silent=True) or {}

            if request.method == "DELETE":
                base = (data.get("base") or data.get("pn") or "").strip()
                if not base:
                    return jsonify({"ok": False, "error": "base required"}), 400
                custom = pn_bases.load_custom_pn_bases()
                before = len(custom)
                custom = [c for c in custom if c.upper() != base.upper()]
                if len(custom) < before:
                    pn_bases.save_custom_pn_bases(custom)
                return jsonify({"ok": True, "bases": pn_bases.merge_pn_base_list()})

            base = (data.get("base") or data.get("pn") or "").strip()
            if not base:
                return jsonify({"ok": False, "error": "base required"}), 400
            existing = {b["base"].upper() for b in pn_bases.merge_pn_base_list()}
            if base.upper() in existing:
                return jsonify({"ok": True, "bases": pn_bases.merge_pn_base_list()})
            custom = pn_bases.load_custom_pn_bases()
            if base.upper() not in {c.upper() for c in custom}:
                custom.append(base)
                pn_bases.save_custom_pn_bases(custom)
            return jsonify({"ok": True, "bases": pn_bases.merge_pn_base_list()})

    @bp.route("/api/etf/online-test/repair", methods=["POST"])
    def api_etf_online_test_repair():
        data = request.get_json(silent=True) or {}
        sn = (data.get("sn") or "").strip().upper()
        reason_code = (data.get("reason_code") or "").strip()
        remark = (data.get("remark") or "Retest").strip()
        emp = resolve_sfis_emp(request, data.get("emp"))
        if not sn or not reason_code:
            return jsonify({"ok": False, "error": "sn and reason_code required"}), 400
        with crabber_profile_scope() as crabber_ok:
            if not crabber_ok:
                return jsonify({"ok": False, "error": "invalid crabber_profile"}), 400
            sn_lock = get_sn_lock(sn)
            if not sn_lock.acquire(blocking=False):
                return jsonify({"ok": False, "error": "SN is being processed. Please wait."}), 409
            try:
                from sfis_tool.db import get_conn
                from sfis_tool.repair_flow import detect_repair_mode, get_dido_suffix_from_node
                from sfis_tool.repair_ok import (
                    check_has_unrepaired,
                    execute_repair_ok,
                    get_group_info,
                    get_jump_param_from_route,
                    jump_routing,
                    resolve_jump_target,
                )
                from sfis_tool.sql_queries import REASON_CODE_DEBUG_VALIDATE
                from sfis_tool.wip import get_station_and_next

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
                    wip = dict(zip(WIP_KEYS, row))
                    if not check_has_unrepaired(conn, sn):
                        return jsonify({"ok": False, "error": "No open repair record."}), 400
                    current_node = (wip.get("NEXT_STATION") or "").strip() or (
                        wip.get("GROUP_NAME") or ""
                    ).strip()
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
                            return jsonify(
                                {
                                    "ok": False,
                                    "error": "Use the Repair page to advance DI/RI before Retest.",
                                }
                            ), 400
                    elif ui_mode == "repair_r_only":
                        jump_target = resolve_jump_target(reason_code, (wip.get("GROUP_NAME") or "").strip())
                    else:
                        jump_target = resolve_jump_target(reason_code, (wip.get("GROUP_NAME") or "").strip())
                    repair_station = wip.get("STATION_NAME") or current_node
                    n, ok_repair, err, repair_time = execute_repair_ok(
                        conn,
                        sn,
                        repair_station,
                        emp,
                        reason_code,
                        duty_station="TEST FIXTURE",
                        remark=remark,
                        repair_action="RETEST",
                        duty_type="RETEST",
                        auto_commit=False,
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
                        conn,
                        sn,
                        info["LINE_NAME"],
                        info["SECTION_NAME"],
                        info["GROUP_NAME"],
                        info["STATION_NAME"],
                        emp,
                        in_station_time=repair_time,
                        auto_commit=False,
                    )
                    if not ok:
                        conn.rollback()
                        return jsonify({"ok": False, "error": "Jump updated 0 rows."}), 400
                    conn.commit()
                    row2 = get_station_and_next(conn, sn)
                    wip2 = dict(zip(WIP_KEYS, row2)) if row2 else None
                    return jsonify(
                        {"ok": True, "wip": serialize_wip(wip2), "jump_target": jump_target}
                    )
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
        data = request.get_json(silent=True) or {}
        pn_name = (data.get("pn_name") or data.get("pn") or "").strip()
        if not pn_name:
            return jsonify({"ok": False, "error": "pn_name required"}), 400
        sn_norm = (data.get("sn") or "").strip().upper()
        with crabber_profile_scope() as crabber_ok:
            if not crabber_ok:
                return jsonify({"ok": False, "error": "invalid crabber_profile"}), 400
            sn_lk = None
            if sn_norm:
                sn_lk = get_sn_lock(sn_norm)
                if not sn_lk.acquire(blocking=False):
                    return jsonify(
                        {
                            "ok": False,
                            "error": "Another operation is in progress for this SN. Please wait.",
                        }
                    ), 409
            try:
                if sn_norm:
                    active, _ = _sn_has_active_crabber_test(sn_norm)
                    if active:
                        return jsonify(
                            {
                                "ok": False,
                                "error": (
                                    "A test is already running on Crabber for this SN (PROC/Testing). "
                                    "Finish or cancel before starting another."
                                ),
                            }
                        ), 409
                from crabber.online_test import (
                    check_pn_mapping,
                    check_sp_units,
                    get_shelf_scan_item_list,
                    parse_first_pn_mapping,
                    pick_default_units,
                )
                from crabber.profile import get_crabber_tuple

                _, _, crab_uid, _ = get_crabber_tuple()
                user_id = str(crab_uid or "41").strip()
                is_rd = bool(data.get("is_rd"))
                raw_map = check_pn_mapping(pn_name, user_id, is_rd=is_rd)
                mfg_id, opt_pn = parse_first_pn_mapping(raw_map)
                if mfg_id is None:
                    return jsonify(
                        {"ok": False, "error": "check_pn_mapping: could not resolve mfg_id", "raw": raw_map}
                    ), 400
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
                    or (
                        (shelf.get("mfg_project") or {}).get("sfc_ext")
                        if isinstance(shelf.get("mfg_project"), dict)
                        else None
                    )
                    or (
                        (shelf.get("mfg_station") or {}).get("sfc_ext")
                        if isinstance(shelf.get("mfg_station"), dict)
                        else None
                    )
                    or ""
                )
                return jsonify(
                    {
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
                    }
                )
            except requests.exceptions.HTTPError as e:
                resp = getattr(e, "response", None)
                code = getattr(resp, "status_code", None) if resp is not None else None
                if code == 401:
                    return jsonify(
                        {
                            "ok": False,
                            "error": (
                                "Crabber API returned 401 Unauthorized. For Sunnyvale (crabber_profile=sv) set "
                                "CRABBER_SV_TOKEN to the same Token the SV Crabber UI uses (Authorization header), and "
                                "optionally CRABBER_SV_USER_ID to match cookie user_id (e.g. 12). "
                                "CRABBER_TOKEN / CRABBER_USER_ID alone are usually San José only."
                            ),
                        }
                    ), 502
                return jsonify({"ok": False, "error": str(e)}), 502
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
        with crabber_profile_scope() as crabber_ok:
            if not crabber_ok:
                return jsonify({"ok": False, "error": "invalid crabber_profile"}), 400
            sn_lock = get_sn_lock(sn_norm)
            if not sn_lock.acquire(blocking=False):
                return jsonify(
                    {
                        "ok": False,
                        "error": "Another operation is in progress for this SN. Please wait.",
                    }
                ), 409
            try:
                active, _ = _sn_has_active_crabber_test(sn_norm)
                if active:
                    return jsonify(
                        {
                            "ok": False,
                            "error": (
                                "A test is already running on Crabber for this SN (PROC/Testing). "
                                "Finish or cancel before starting another."
                            ),
                        }
                    ), 409
                from crabber.online_test import build_scan_code_map, run_start_test_sequence
                from crabber.profile import get_crabber_tuple

                _, _, crab_uid, _ = get_crabber_tuple()
                user_id = str(crab_uid or "41").strip()
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
            except requests.exceptions.HTTPError as e:
                resp = getattr(e, "response", None)
                code = getattr(resp, "status_code", None) if resp is not None else None
                if code == 401:
                    return jsonify(
                        {
                            "ok": False,
                            "error": (
                                "Crabber API returned 401 Unauthorized. For Sunnyvale set CRABBER_SV_TOKEN (SV UI token) "
                                "and optionally CRABBER_SV_USER_ID to match the SV Crabber user id."
                            ),
                        }
                    ), 502
                return jsonify({"ok": False, "error": str(e)}), 502
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500
            finally:
                try:
                    sn_lock.release()
                except Exception:
                    pass

    @bp.route("/api/debug/l10-test/online-queue", methods=["GET"])
    def api_debug_l10_test_online_queue_get():
        both = l10q.snapshot_queues_by_site()
        return jsonify({"ok": True, "sj": both["sj"], "sv": both["sv"]})

    @bp.route("/api/debug/l10-test/online-queue/enqueue", methods=["POST"])
    def api_debug_l10_test_online_queue_enqueue():
        data = request.get_json(silent=True) or {}
        fixture_no = data.get("fixture_no") or data.get("fixture") or ""
        slot_no = data.get("slot_no") or data.get("slot") or ""
        sn = data.get("sn") or ""
        site = norm_l10_queue_site(data.get("site"))
        out = l10q.enqueue(str(fixture_no), str(slot_no), str(sn), site=site)
        status = 200 if out.get("ok") else 400
        return jsonify(out), status

    @bp.route("/api/debug/l10-test/online-queue/complete", methods=["POST"])
    def api_debug_l10_test_online_queue_complete():
        data = request.get_json(silent=True) or {}
        fixture_no = data.get("fixture_no") or ""
        job_id = data.get("job_id") or ""
        delay_min = data.get("delay_min", 0)
        delay_sec = data.get("delay_sec", 0)
        site = norm_l10_queue_site(data.get("site"))
        out = l10q.complete(str(fixture_no), str(job_id), delay_min, delay_sec, site=site)
        status = 200 if out.get("ok") else 400
        return jsonify(out), status

    @bp.route("/api/debug/l10-test/online-queue/abandon", methods=["POST"])
    def api_debug_l10_test_online_queue_abandon():
        data = request.get_json(silent=True) or {}
        fixture_no = data.get("fixture_no") or ""
        job_id = data.get("job_id") or ""
        site = norm_l10_queue_site(data.get("site"))
        out = l10q.abandon(str(fixture_no), str(job_id), site=site)
        status = 200 if out.get("ok") else 400
        return jsonify(out), status

    @bp.route("/api/debug/l10-test/online-queue/force-next", methods=["POST"])
    def api_debug_l10_test_online_queue_force_next():
        data = request.get_json(silent=True) or {}
        fixture_no = data.get("fixture_no") or ""
        job_id = data.get("job_id") or None
        site = norm_l10_queue_site(data.get("site"))
        out = l10q.force_next(str(fixture_no), str(job_id) if job_id else None, site=site)
        status = 200 if out.get("ok") else 400
        return jsonify(out), status

    return bp
