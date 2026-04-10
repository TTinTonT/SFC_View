# -*- coding: utf-8 -*-
"""
Crabber API client: search by SN -> node_log_id -> get_node_info -> Log Report File Path.

Flow:
  1. GET /api/search_log_items/?sn=XXX -> get latest node_log_id
  2. GET /api/get_node_info/?node_log_id=XXX -> extract Log Report File Path from Log-Info section
"""
from typing import Any, List, Optional, Tuple
from urllib.parse import quote

import requests

from crabber.log_unc_path import build_crabber_log_folder_unc, extract_node_log_id


def _get_config():
    try:
        from config.debug_config import CRABBER_BASE_URL, CRABBER_TOKEN
        return ((CRABBER_BASE_URL or "").strip(), (CRABBER_TOKEN or "").strip())
    except Exception:
        return ("", "")


def _headers(token: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Token {token}" if token else "",
    }


def build_search_log_items_url(
    base: str,
    sn: str = "",
    cur_page: int = 1,
    is_trial: bool = False,
) -> str:
    """Crabber search_log_items query; sn may be empty for global recent logs."""
    trial = "true" if is_trial else "false"
    sn_q = quote((sn or "").strip(), safe="")
    root = (base or "").strip().rstrip("/")
    return (
        f"{root}/api/search_log_items/"
        f"?cur_page={int(cur_page)}&project=&station=&phase=&precondition=&label_data=&result=All"
        f"&spid=&machine=&pn=&from_date=&to_date=&sfc=&cal_total=false&is_trial={trial}"
        f"&sn={sn_q}"
    )


def fetch_search_log_items_json(
    sn: str = "",
    cur_page: int = 1,
    is_trial: bool = False,
    timeout: int = 20,
) -> Tuple[Optional[dict], Optional[str]]:
    """
    GET search_log_items; returns (response_dict, error_str).
    On failure response_dict is None.
    """
    base, token = _get_config()
    if not base:
        return None, "CRABBER_BASE_URL empty"
    url = build_search_log_items_url(base, sn=sn, cur_page=cur_page, is_trial=is_trial)
    try:
        r = requests.get(url, headers=_headers(token), timeout=timeout)
        if not r.ok:
            return None, f"HTTP {r.status_code}"
        data = r.json()
        if not isinstance(data, dict):
            return None, "response is not a JSON object"
        return data, None
    except Exception as e:
        return None, str(e)


def fetch_search_log_items_all_pages(
    sn: str = "",
    is_trial: bool = False,
    timeout: int = 20,
) -> Tuple[Optional[List[dict]], Optional[dict], Optional[str]]:
    """
    Fetch all pages from search_log_items.
    Returns (merged_log_list_sorted_desc, first_page_response, error_str).
    """
    page = 1
    total_pages = None
    merged: List[dict] = []
    first_resp: Optional[dict] = None
    while True:
        data, err = fetch_search_log_items_json(
            sn=sn,
            cur_page=page,
            is_trial=is_trial,
            timeout=timeout,
        )
        if err:
            return None, first_resp, err
        if not isinstance(data, dict):
            return None, first_resp, "response is not a JSON object"
        if first_resp is None:
            first_resp = data
        if total_pages is None:
            try:
                total_pages = int(data.get("total_pages") or 0)
            except (TypeError, ValueError):
                return None, first_resp, "total_pages is invalid"
            if total_pages < 1:
                return None, first_resp, "total_pages missing or < 1"
        items = _extract_items_list(data) or []
        for it in items:
            if isinstance(it, dict):
                merged.append(it)
        if page >= total_pages:
            break
        page += 1
    merged.sort(key=lambda x: str(x.get("log_time") or ""), reverse=True)
    return merged, first_resp, None


def tier_from_crabber_station(station: str) -> Optional[str]:
    """L10 if SYSTEM in station, L11 if FVT (FVT checked first). Else None."""
    s = (station or "").strip()
    if "FVT" in s:
        return "L11"
    if "SYSTEM" in s:
        return "L10"
    return None


def reconcile_l10_proc_items_for_sns(
    sns: List[str],
    is_trial: bool,
    *,
    timeout: int = 10,
    limit: int = 50,
) -> List[dict]:
    """
    For each SN, if latest rows still contain L10 PROC, return one dict per SN (fetch_test_history shape).
    """
    out: List[dict] = []
    want_seen: set = set()
    for sn in sns:
        s = (sn or "").strip()
        if not s:
            continue
        ku = s.upper()
        if ku in want_seen:
            continue
        want_seen.add(ku)
        res = fetch_test_history_for_sn(s, timeout=timeout, limit=limit, is_trial=is_trial)
        if not res.get("ok"):
            continue
        for t in res.get("tests") or []:
            if not isinstance(t, dict):
                continue
            if str(t.get("node_log_event") or "").strip().upper() != "PROC":
                continue
            st = str(t.get("station") or "").strip()
            if tier_from_crabber_station(st) != "L10":
                continue
            row_sn = str(t.get("sn") or "").strip().upper()
            if row_sn and row_sn != ku:
                continue
            out.append(t)
            break
    return out


def extract_l10_proc_first_per_sn(items: Any) -> List[dict]:
    """
    From search_log_items log_list (newest first): first PROC row per SN, L10 only.
    """
    if not isinstance(items, list):
        return []
    seen: set = set()
    out: List[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("node_log_event") or it.get("nodeLogEvent") or "").strip().upper() != "PROC":
            continue
        st = str(it.get("station") or it.get("Station") or "").strip()
        if tier_from_crabber_station(st) != "L10":
            continue
        sn = str(it.get("sn") or it.get("SN") or "").strip()
        if not sn:
            continue
        ku = sn.upper()
        if ku in seen:
            continue
        seen.add(ku)
        out.append(it)
    return out


def _extract_items_list(obj: Any) -> Optional[list]:
    """Extract list of items from search_log_items response. Try many key names."""
    if obj is None:
        return None
    if isinstance(obj, list) and len(obj) > 0:
        return obj
    if isinstance(obj, dict):
        for key in (
            "log_list",  # Crabber search_log_items response
            "items", "results", "data", "logs", "log_items", "nodes",
            "search_results", "rows", "records", "entries", "list",
        ):
            val = obj.get(key)
            if isinstance(val, list) and len(val) > 0:
                return val
        # Nested: data.items, data.results, etc.
        data = obj.get("data") or obj.get("response")
        if isinstance(data, dict):
            for key in ("items", "results", "logs", "data"):
                val = data.get(key)
                if isinstance(val, list) and len(val) > 0:
                    return val
        if isinstance(data, list) and len(data) > 0:
            return data
        # Last resort: any value that is a non-empty list of dicts
        for val in obj.values():
            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                return val
    return None


def get_sn_tier_from_crabber(sn: str, timeout: int = 15) -> Optional[str]:
    """
    GET /api/search_log_items/?sn=XXX; classify SN as L10/L11 from station.
    - total_logs < 1 or no log_list -> None (invalid).
    - total_logs == 1 -> check station of log_list[0]: FVT -> L11, SYSTEM -> L10.
    - total_logs > 1 -> check station of log_list[1]: FVT -> L11, SYSTEM -> L10.
    Returns "L10" | "L11" | None.
    """
    base, token = _get_config()
    if not base or not (sn or "").strip():
        return None
    sn = sn.strip()
    search_url = build_search_log_items_url(base, sn=sn, cur_page=1, is_trial=False)
    try:
        r = requests.get(search_url, headers=_headers(token), timeout=timeout)
        if not r.ok:
            return None
        search_resp = r.json()
    except Exception:
        return None
    log_list = _extract_items_list(search_resp)
    if not log_list or not isinstance(log_list, list):
        return None
    total_logs = search_resp.get("total_logs") if isinstance(search_resp, dict) else None
    if total_logs is None:
        total_logs = len(log_list)
    if total_logs < 1:
        return None
    idx = 1 if total_logs > 1 else 0
    if idx >= len(log_list):
        return None
    log = log_list[idx] if isinstance(log_list[idx], dict) else {}
    station = (log.get("station") or "").strip()
    if "FVT" in station:
        return "L11"
    if "SYSTEM" in station:
        return "L10"
    return None


def _looks_like_file_path(s: str) -> bool:
    """Must be actual path, not project name like NVIDIA_NVL144."""
    s = (s or "").strip()
    if not s or len(s) < 4:
        return False
    # Real path: contains / or starts with /mnt, C:\, \\server, etc.
    return "/" in s or s.startswith(("/", "\\")) or (len(s) > 2 and s[1] == ":" and s[2] in ("\\", "/"))


def _find_log_report_path(obj: Any) -> Optional[str]:
    """Search recursively for Log Report File Path. Only return values that look like paths (/mnt/...)."""
    if obj is None:
        return None
    if isinstance(obj, str):
        s = obj.strip()
        return s if s and _looks_like_file_path(s) else None
    if isinstance(obj, dict):
        # Prefer keys that explicitly mention Log Report File Path
        for key in (
            "Log - Info - Log Report File Path",
            "#Log - Info - Log Report File Path",
            "log_report_file_path",
            "Log Report File Path",
            "logReportFilePath",
            "REPORT_PATH",
        ):
            v = obj.get(key)
            if v is not None and str(v).strip() and _looks_like_file_path(str(v)):
                return str(v).strip()
        for k, v in obj.items():
            if v is not None and "Log Report File Path" in str(k) and _looks_like_file_path(str(v)):
                return str(v).strip()
        if obj.get("label") and "Log Report File Path" in str(obj.get("label", "")):
            val = obj.get("value") or obj.get("val")
            if val is not None and str(val).strip() and _looks_like_file_path(str(val)):
                return str(val).strip()
        for v in obj.values():
            found = _find_log_report_path(v)
            if found:
                return found
    if isinstance(obj, list):
        for item in obj:
            found = _find_log_report_path(item)
            if found:
                return found
    return None


def fetch_node_info(
    node_log_id: Any,
    *,
    execute_log_id: str = "",
    all_detail: bool = False,
    load_tcs: bool = False,
    timeout: int = 15,
) -> Tuple[Optional[dict], Optional[str]]:
    """GET /api/get_node_info with API-2 query keys from the capture."""
    base, token = _get_config()
    node = str(node_log_id or "").strip()
    if not base:
        return None, "CRABBER_BASE_URL empty"
    if not node:
        return None, "node_log_id empty"
    url = (
        f"{base}/api/get_node_info/"
        f"?node_log_id={quote(node, safe='')}"
        f"&execute_log_id={quote(str(execute_log_id or ''), safe='')}"
        f"&all_detail={'true' if all_detail else 'false'}"
        f"&load_tcs={'true' if load_tcs else 'false'}"
    )
    try:
        r = requests.get(url, headers=_headers(token), timeout=timeout)
        if not r.ok:
            return None, f"HTTP {r.status_code}"
        data = r.json()
        if not isinstance(data, dict):
            return None, "response is not a JSON object"
        return data, None
    except Exception as e:
        return None, str(e)


def _derive_crabber_display_result(raw_result: str, node_log_event: str) -> str:
    """Map node_log_event to UI result; empty event means finished test — use API result (Pass/Fail/…)."""
    ev = (node_log_event or "").strip().upper()
    if ev == "TPSQ":
        return "Canceled"
    if ev == "PROC":
        return "Testing"
    return (raw_result or "").strip()


def fetch_test_history_for_sn(
    sn: str, timeout: int = 20, limit: int = 100, is_trial: bool = False
) -> dict:
    """
    List test log rows for SN from Crabber search_log_items (no per-row node detail fetch).

    Returns {ok, tests, error?, raw_total?}. Each test row:
      sn, station, result (display: Canceled / Testing / API Pass|Fail|…),
      test_time (legacy: same as start time source), log_time (ISO UTC, prefer API log_time),
      sfc_event_date (ISO UTC when test finished / SFC posted; empty while PROC/TPSQ or missing),
      node_log_id, exe_log_id, log_folder_unc (Oberon UNC uses node_log_id segment), pn, pn_name, machine, machine_id,
      phase, project, node_log_event (raw, for UI polling),
      procedure, revision (for Crabber UI deep-link cookie + processing_info query).
    """
    base, token = _get_config()
    result: dict = {"ok": False, "tests": [], "error": None}
    if not base or not (sn or "").strip():
        result["error"] = "CRABBER_BASE_URL empty or sn empty"
        return result
    sn = sn.strip()
    search_url = build_search_log_items_url(base, sn=sn, cur_page=1, is_trial=is_trial)
    try:
        r = requests.get(search_url, headers=_headers(token), timeout=timeout)
        if not r.ok:
            result["error"] = f"HTTP {r.status_code}"
            return result
        search_resp = r.json()
    except Exception as e:
        result["error"] = str(e)
        return result

    items = _extract_items_list(search_resp) or []
    if not items:
        result["ok"] = True
        result["tests"] = []
        result["raw_total"] = search_resp.get("total_logs") if isinstance(search_resp, dict) else 0
        return result

    out = []
    n = 0
    for it in items:
        if n >= limit:
            break
        if not isinstance(it, dict):
            continue
        node_log_id_str = extract_node_log_id(it)
        _exe_raw = it.get("exe_log_id") if it.get("exe_log_id") is not None else it.get("exeLogId")
        exe_log_id_str = str(_exe_raw).strip() if _exe_raw is not None else ""
        node_log_event = str(
            it.get("node_log_event") or it.get("nodeLogEvent") or ""
        ).strip()
        raw_res = str(it.get("result") or it.get("Result") or "").strip()
        log_time_iso = str(it.get("log_time") or it.get("LogTime") or "").strip()
        test_time = log_time_iso or str(
            it.get("test_time")
            or it.get("end_time")
            or it.get("time")
            or it.get("start_time")
            or it.get("create_time")
            or ""
        ).strip()
        if not log_time_iso:
            log_time_iso = test_time
        log_folder_unc = (
            build_crabber_log_folder_unc(log_time_iso, node_log_id_str)
            if node_log_id_str
            else ""
        )
        sfc_raw = it.get("sfc_event_date") or it.get("sfcEventDate")
        sfc_event_date = str(sfc_raw).strip() if sfc_raw is not None and str(sfc_raw).strip() else ""
        pn_name = str(
            it.get("pn_name")
            or it.get("pnName")
            or it.get("pn")
            or it.get("PN")
            or it.get("part_number")
            or ""
        ).strip()
        procedure = str(
            it.get("procedure")
            or it.get("procedure_id")
            or it.get("procedureId")
            or ""
        ).strip()
        revision = str(
            it.get("revision")
            or it.get("procedure_rev")
            or it.get("procedureRev")
            or ""
        ).strip()
        machine_id = str(
            it.get("machine_id")
            or it.get("machineId")
            or it.get("mac_id")
            or ""
        ).strip()
        row_sn = str(it.get("sn") or it.get("SN") or "").strip()
        out.append(
            {
                "sn": row_sn,
                "station": str(it.get("station") or it.get("Station") or "").strip(),
                "result": _derive_crabber_display_result(raw_res, node_log_event),
                "test_time": test_time,
                "log_time": log_time_iso,
                "sfc_event_date": sfc_event_date,
                "node_log_id": node_log_id_str,
                "exe_log_id": exe_log_id_str,
                "log_folder_unc": log_folder_unc,
                "pn": pn_name,
                "pn_name": pn_name,
                "machine": str(
                    it.get("machine") or it.get("machine_name") or it.get("Machine") or ""
                ).strip(),
                "machine_id": machine_id,
                "phase": str(it.get("phase") or it.get("Phase") or "").strip(),
                "project": str(it.get("project") or it.get("Project") or "").strip(),
                "node_log_event": node_log_event,
                "procedure": procedure,
                "revision": revision,
            }
        )
        n += 1

    result["ok"] = True
    result["tests"] = out
    if isinstance(search_resp, dict) and search_resp.get("total_logs") is not None:
        result["raw_total"] = search_resp.get("total_logs")
    else:
        result["raw_total"] = len(items)
    return result


def sn_has_active_crabber_test(
    sn: str, *, timeout: int = 12, limit: int = 80, is_trial: bool = False
) -> tuple[bool, Optional[str]]:
    """
    True if Crabber log rows for SN show an in-progress test (node_log_event PROC or display Testing).

    Returns (active, crabber_error). crabber_error is set when the Crabber list could not be fetched;
    (False, None) means fetched OK and no active row.
    """
    s = (sn or "").strip()
    if not s:
        return False, "sn empty"
    res = fetch_test_history_for_sn(s, timeout=timeout, limit=limit, is_trial=is_trial)
    if not res.get("ok"):
        return False, str(res.get("error") or "crabber fetch failed")
    want = s.upper()
    for t in res.get("tests") or []:
        if not isinstance(t, dict):
            continue
        row_sn = str(t.get("sn") or t.get("SN") or "").strip().upper()
        if row_sn and row_sn != want:
            continue
        ev = str(t.get("node_log_event") or "").strip().upper()
        if ev == "PROC":
            return True, None
        disp = str(t.get("result") or "").strip().upper()
        if disp == "TESTING":
            return True, None
    return False, None


def fetch_log_report_path(sn: str, timeout: int = 15) -> Optional[str]:
    """
    Fetch Log Report File Path for SN.
    1. GET /api/search_log_items/?sn=XXX -> latest node_log_id
    2. GET /api/get_node_info/?node_log_id=XXX -> Log Report File Path
    Returns path string or None if not found / API disabled.
    """
    base, _ = _get_config()
    if not base or not (sn or "").strip():
        return None
    sn = sn.strip()

    items, _, err = fetch_search_log_items_all_pages(sn=sn, is_trial=False, timeout=timeout)
    if err or not items:
        return None

    # Only Pass/Fail - skip Unfinished
    completed = [
        x for x in items
        if isinstance(x, dict)
        and (x.get("result") or "").strip().upper() in ("PASS", "FAIL")
    ]
    if not completed:
        return None

    # Pick first (latest) - API typically returns newest first
    first = completed[0]
    if not isinstance(first, dict):
        return None
    node_log_id = (
        first.get("node_log_id")
        or first.get("nodeLogId")
        or first.get("log_id")
        or first.get("id")
    )
    if not node_log_id:
        return None
    node_log_id = str(node_log_id).strip()

    detail, detail_err = fetch_node_info(
        node_log_id,
        execute_log_id="",
        all_detail=False,
        load_tcs=False,
        timeout=timeout,
    )
    if detail_err or not detail:
        return None

    return _find_log_report_path(detail)


def fetch_log_report_path_debug(sn: str, timeout: int = 15) -> dict:
    """
    Debug version: returns step-by-step info to diagnose 404.
    Call /api/debug/log-path-debug?sn=XXX
    """
    base, token = _get_config()
    result = {
        "ok": False,
        "path": None,
        "step1": {},
        "step2": {},
        "error": None,
    }
    if not base or not (sn or "").strip():
        result["error"] = "CRABBER_BASE_URL empty or sn empty"
        return result
    sn = sn.strip()
    result["base_url"] = base
    result["sn"] = sn
    result["has_token"] = bool(token)

    # Step 1
    search_url = build_search_log_items_url(base, sn=sn, cur_page=1, is_trial=False)
    result["step1"]["url"] = search_url
    try:
        r = requests.get(search_url, headers=_headers(token), timeout=timeout)
        result["step1"]["status_code"] = r.status_code
        result["step1"]["status_reason"] = r.reason
        if not r.ok:
            result["step1"]["error"] = r.text[:500] if r.text else "No body"
            return result
        search_resp = r.json()
    except Exception as e:
        result["step1"]["error"] = str(e)
        return result

    result["step1"]["keys"] = list(search_resp.keys())[:30] if isinstance(search_resp, dict) else []
    items = _extract_items_list(search_resp)

    if not items or not isinstance(items, list):
        result["step1"]["error"] = "No items list in response (tried: items, results, data, logs, log_items, nodes, etc.)"
        return result
    result["step1"]["items_count"] = len(items)

    completed = [
        x for x in items
        if isinstance(x, dict)
        and (x.get("result") or "").strip().upper() in ("PASS", "FAIL")
    ]
    result["step1"]["completed_count"] = len(completed)
    if not completed:
        result["step1"]["error"] = "No Pass/Fail logs (all Unfinished?)"
        return result

    first = completed[0]
    if not isinstance(first, dict):
        result["step1"]["error"] = f"First item not dict: {type(first)}"
        return result
    result["step1"]["first_item_keys"] = list(first.keys())[:30]

    node_log_id = (
        first.get("node_log_id")
        or first.get("nodeLogId")
        or first.get("log_id")
        or first.get("id")
    )
    if not node_log_id:
        result["step1"]["error"] = "node_log_id not found in first item"
        return result
    node_log_id = str(node_log_id).strip()
    result["step1"]["node_log_id"] = node_log_id

    # Step 2
    detail_url = (
        f"{base}/api/get_node_info/"
        f"?node_log_id={node_log_id}&execute_log_id=&all_detail=false&load_tcs=false"
    )
    result["step2"]["url"] = detail_url
    try:
        r = requests.get(detail_url, headers=_headers(token), timeout=timeout)
        result["step2"]["status_code"] = r.status_code
        if not r.ok:
            result["step2"]["error"] = r.text[:500] if r.text else "No body"
            return result
        detail = r.json()
    except Exception as e:
        result["step2"]["error"] = str(e)
        return result

    result["step2"]["detail_keys"] = list(detail.keys())[:30] if isinstance(detail, dict) else []
    path = _find_log_report_path(detail)
    if path:
        result["ok"] = True
        result["path"] = path
    else:
        result["step2"]["error"] = "Log Report File Path not found in response"
    return result
