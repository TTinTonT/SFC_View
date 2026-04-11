# -*- coding: utf-8 -*-
"""Crabber API helpers for Tray Status Online Test (PN mapping, shelf, start test sequence)."""

from __future__ import annotations

import json
from typing import Any, Optional

import requests
from requests import HTTPError


def _cfg():
    try:
        from config.debug_config import CRABBER_BASE_URL, CRABBER_TOKEN, CRABBER_USER_ID, CRABBER_SITENAME
        return (
            (CRABBER_BASE_URL or "").strip().rstrip("/"),
            (CRABBER_TOKEN or "").strip(),
            str(CRABBER_USER_ID or "41").strip(),
            (CRABBER_SITENAME or "SanJose").strip(),
        )
    except Exception:
        return "", "", "41", "SanJose"


def _headers_get(token: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Token {token}" if token else "",
    }


def _headers_post(token: str) -> dict:
    h = _headers_get(token)
    h["Content-Type"] = "application/json"
    return h


def _get(path: str, params: Optional[dict] = None, timeout: int = 120) -> Any:
    base, token, _, _ = _cfg()
    if not base:
        raise RuntimeError("CRABBER_BASE_URL is not configured")
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    r = requests.get(url, headers=_headers_get(token), params=params or {}, timeout=timeout)
    r.raise_for_status()
    if not r.text.strip():
        return None
    try:
        return r.json()
    except Exception:
        return r.text


def _post(path: str, json_body: Optional[dict] = None, timeout: int = 120) -> Any:
    base, token, _, _ = _cfg()
    if not base:
        raise RuntimeError("CRABBER_BASE_URL is not configured")
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    r = requests.post(url, headers=_headers_post(token), json=json_body or {}, timeout=timeout)
    r.raise_for_status()
    if not r.text.strip():
        return None
    try:
        return r.json()
    except Exception:
        return r.text


def check_pn_mapping(pn_name: str, user_id: str, is_rd: bool = False) -> Any:
    return _get(
        "/api/check_pn_mapping/",
        {"pn_name": pn_name, "user_id": user_id, "is_rd": "true" if is_rd else "false"},
    )


def check_sp_units(pn_name: str, user_id: str, mfg_id: int, is_rd: bool = False) -> Any:
    return _get(
        "/api/check_sp_units/",
        {
            "pn_name": pn_name,
            "user_id": user_id,
            "mfg_id": mfg_id,
            "is_rd": "true" if is_rd else "false",
        },
    )


def get_shelf_scan_item_list(
    pn_name: str, mfg_id: int, user_id: str, units: int, is_rd: bool = False
) -> Any:
    return _get(
        "/api/get_shelf_scan_item_list/",
        {
            "pn_name": pn_name,
            "mfg_id": mfg_id,
            "user_id": user_id,
            "is_rd": "true" if is_rd else "false",
            "units": units,
        },
    )


def get_station_list(*, is_mfg: bool = True, timeout: int = 60) -> Any:
    """Crabber MFG station dropdown (same as shelf UI)."""
    return _get("/api/getStationList/", {"is_mfg": "true" if is_mfg else "false"}, timeout=timeout)


def get_shelf_procedure_released(
    *,
    project_id: int,
    station_id: str | None,
    page: int = 1,
    page_size: int = 240,
    timeout: int = 120,
) -> Any:
    """
    Crabber released shelf procedures for MFG shelf grid.
    station_id: use None or '' to pass literal 'null' (all stations), matching Crabber query.
    """
    params: dict[str, Any] = {
        "project_id": project_id,
        "page": max(1, int(page)),
        "page_size": max(1, min(500, int(page_size))),
    }
    if station_id is None or str(station_id).strip() == "":
        params["station_id"] = "null"
    else:
        params["station_id"] = str(station_id).strip()
    return _get("/api/get_shelf_procedure_released/", params, timeout=timeout)


def get_rd_shelf_scan_item_list(
    *,
    sp_id: int,
    user_id: str,
    trial_run: bool = True,
    source: str = "",
    timeout: int = 120,
) -> Any:
    """
    Crabber operator-console shelf payload for a specific released shelf procedure (sp_id).
    Matches browser: /api/get_rd_shelf_scan_item_list/?sp_id=&user_id=&trial_run=&source=
    """
    params = {
        "sp_id": int(sp_id),
        "user_id": str(user_id),
        "trial_run": "true" if trial_run else "false",
        "source": source or "",
    }
    try:
        return _get("/api/get_rd_shelf_scan_item_list/", params, timeout=timeout)
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return _get("/api/get_rel_shelf_scan_item_list/", params, timeout=timeout)
        raise


def get_machine_config(machine_id: int, spid: int) -> Any:
    return _get(
        "/api/get_machine_config/",
        {"machine_id": machine_id, "spid": spid},
    )


def check_machine_status(machine_id: int) -> Any:
    return _get("/api/check_machine_status/", {"machine_id": machine_id})


def close_terminals(machine_id: int) -> Any:
    return _get("/api/close_terminals/", {"machine_id": machine_id})


def process_sfc(payload: dict) -> Any:
    return _post("/api/process_sfc/", json_body=payload)


def check_set_shelf_procedure_accessibility(shelf_proc_id: int) -> Any:
    return _get(
        "/api/check_set_shelf_procedure_accessibility/",
        {"shelf_proc_id": shelf_proc_id},
    )


def check_is_over_thread_quota(
    machine_id: int, units: int, shelf_proc_id: int, sitename: str
) -> Any:
    return _get(
        "/api/check_is_over_thread_quota/",
        {
            "machine_id": machine_id,
            "units": units,
            "shelf_proc_id": shelf_proc_id,
            "sitename": sitename,
        },
    )


def get_controllers(payload: dict) -> Any:
    return _post("/api/getControllers/", json_body=payload)


def send_list(payload: dict) -> Any:
    return _post("/api/send_list/", json_body=payload)


def parse_first_pn_mapping(resp: Any) -> tuple[Optional[int], Optional[str]]:
    """Return (opt_mfg_id, opt_pn_name) from check_pn_mapping list response."""
    if not resp or not isinstance(resp, list) or len(resp) == 0:
        return None, None
    raw = resp[0].get("value") if isinstance(resp[0], dict) else None
    if not raw:
        return None, None
    if isinstance(raw, dict):
        return raw.get("opt_mfg_id"), raw.get("opt_pn_name")
    try:
        d = json.loads(raw) if isinstance(raw, str) else {}
        mid = d.get("opt_mfg_id")
        if mid is not None:
            try:
                mid = int(mid)
            except (TypeError, ValueError):
                try:
                    mid = int(float(mid))
                except (TypeError, ValueError):
                    mid = None
        return mid, d.get("opt_pn_name")
    except Exception:
        return None, None


def pick_default_units(sp_units_resp: Any) -> int:
    if not sp_units_resp or not isinstance(sp_units_resp, dict):
        return 1
    mx = sp_units_resp.get("max_unit")
    mn = sp_units_resp.get("min_unit")
    try:
        if mx is not None:
            return int(mx)
    except (TypeError, ValueError):
        pass
    try:
        if mn is not None:
            return int(mn)
    except (TypeError, ValueError):
        pass
    return 1


def _crabber_scan_cell_str(v: Any) -> str:
    """Ensure scan cell values are strings; non-string types cause Crabber server 500."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def build_scan_code_map(
    scan_items: list,
    env_items: list,
    tray_sn: str,
    op_id: str,
) -> dict:
    """Build scan_code_map dict for process_sfc / send_list (keys = scan_item names)."""
    out: dict = {}

    def one_item(it: dict) -> dict:
        scan_item = (it.get("scan_item") or "").strip()
        if not scan_item:
            return {}
        row: dict = {
            "value": _crabber_scan_cell_str(it.get("value")),
            "description": _crabber_scan_cell_str(it.get("description")),
            "type_sn": _crabber_scan_cell_str(it.get("type_sn")),
            "shown_in_log": int(it.get("shown_in_log") or 0),
        }
        if "@" in scan_item or it.get("parent") is not None:
            parent = it.get("parent")
            position = it.get("position")
            row["parent"] = _crabber_scan_cell_str(parent) if parent is not None else scan_item.split("@")[0]
            row["position"] = _crabber_scan_cell_str(position) if position is not None else ""
        return {scan_item: row}

    for it in scan_items or []:
        if isinstance(it, dict):
            out.update(one_item(it))
    for it in env_items or []:
        if isinstance(it, dict):
            out.update(one_item(it))

    base_sn = (tray_sn or "").strip()
    base_op = (op_id or "").strip()

    if "SCAN_SYSTEM_SN" in out:
        out["SCAN_SYSTEM_SN"]["value"] = base_sn
    else:
        out["SCAN_SYSTEM_SN"] = {
            "value": base_sn,
            "description": "Compute Tray - Info - Scan L10 System Serial Number",
            "type_sn": "SN_NODE_1_1",
            "shown_in_log": 1,
            "parent": "SCAN_SYSTEM_SN",
            "position": "1_",
        }
    if "OP_ID" in out:
        out["OP_ID"]["value"] = base_op
    else:
        out["OP_ID"] = {
            "value": base_op,
            "description": "Station - Info - Scan Operator ID",
            "type_sn": "",
            "shown_in_log": 1,
            "parent": "OP_ID",
            "position": "1_",
        }
    return out


def run_start_test_sequence(
    *,
    machine_id: int,
    shelf_proc_data: dict,
    units: int,
    pn_name: str,
    owner: str,
    user_id: str,
    scan_code_map: dict,
    sfc_ext: Any = None,
    trial_run: bool = False,
) -> dict:
    """
    Run Crabber start chain after user picked machine.
    Returns dict with step results or raises on HTTP/required field errors.
    """
    spd = shelf_proc_data or {}
    list_id = int(spd.get("id") or 0)
    if not list_id:
        raise ValueError("shelf_proc_data.id is required")
    shelf_proc_id = list_id
    tp_raw = spd.get("test_procedure_id")
    tp_id = int(tp_raw) if tp_raw is not None else list_id

    _, _, _, sitename = _cfg()
    steps: list = []

    st = check_machine_status(machine_id)
    steps.append({"step": "check_machine_status", "ok": True, "data": st})

    ct = close_terminals(machine_id)
    steps.append({"step": "close_terminals", "ok": True, "data": ct})

    try:
        mc = get_machine_config(machine_id, shelf_proc_id)
        steps.append({"step": "get_machine_config", "ok": True, "data": mc})
    except Exception as e:
        steps.append({"step": "get_machine_config", "ok": False, "error": str(e)})

    scan_json = json.dumps(scan_code_map, ensure_ascii=False)
    sfc_ext_raw = sfc_ext if sfc_ext else "{}"
    if isinstance(sfc_ext_raw, dict):
        sfc_ext_raw = json.dumps(sfc_ext_raw, ensure_ascii=False)

    proc_payload: dict = {
        "list_id": list_id,
        "scan_code_map": scan_json,
        "sfc_ext": sfc_ext_raw,
        "machine_id": machine_id,
        "exe_units": units,
        "unit_enabled_list": [1] * max(1, int(units)),
    }

    psfc = process_sfc(proc_payload)
    steps.append({"step": "process_sfc", "ok": True, "data": psfc})

    acc = check_set_shelf_procedure_accessibility(shelf_proc_id)
    steps.append({"step": "check_set_shelf_procedure_accessibility", "ok": True, "data": acc})

    quota = check_is_over_thread_quota(machine_id, units, shelf_proc_id, sitename)
    steps.append({"step": "check_is_over_thread_quota", "ok": True, "data": quota})

    ctrl_payload = {
        "id_mac": machine_id,
        "number_of_units": units,
        "unit_enabled_list": [True] * max(1, int(units)),
        "data_type": "archive",
        "shelf_proc_id": shelf_proc_id,
    }
    controllers = get_controllers(ctrl_payload)
    steps.append({"step": "getControllers", "ok": True, "data": controllers})

    controllers_for_send = controllers
    if isinstance(controllers, dict):
        for key in ("controllers", "data", "result"):
            if key in controllers and controllers[key] is not None:
                controllers_for_send = controllers[key]
                break
    if isinstance(controllers_for_send, dict) and "mcs" in controllers_for_send:
        controllers_for_send = controllers_for_send["mcs"]

    ctrl_json = json.dumps(controllers_for_send, ensure_ascii=False) if not isinstance(controllers_for_send, str) else controllers_for_send

    sfc_event_map = {}
    if isinstance(psfc, dict) and psfc.get("sfc_event_map"):
        sfc_event_map = psfc["sfc_event_map"]

    send_payload = {
        "machine_id": machine_id,
        "list_id": list_id,
        "controllers": ctrl_json,
        "scan_code_map": scan_json,
        "owner": owner or str(user_id),
        "log_type": 0,
        "pn_name": pn_name,
        "sfc_ext": sfc_ext_raw,
        "user_id": str(user_id),
        "data_type": "archive",
        "tp_id": tp_id,
        "sfc_event_map": sfc_event_map,
        "trial_run": trial_run,
    }
    send_res = send_list(send_payload)
    steps.append({"step": "send_list", "ok": True, "data": send_res})

    log_id = None
    if isinstance(psfc, dict):
        log_id = psfc.get("log_id")
    return {"ok": True, "steps": steps, "log_id": log_id, "send_list": send_res}
