# -*- coding: utf-8 -*-
"""
Crabber API client: search by SN -> node_log_id -> get_node_info -> Log Report File Path.

Flow:
  1. GET /api/search_log_items/?sn=XXX -> get latest node_log_id
  2. GET /api/get_node_info/?node_log_id=XXX -> extract Log Report File Path from Log-Info section
"""
from typing import Any, Optional

import requests


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


def fetch_log_report_path(sn: str, timeout: int = 15) -> Optional[str]:
    """
    Fetch Log Report File Path for SN.
    1. GET /api/search_log_items/?sn=XXX -> latest node_log_id
    2. GET /api/get_node_info/?node_log_id=XXX -> Log Report File Path
    Returns path string or None if not found / API disabled.
    """
    base, token = _get_config()
    if not base or not (sn or "").strip():
        return None
    sn = sn.strip()

    # Step 1: Search logs by SN
    search_url = (
        f"{base}/api/search_log_items/"
        f"?cur_page=1&project=&station=&phase=&precondition=&label_data=&result=All"
        f"&spid=&machine=&pn=&from_date=&to_date=&sfc=&cal_total=false&is_trial=false"
        f"&sn={sn}"
    )
    try:
        r = requests.get(search_url, headers=_headers(token), timeout=timeout)
        if not r.ok:
            return None
        search_resp = r.json()
    except Exception:
        return None

    # Extract node_log_id - try common keys and nested structures
    items = _extract_items_list(search_resp)
    if not items or not isinstance(items, list) or len(items) == 0:
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

    # Step 2: Get log details
    detail_url = (
        f"{base}/api/get_node_info/"
        f"?node_log_id={node_log_id}&execute_log_id=&all_detail=false&load_tcs=false"
    )
    try:
        r = requests.get(detail_url, headers=_headers(token), timeout=timeout)
        if not r.ok:
            return None
        detail = r.json()
    except Exception:
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
    search_url = (
        f"{base}/api/search_log_items/"
        f"?cur_page=1&project=&station=&phase=&precondition=&label_data=&result=All"
        f"&spid=&machine=&pn=&from_date=&to_date=&sfc=&cal_total=false&is_trial=false"
        f"&sn={sn}"
    )
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
