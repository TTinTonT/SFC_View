# -*- coding: utf-8 -*-
"""
Same logic as POST /api/debug/repair/execute in fa_debug/routes.py.

Pass a dict with keys: sn, emp, reason_code, desired_target, repair_action, duty_station,
remark, kit_list, dekit_keys, action, force_continue, force_dekit_other_tray, request_id.
"""
from repair_module.core.db import get_conn
from repair_module.core.wip import get_station_and_next, validate_next_station_r
from repair_module.core.flow_state import compute_rc500_jump_next_param
from repair_module.core.repair_actions import (
    check_has_unrepaired,
    execute_repair_ok,
    get_group_info,
    jump_routing,
    resolve_jump_target,
    get_jump_param_from_route,
)
from repair_module.core.kitting import (
    check_vendor_in_other_trays,
    dekit_nodes,
    dekit_vendor_from_other_tray,
    dekit_specs_from_request_items,
    insert_assy_row,
    validate_kit_request,
    validate_tree_integrity,
    snapshot_tree,
    build_numbered_tree_preserve_order,
    fetch_assy_tree,
    sort_dekit_specs_by_tree_depth,
    verify_dekit_targets,
)
from repair_module.core.qa_lock import check_ppid_lock
from repair_module.core.sn_locks import (
    get_sn_lock,
    cache_repair_response,
    get_cached_repair_response,
)
from repair_module.core.wip_serialize import WIP_KEYS, serialize_wip


def execute_repair(data: dict):
    """
    Execute repair / dekit / kitting. Returns plain dict (same keys as Flask jsonify body).
    On concurrent SN lock failure, returns ok False and error message (same as HTTP 409 body).
    """
    data = data or {}
    sn = (data.get("sn") or "").strip()
    if not sn:
        return {"ok": False, "error": "sn required"}

    emp = (data.get("emp") or "").strip()
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

    cached = get_cached_repair_response(sn, request_id)
    if cached is not None:
        return cached

    sn_lock = get_sn_lock(sn)
    if not sn_lock.acquire(blocking=False):
        return {"ok": False, "error": "SN is being processed. Please wait and retry."}

    conn = None
    try:
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return {"ok": False, "error": "No WIP for this SN"}
            wip = dict(zip(WIP_KEYS, row))
            next_station = wip.get("NEXT_STATION")
            station_name = wip.get("STATION_NAME")
            line_name = wip.get("LINE_NAME") or ""
            group_name = wip.get("GROUP_NAME") or ""
            if action == "repair":
                valid, msg = validate_next_station_r(next_station)
                if not valid:
                    return {"ok": False, "error": msg}
            if action == "repair" and not check_has_unrepaired(conn, sn):
                return {"ok": False, "error": "No un-repaired record"}
            tree_valid, bad_duplicates = validate_tree_integrity(conn, sn)
            duplicate_vendor_warning = None
            if not tree_valid:
                duplicate_vendor_warning = (
                    "Duplicate vendor SN (ASSY_FLAG=Y, non-CONFIG): "
                    + ", ".join(bad_duplicates)
                    + ". IT Kitting cleanup recommended; kitting/repair will proceed."
                )

            def _attach_dup_warn(out: dict) -> None:
                if duplicate_vendor_warning:
                    out["duplicate_vendor_warning"] = duplicate_vendor_warning
                    out["invalid_duplicates"] = bad_duplicates

            before_snapshot = snapshot_tree(conn, sn)

            repair_station = (
                (next_station if (next_station and str(next_station).startswith("R_")) else None)
                or station_name
                or str(next_station or "")
            )

            if action == "dekit":
                specs = dekit_specs_from_request_items(dekit_keys)
                if not specs:
                    return {
                        "ok": False,
                        "error": "No valid dekit_keys (need vendor_sn per row).",
                        "step": "dekit",
                    }
                cols, rows = fetch_assy_tree(conn, sn)
                numbered_list, _ = build_numbered_tree_preserve_order(cols, rows)
                specs = sort_dekit_specs_by_tree_depth(numbered_list, specs)
                total, err = dekit_nodes(conn, sn, specs, emp, auto_commit=False)
                if err:
                    conn.rollback()
                    return {"ok": False, "error": f"De-kit failed: {err}", "step": "dekit"}
                vcur = conn.cursor()
                try:
                    ok_v, bad_spec, reason = verify_dekit_targets(vcur, sn, specs)
                finally:
                    vcur.close()
                if not ok_v:
                    conn.rollback()
                    bv = (bad_spec or {}).get("vendor_sn", "?")
                    return {
                        "ok": False,
                        "error": (
                            f"Rollback: post-validation failed -- node {bv} ({reason}). "
                            "All changes reverted."
                        ),
                        "step": "dekit",
                    }
                conn.commit()
                row2 = get_station_and_next(conn, sn)
                current_station = serialize_wip(dict(zip(WIP_KEYS, row2))) if row2 else None
                resp = {"ok": True, "message": f"De-kit OK ({total} row(s)).", "current_station": current_station}
                _attach_dup_warn(resp)
                cache_repair_response(sn, request_id, resp)
                return resp

            if kit_list:
                ok_req, errors, depth_map_raw = validate_kit_request(conn, sn, kit_list)
                if not ok_req:
                    return {"ok": False, "error": errors[0], "errors": errors}

                new_vsns = [
                    (item.get("new_vendor_sn") or "").strip()
                    for item in kit_list
                    if (item.get("new_vendor_sn") or "").strip()
                ]
                cross_conflicts = check_vendor_in_other_trays(conn, new_vsns, sn)
                if cross_conflicts and not force_dekit_other_tray:
                    return {
                        "ok": False,
                        "cross_tray_conflict": True,
                        "conflicts": cross_conflicts,
                        "error": "Vendor SN already kitted in another tray.",
                    }

                other_tray_locks = []
                if cross_conflicts and force_dekit_other_tray:
                    other_tray_sns = sorted(
                        dict.fromkeys(c["tray_sn"] for c in cross_conflicts if c.get("tray_sn"))
                    )
                    for other_sn in other_tray_sns:
                        if str(other_sn).upper() == sn.upper():
                            continue
                        other_lock = get_sn_lock(other_sn)
                        if not other_lock.acquire(blocking=False):
                            for lk in other_tray_locks:
                                try:
                                    lk.release()
                                except Exception:
                                    pass
                            return {
                                "ok": False,
                                "error": (
                                    f"Tray {other_sn} is currently being processed. "
                                    "Please try again."
                                ),
                            }
                        other_tray_locks.append(other_lock)

                    try:
                        fresh = check_vendor_in_other_trays(conn, new_vsns, sn)
                        fresh_vsns = list(dict.fromkeys(c["vendor_sn"] for c in fresh if c.get("vendor_sn")))
                        fresh_trays = list(dict.fromkeys(c["tray_sn"] for c in fresh if c.get("tray_sn")))
                        for ct in fresh_trays:
                            for cv in fresh_vsns:
                                _total, derr = dekit_vendor_from_other_tray(
                                    conn, ct, cv, emp, auto_commit=False
                                )
                                if derr:
                                    conn.rollback()
                                    return {
                                        "ok": False,
                                        "error": (
                                            f"Cross-tray dekit failed: {cv} in tray {ct}: {derr}"
                                        ),
                                        "step": "cross_tray_dekit",
                                    }
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
                    vendor_sns = list(
                        dict.fromkeys(
                            [
                                (item.get("old_vendor_sn") or "").strip()
                                for item in kit_list
                                if (item.get("old_vendor_sn") or "").strip()
                            ]
                        )
                    )
                    locked_sns = []
                    lock_msg = ""
                    for vsn in vendor_sns:
                        is_locked, msg = check_ppid_lock(conn, vsn)
                        if is_locked:
                            locked_sns.append(vsn)
                            if msg:
                                lock_msg = msg
                    if locked_sns:
                        return {
                            "ok": False,
                            "qa_locked": True,
                            "locked_sns": locked_sns,
                            "error": lock_msg
                            or "Part(s) are QA locked (PPID lock). Please unlock before retry.",
                        }
                # Bulk kitting is always two-phase: de-kit EVERY distinct (old_vendor, old_father),
                # then INSERT new rows in stable tree order — never kit before all de-kits ran.
                node_keys = [
                    (item.get("old_vendor_sn"), item.get("old_father_sn"))
                    for item in kit_list
                    if (item.get("old_vendor_sn") or "").strip()
                ]
                node_keys = sorted(
                    [(k[0], k[1]) for k in node_keys if k[0]],
                    key=lambda x: (
                        depth_map_raw.get(
                            (sn.upper(), str(x[0]), "" if x[1] is None else str(x[1])),
                            999,
                        ),
                        str(x[0]),
                    ),
                )
                nk_seen = set()
                node_keys_dedup = []
                for nk in node_keys:
                    kk = (str(nk[0]), "" if nk[1] is None else str(nk[1]))
                    if kk in nk_seen:
                        continue
                    nk_seen.add(kk)
                    node_keys_dedup.append(nk)
                total, err = dekit_nodes(conn, sn, node_keys_dedup, emp, auto_commit=False, skip_missing=True)
                if err:
                    conn.rollback()
                    return {"ok": False, "error": f"De-kit failed: {err}", "step": "dekit"}
                after_dekit_snap = snapshot_tree(conn, sn)
                for nk in node_keys_dedup:
                    v, f = nk[0], nk[1]
                    key_s = (str(v), "" if f is None else str(f))
                    row_d = after_dekit_snap.get(key_s) or {}
                    if str(row_d.get("ASSY_FLAG") or "").upper() != "N":
                        conn.rollback()
                        bad_flag = row_d.get("ASSY_FLAG")
                        bad_disp = repr(bad_flag) if bad_flag is not None else "MISSING ROW"
                        return {
                            "ok": False,
                            "step": "dekit_verify",
                            "error": (
                                "Bulk de-kit incomplete (no kit inserts run yet): node "
                                f"{v} under father {key_s[1]!r} expected ASSY_FLAG=N but got {bad_disp}. "
                                "Verify FATHER_SN matches Oracle or fix data in IT Kitting."
                            ),
                        }
                kit_sorted = sorted(
                    list(kit_list),
                    key=lambda item: (
                        depth_map_raw.get(
                            (
                                sn.upper(),
                                str((item.get("old_vendor_sn") or "").strip()),
                                ""
                                if item.get("old_father_sn") is None
                                else str(item.get("old_father_sn")).strip(),
                            ),
                            999,
                        ),
                        str((item.get("old_vendor_sn") or "").strip()),
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
                        return {"ok": False, "error": f"Kit failed: {err}", "step": "kit", "vendor_sn": ov}
                # Post-insert snapshot by (vendor,father) is unsafe after intra-tray swaps (same as fa_debug/routes).
                if action == "kitting":
                    conn.commit()
                    row2 = get_station_and_next(conn, sn)
                    current_station = serialize_wip(dict(zip(WIP_KEYS, row2))) if row2 else None
                    resp = {
                        "ok": True,
                        "message": f"Kitting OK ({len(kit_list)} row(s)).",
                        "current_station": current_station,
                    }
                    _attach_dup_warn(resp)
                    cache_repair_response(sn, request_id, resp)
                    return resp
            elif action == "kitting":
                return {
                    "ok": False,
                    "error": "No kitting items found. Please input New SN for selected subtree.",
                }

            rows_ok, success, err, repair_time = execute_repair_ok(
                conn,
                sn,
                repair_station,
                emp,
                reason_code,
                duty_station,
                remark,
                repair_action,
                duty_type=duty_station,
                auto_commit=False,
            )
            if not success:
                conn.rollback()
                return {"ok": False, "error": err}
            if (
                action == "repair"
                and reason_code == "RC500"
                and desired_target == "__AUTO_RC500__"
            ):
                desired_target = compute_rc500_jump_next_param(conn, sn, next_station, group_name)
            desired_target = desired_target or resolve_jump_target(reason_code, group_name)
            target_group = get_jump_param_from_route(conn, sn, desired_target)
            info = get_group_info(conn, line_name, target_group)
            jump_warning = False
            if info:
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
                    jump_warning = True
            after_snapshot = snapshot_tree(conn, sn)
            if action in ("repair", "kitting") and before_snapshot == after_snapshot and kit_list:
                conn.rollback()
                return {
                    "ok": False,
                    "error": "Rollback: post-validation failed -- no tree changes detected after kit. All changes reverted.",
                    "step": "post_validate",
                }
            conn.commit()
            row2 = get_station_and_next(conn, sn)
            current_station = serialize_wip(dict(zip(WIP_KEYS, row2))) if row2 else None
            message = "Repair OK."
            if jump_warning:
                message = "Repair OK, but jump failed (0 rows updated). Please check station manually."
            resp = {
                "ok": True,
                "message": message,
                "current_station": current_station,
                "jump_warning": jump_warning,
            }
            _attach_dup_warn(resp)
            cache_repair_response(sn, request_id, resp)
            return resp
        finally:
            if conn is not None:
                conn.close()
    except Exception as e:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}
    finally:
        try:
            sn_lock.release()
        except Exception:
            pass
