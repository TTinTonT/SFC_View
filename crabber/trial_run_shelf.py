# -*- coding: utf-8 -*-
"""Crabber MFG shelf list + station list for FA Debug Trial Run page."""

from __future__ import annotations

import re
from typing import Any, Dict


def _plain_process_sfc_message(message: Any) -> str:
    if message is None:
        return ""
    s = str(message)
    s = re.sub(r"<[^>]+>", " ", s, flags=re.IGNORECASE)
    return " ".join(s.split()).strip()


def process_sfc_payload_indicates_failure(psfc: Any) -> tuple[bool, str]:
    """
    Trial run only: Crabber may return HTTP 200 with failure in process_sfc JSON
    (e.g. message HTML with failed=NG, INPUT DATA ERROR). When True, do not send_list.
    """
    if not isinstance(psfc, dict):
        return False, ""
    if psfc.get("ok") is False:
        err = psfc.get("error") or psfc.get("message") or "process_sfc failed"
        return True, _plain_process_sfc_message(err) or "process_sfc failed"
    msg = psfc.get("message")
    if not msg:
        return False, ""
    raw = str(msg)
    lower = raw.lower()
    collapsed = re.sub(r"\s+", "", lower)
    if "failed=ng" in collapsed or "input data error" in lower:
        plain = _plain_process_sfc_message(raw)
        return True, plain or "process_sfc reported failure"
    return False, ""


def is_pn_mapping_true_for_trial_run(row: dict) -> bool:
    """
    Crabber MFG shelf rows include is_pn_mapping; Trial run is only offered when true.
    If the field is absent or null, default True (older API payloads).
    """
    if "is_pn_mapping" not in row:
        return True
    v = row.get("is_pn_mapping")
    if v is None:
        return True
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


def pn_name_from_shelf_procedure_row(row: dict) -> str:
    """Derive pn_name for /api/etf/online-test/prepare from a get_shelf_procedure_released row."""
    if not isinstance(row, dict):
        return ""
    for key in ("pn_name", "pn", "opt_pn_name", "model_pn", "product_pn", "craft_pn"):
        v = row.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    for key in ("code", "pn_code", "mapping_pn", "srv_pn"):
        v = row.get(key)
        if v is not None and str(v).strip():
            first = str(v).split(",")[0].strip()
            if first:
                return first
    return ""


def normalize_result_list(resp: Any) -> list:
    if isinstance(resp, dict):
        for k in ("result_list", "results", "data", "items"):
            v = resp.get(k)
            if isinstance(v, list):
                return v
        return []
    if isinstance(resp, list):
        return resp
    return []


def shelf_row_to_card(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    rid = row.get("id")
    if rid is None:
        return None
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return None
    tp_num = row.get("test_procedure")
    tp_label = ""
    if tp_num is not None:
        try:
            tp_label = f"TP{int(tp_num):06d}"
        except (TypeError, ValueError):
            tp_label = str(tp_num).strip()
    rev = row.get("test_procedure_revision")
    if rev is None:
        rev = row.get("rev")
    pn_name = pn_name_from_shelf_procedure_row(row)
    return {
        "id": rid,
        "pn_name": pn_name,
        "is_pn_mapping": is_pn_mapping_true_for_trial_run(row),
        "tp_label": tp_label,
        "rev": str(rev) if rev is not None else "",
        "project": row.get("project") or "",
        "station": row.get("station") or "",
        "description": row.get("description") or "",
        "releaser": row.get("releaser") or row.get("released_by") or "",
        "modified_date": row.get("modified_date") or row.get("modified") or "",
        "phase": row.get("phase") or "",
    }


def normalize_rd_shelf_for_prepare(raw: Any, fallback_pn: str = "") -> Dict[str, Any]:
    """
    Shape Crabber get_rd_shelf_scan_item_list JSON like ETF prepare output.
    fallback_pn: pn_name from shelf card (required if API omits pn in shelf_proc_data).
    """
    if isinstance(raw, dict):
        for wrap in ("data", "result", "payload"):
            inner = raw.get(wrap)
            if isinstance(inner, dict) and (
                inner.get("shelf_proc_data") is not None or inner.get("machines") is not None
            ):
                raw = inner
                break
    if not isinstance(raw, dict):
        raise ValueError("shelf scan response must be a JSON object")
    machines = raw.get("machines") or []
    scan_items = raw.get("scan_items") or []
    env_items = raw.get("env_items") or []
    shelf_proc_data = raw.get("shelf_proc_data") or {}
    if not isinstance(shelf_proc_data, dict):
        shelf_proc_data = {}
    pn_name = (fallback_pn or "").strip()
    if not pn_name:
        for k in ("pn_name", "pn", "opt_pn_name", "mapping_pn"):
            v = shelf_proc_data.get(k)
            if v is not None and str(v).strip():
                pn_name = str(v).strip()
                break
    sfc_ext = (
        raw.get("sfc_ext")
        or shelf_proc_data.get("sfc_ext")
        or ""
    )
    if isinstance(sfc_ext, dict):
        import json as _json

        sfc_ext = _json.dumps(sfc_ext, ensure_ascii=False)
    return {
        "pn_name": pn_name,
        "machines": machines if isinstance(machines, list) else [],
        "scan_items": scan_items if isinstance(scan_items, list) else [],
        "env_items": env_items if isinstance(env_items, list) else [],
        "shelf_proc_data": shelf_proc_data,
        "sfc_ext": sfc_ext if isinstance(sfc_ext, str) else "",
    }


def normalize_station_list(resp: Any) -> list[dict]:
    """Return [{id, name}, ...] from Crabber getStationList response."""
    if resp is None:
        return []
    items: Any = resp
    if isinstance(resp, dict):
        for k in ("result", "results", "data", "stations", "station_list", "items"):
            v = resp.get(k)
            if isinstance(v, list):
                items = v
                break
        else:
            items = []
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        sid = it.get("id")
        if sid is None:
            sid = it.get("station_id") or it.get("pk")
        name = (
            it.get("name")
            or it.get("station")
            or it.get("station_name")
            or it.get("text")
            or it.get("key")
            or (str(sid) if sid is not None else "")
        )
        if sid is None:
            continue
        try:
            sid_i = int(sid)
        except (TypeError, ValueError):
            sid_i = sid
        out.append({"id": sid_i, "name": str(name)})
    return out
