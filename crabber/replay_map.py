# -*- coding: utf-8 -*-
"""Crabber raw offline replay mapping + preflight gates."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from config.debug_config import (
    REPLAY_AUX_BUNDLE_ROOT,
    REPLAY_DATACENTER_CMD,
    REPLAY_DEFAULT_SKU,
    REPLAY_FACTORY_CODE_DEFAULT,
    REPLAY_MAIN_BUNDLE_ROOT,
    REPLAY_TEST_BAY_PORT_MAP,
)

PROCESS_ALLOWLIST = {
    "BAT", "FLA", "FLW", "FLB", "FLC", "FCT", "FTS", "RIN", "DCC", "IOT", "NVL", "AST", "SOT",
}
BLOCKED_NAME_HINTS = ("PASSWORD", "TOKEN", "SECRET", "KEY")
SHELL_DANGEROUS = ("`", "$(", "${", ";", "|", "&", "<", ">")
SAFE_KEY_RE = re.compile(r"^[A-Z0-9_]+$")


def _as_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _norm_process(v: Any) -> str:
    return _as_str(v).upper()


def _normalize_mac(v: str) -> str:
    s = _as_str(v).lower().replace("-", ":")
    return s


def is_incomplete_or_special(row: Dict[str, Any]) -> bool:
    return (
        _as_str(row.get("result")) == ""
        or _as_str(row.get("node_log_event")) != ""
        or (row.get("sfc_event_id") is None and row.get("sfc_result") is None)
    )


def normalize_run_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "node_log_id": _as_str(row.get("node_log_id")),
        "exe_log_id": _as_str(row.get("exe_log_id")),
        "station": _as_str(row.get("station")),
        "machine": _as_str(row.get("machine")),
        "result": _as_str(row.get("result")),
        "procedure": _as_str(row.get("procedure")),
        "revision": _as_str(row.get("revision")),
        "pn_name": _as_str(row.get("pn_name")),
        "log_time": _as_str(row.get("log_time")),
        "sn": _as_str(row.get("sn")),
        "node_log_event": _as_str(row.get("node_log_event")),
        "sfc_event_id": row.get("sfc_event_id"),
        "sfc_result": row.get("sfc_result"),
    }
    out["incomplete_or_special"] = is_incomplete_or_special(out)
    return out


def group_runs_by_station(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        st = _as_str(r.get("station")) or "UNKNOWN"
        grouped.setdefault(st, []).append(r)
    return grouped


def _uut_info_to_map(uut_info: Any) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    if not isinstance(uut_info, list):
        return {}, None
    out: Dict[str, str] = {}
    for it in uut_info:
        if not isinstance(it, dict):
            continue
        k = _as_str(it.get("scan_code"))
        if not k:
            continue
        if k in out:
            return None, f"Duplicate scan_code detected: {k}"
        out[k] = _as_str(it.get("scan_value"))
    return out, None


def _safe_value(v: str) -> bool:
    if "\n" in v or "\r" in v:
        return False
    for token in SHELL_DANGEROUS:
        if token in v:
            return False
    return True


def _is_fla_replay_context(test_bay_location: str, selected: Dict[str, Any]) -> bool:
    """FLA-only: allow missing DUT_IP when bay/machine/station clearly indicates FLA (not FLB)."""
    tl = _as_str(test_bay_location).upper()
    if "_FLA_" in tl or tl.startswith("FLA_"):
        return True
    machine = _as_str(selected.get("machine")).upper()
    if "_FLA_" in machine or "-FLA_" in machine:
        return True
    st = _as_str(selected.get("station")).upper()
    if "FLA" in st and "FLB" not in st:
        return True
    return False


def validate_replay_datafile_override(text: str) -> Optional[str]:
    """Return error message if user-supplied datafile text is unsafe; None if OK."""
    if not _as_str(text):
        return None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            return "invalid datafile line (expected KEY:VALUE)"
        key, _, val = line.partition(":")
        ku = key.strip().upper()
        vs = val.strip()
        if not SAFE_KEY_RE.match(ku):
            return f"invalid datafile key: {ku}"
        if any(hint in ku for hint in BLOCKED_NAME_HINTS):
            return f"blocked datafile key: {ku}"
        if not _safe_value(vs):
            return f"unsafe value for {ku}"
    return None


def _resolve_process(uut_map: Dict[str, str], selected_station: str) -> Tuple[str, List[str], bool]:
    candidates: List[str] = []
    for key in ("MFG_DIAG_PROCESS", "PROCESS"):
        val = _norm_process(uut_map.get(key))
        if val:
            candidates.append(val)
    station_derived = _norm_process(_as_str(selected_station).replace("SYSTEM_", "", 1))
    if station_derived:
        candidates.append(station_derived)
    non_empty = [c for c in candidates if c]
    if not non_empty:
        return "", ["PROCESS cannot be resolved"], False
    valid = [c for c in non_empty if c in PROCESS_ALLOWLIST]
    if not valid:
        return "", [f"PROCESS not in allowlist: {', '.join(non_empty)}"], False
    if len(set(valid)) > 1:
        return "", [f"PROCESS conflict across sources: {', '.join(sorted(set(valid)))}"], False
    return valid[0], [], True


def _select_value(key: str, uut_map: Dict[str, str], basic: Dict[str, Any], default: str = "") -> str:
    if _as_str(uut_map.get(key)):
        return _as_str(uut_map.get(key))
    if _as_str(basic.get(key)):
        return _as_str(basic.get(key))
    return default


def _resolve_factory_code(uut_map: Dict[str, str]) -> str:
    return _as_str(uut_map.get("FACTORY_CODE")) or _as_str(REPLAY_FACTORY_CODE_DEFAULT)


def _resolve_port(test_bay_location: str, ui_overrides: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    slot_override = _as_str(ui_overrides.get("slot_number"))
    if slot_override:
        digits = "".join([c for c in slot_override if c.isdigit()])
        if digits:
            port = digits[-2:].zfill(2)
            return port, None
    raw = _as_str(REPLAY_TEST_BAY_PORT_MAP) or "{}"
    try:
        mapping = json.loads(raw)
    except Exception:
        mapping = {}
    if not isinstance(mapping, dict):
        mapping = {}
    port = _as_str(mapping.get(test_bay_location))
    if not port:
        return "", "TEST_BAY_LOCATION cannot be resolved to port"
    if port == "00":
        return "", "PORT=00 is blocked for production replay"
    return port, None


def _derive_test_bay_location(
    uut_map: Dict[str, str],
    basic: Dict[str, Any],
    ui_overrides: Dict[str, Any],
    selected_station: str,
) -> str:
    override_loc = _as_str(ui_overrides.get("test_bay_location"))
    if override_loc:
        return override_loc
    proc = _norm_process(_as_str(selected_station).replace("SYSTEM_", "", 1))
    slot_override = _as_str(ui_overrides.get("slot_number"))
    if slot_override:
        return f"{proc}_FA_{slot_override.zfill(2)}" if proc else f"FA_{slot_override.zfill(2)}"
    direct = _select_value("TEST_BAY_LOCATION", uut_map, basic, default="")
    if direct:
        return direct
    station_id = _select_value("STATION_ID", uut_map, basic, default="")
    m = re.search(r"(FA[_-]?\d+)", station_id, re.IGNORECASE)
    if m:
        val = m.group(1).upper().replace("-", "_")
        if "_" not in val:
            val = val[:2] + "_" + val[2:]
        return val
    return ""


def _resolve_bundle_paths(uut_map: Dict[str, str]) -> Tuple[Dict[str, str], List[str]]:
    out: Dict[str, str] = {}
    reasons: List[str] = []
    # Prefer direct runtime bundle paths from captured run detail when available.
    direct_main = _as_str(uut_map.get("MFG_DIAG_FILE_PATH"))
    direct_aux = _as_str(uut_map.get("MFG_DIAG_AUX_FILE_PATH"))
    if direct_main:
        out["MAIN_BUNDLE"] = direct_main
    if direct_aux:
        out["AUX_BUNDLE"] = direct_aux
    fw = _as_str(uut_map.get("FW_VERSION_DIAG"))
    aux = _as_str(uut_map.get("MFG_DIAG_AUX"))
    if not direct_main and fw and REPLAY_MAIN_BUNDLE_ROOT:
        out["MAIN_BUNDLE"] = os.path.join(REPLAY_MAIN_BUNDLE_ROOT, fw)
    elif not direct_main and fw:
        reasons.append("REPLAY_MAIN_BUNDLE_ROOT is empty")
    if not direct_aux and aux and REPLAY_AUX_BUNDLE_ROOT:
        out["AUX_BUNDLE"] = os.path.join(REPLAY_AUX_BUNDLE_ROOT, os.path.basename(aux))
    elif not direct_aux and aux:
        reasons.append("REPLAY_AUX_BUNDLE_ROOT is empty")
    return out, reasons


def _collect_tcs_ips_tags(obj: Any, ips: List[str], tags: List[str]) -> None:
    if isinstance(obj, dict):
        # Do not use "server_ip" — unreliable in Crabber payloads; only test_server_ip.
        raw_ip = obj.get("test_server_ip")
        if isinstance(raw_ip, list):
            for x in raw_ip:
                s = _as_str(x)
                if s:
                    ips.append(s)
        else:
            s = _as_str(raw_ip)
            if s:
                ips.append(s)
        tag = _as_str(obj.get("machine_tag"))
        if tag:
            tags.append(tag)
        for v in obj.values():
            if isinstance(v, str):
                sv = v.strip()
                if sv and ((sv.startswith("{") and sv.endswith("}")) or (sv.startswith("[") and sv.endswith("]"))):
                    try:
                        parsed = json.loads(sv)
                    except Exception:
                        parsed = None
                    if isinstance(parsed, (dict, list)):
                        _collect_tcs_ips_tags(parsed, ips, tags)
            if isinstance(v, (dict, list)):
                _collect_tcs_ips_tags(v, ips, tags)
    elif isinstance(obj, list):
        for it in obj:
            _collect_tcs_ips_tags(it, ips, tags)


def _extract_tcs_server_meta(detail: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    ips: List[str] = []
    tags: List[str] = []
    tcs = detail.get("test_case_command_list")
    if isinstance(tcs, list):
        for item in tcs:
            _collect_tcs_ips_tags(item, ips, tags)

    def _dedupe(seq: List[str]) -> List[str]:
        seen: set = set()
        out: List[str] = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    ips_dedup = _dedupe(ips)
    tags_dedup = _dedupe(tags)
    if ips_dedup:
        return ips_dedup, tags_dedup

    # Fallback: some Crabber payloads bury test_server_ip inside serialized JSON strings.
    # Scan the full detail payload text and only accept IPv4s that appear near "test_server_ip".
    try:
        blob = json.dumps(detail, ensure_ascii=False)
    except Exception:
        blob = ""
    if blob:
        hits: List[str] = []
        for m in re.finditer(r'test_server_ip[^0-9]*(\d{1,3}(?:\.\d{1,3}){3})', blob, re.IGNORECASE):
            ip = _as_str(m.group(1))
            if ip:
                hits.append(ip)
        if hits:
            ips_dedup = _dedupe(hits)
    return ips_dedup, tags_dedup


def _extract_uut_machine_name(detail: Dict[str, Any], selected: Dict[str, Any]) -> str:
    direct = _as_str(((detail.get("basic_info") or {}) if isinstance(detail.get("basic_info"), dict) else {}).get("uut_machine_name"))
    if direct:
        return direct
    stack: List[Any] = [detail.get("test_case_command_list")]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            v = _as_str(cur.get("uut_machine_name"))
            if v:
                return v
            for vv in cur.values():
                if isinstance(vv, (dict, list)):
                    stack.append(vv)
        elif isinstance(cur, list):
            stack.extend(cur)
    return _as_str(selected.get("machine"))


def _cross_check(selected: Dict[str, Any], detail: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    basic = detail.get("basic_info") if isinstance(detail.get("basic_info"), dict) else {}
    if _as_str(basic.get("node_log_id")) != _as_str(selected.get("node_log_id")):
        reasons.append("basic_info.node_log_id mismatch")
    sel_exe = _as_str(selected.get("exe_log_id"))
    det_exe = _as_str(basic.get("execution_log_id"))
    if sel_exe and det_exe and sel_exe != det_exe:
        reasons.append("exe_log_id vs execution_log_id mismatch")
    if _as_str(basic.get("node_sn")) != _as_str(selected.get("sn")):
        reasons.append("node_sn mismatch")
    if _as_str(basic.get("station")) != _as_str(selected.get("station")):
        reasons.append("station mismatch")
    if _as_str(basic.get("tp_id")) != _as_str(selected.get("procedure")):
        reasons.append("procedure/tp_id mismatch")
    if _as_str(basic.get("tp_rev")) != _as_str(selected.get("revision")):
        reasons.append("revision/tp_rev mismatch")
    pn = _as_str(basic.get("pn"))
    if pn and _as_str(selected.get("pn_name")) and pn != _as_str(selected.get("pn_name")):
        reasons.append("pn mismatch")
    rel = detail.get("related_nodes_info")
    if isinstance(rel, list) and len(rel) > 1:
        selected_node = _as_str(selected.get("node_log_id"))
        count = 0
        for n in rel:
            if isinstance(n, dict) and _as_str(n.get("node_log_id")) == selected_node:
                count += 1
        if count != 1:
            reasons.append("related_nodes_info ambiguous for selected node_log_id")
    return reasons


def prepare_replay(
    selected_run: Dict[str, Any],
    detail_payload: Dict[str, Any],
    ui_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    selected = normalize_run_row(selected_run or {})
    ui_overrides = ui_overrides or {}
    reasons: List[str] = []
    allow_raw = ui_overrides.get("allow_incomplete_or_special")
    allow_incomplete = True if allow_raw is None else bool(allow_raw)
    if selected.get("incomplete_or_special") and not allow_incomplete:
        reasons.append("run is incomplete_or_special")
    reasons.extend(_cross_check(selected, detail_payload or {}))
    basic = detail_payload.get("basic_info") if isinstance(detail_payload.get("basic_info"), dict) else {}
    uut_map, dup_err = _uut_info_to_map(detail_payload.get("uut_info"))
    if dup_err:
        reasons.append(dup_err)
        uut_map = {}

    process, proc_reasons, proc_ok = _resolve_process(uut_map or {}, selected.get("station") or "")
    reasons.extend(proc_reasons)
    factory_code = _resolve_factory_code(uut_map or {})
    if not factory_code:
        reasons.append("FACTORY_CODE is empty")

    test_bay_location = _derive_test_bay_location(
        uut_map or {},
        basic,
        ui_overrides,
        selected.get("station") or "",
    )
    port, port_err = _resolve_port(test_bay_location, ui_overrides) if test_bay_location else ("", "TEST_BAY_LOCATION missing")
    if port_err:
        reasons.append(port_err)

    bundle_paths, bundle_reasons = _resolve_bundle_paths(uut_map or {})
    reasons.extend(bundle_reasons)

    test_server_ips, machine_tags = _extract_tcs_server_meta(detail_payload or {})
    uut_machine_name = _extract_uut_machine_name(detail_payload or {}, selected)
    sku_val = _select_value("SKU", uut_map or {}, basic, "") or _as_str(REPLAY_DEFAULT_SKU)

    direct_map = {
        "PRODUCT": _select_value("PRODUCT_NAME", uut_map or {}, basic, ""),
        "SKU": sku_val,
        "SN": _select_value("SN", uut_map or {}, basic, "") or _select_value("SCAN_SYSTEM_SN", uut_map or {}, basic, ""),
        "PN": _select_value("PN", uut_map or {}, basic, ""),
        "PRODUCT_PN": _select_value("PRODUCT_PN", uut_map or {}, basic, ""),
        "PBR": _select_value("PBR_NUMBER", uut_map or {}, basic, ""),
        "BMC_IP": _select_value("COMPUTE_TRAY_BMC_IP", uut_map or {}, basic, ""),
        "BMC_MAC": _normalize_mac(_select_value("BMC_MAC", uut_map or {}, basic, "")),
        "DUT_IP": _select_value("COMPUTE_TRAY_HOST_IP", uut_map or {}, basic, ""),
        "DUT_MAC": _normalize_mac(_select_value("HOST_MAC", uut_map or {}, basic, "")),
        "PDB_BOARD_SN": _select_value("PDB_BOARD_SN", uut_map or {}, basic, ""),
        "PDB_BOARD_PN": _select_value("PDB_BOARD_PN", uut_map or {}, basic, ""),
        "MIDPLANE_SN": _select_value("MIDPLANE_BOARD_SN", uut_map or {}, basic, ""),
        "MIDPLANE_PN": _select_value("MIDPLANE_BOARD_PN", uut_map or {}, basic, ""),
        "PDB_CHASSIS_PN": _select_value("PN_CHASSIS", uut_map or {}, basic, "") or _select_value("PN", uut_map or {}, basic, ""),
        "PDB_CHASSIS_SN": _select_value("SN", uut_map or {}, basic, ""),
        "PROCESS": process,
    }

    required = (
        "PRODUCT", "SKU", "PROCESS", "SN", "PN", "PBR", "BMC_IP", "BMC_MAC", "DUT_IP", "DUT_MAC",
        "PDB_CHASSIS_SN", "PDB_CHASSIS_PN", "MIDPLANE_SN", "MIDPLANE_PN",
    )
    if _is_fla_replay_context(test_bay_location, selected):
        required = tuple(k for k in required if k != "DUT_IP")
    for key in required:
        if not _as_str(direct_map.get(key)):
            reasons.append(f"missing required field: {key}")

    datafile_lines: List[str] = []
    redacted_fields: Dict[str, Any] = {
        "node_log_id": selected.get("node_log_id"),
        "exe_log_id": selected.get("exe_log_id"),
        "station": selected.get("station"),
        "procedure": selected.get("procedure"),
        "revision": selected.get("revision"),
        "pn_name": selected.get("pn_name"),
        "log_time": selected.get("log_time"),
        "machine": selected.get("machine"),
    }

    for k, v in direct_map.items():
        key = _as_str(k).upper()
        val = _as_str(v)
        if not SAFE_KEY_RE.match(key):
            reasons.append(f"invalid key format: {key}")
            continue
        if any(hint in key for hint in BLOCKED_NAME_HINTS):
            reasons.append(f"blocked key name: {key}")
            continue
        if not _safe_value(val):
            reasons.append(f"unsafe value for {key}")
            continue
        datafile_lines.append(f"{key}:{val}")

    onediag_aux = _as_str(bundle_paths.get("AUX_BUNDLE"))
    if onediag_aux and _safe_value(onediag_aux):
        datafile_lines.append(f"ONEDIAG_AUX:{onediag_aux}")

    if port:
        datafile_lines.append(f"PORT:{port}")
    if test_bay_location and _safe_value(test_bay_location):
        datafile_lines.append(f"TEST_BAY_LOCATION:{test_bay_location}")

    runnable = proc_ok and len(reasons) == 0
    command_preview = ""
    datafile_path = ""
    if runnable:
        datafile_path = f"{REPLAY_DATACENTER_CMD}.datafile"
        command_preview = (
            f"{REPLAY_DATACENTER_CMD} --process={process} --factory={factory_code} --datafile={datafile_path}"
        )

    return {
        "runnable": runnable,
        "reasons": reasons,
        "selectedRun": selected,
        "resolvedProcess": process,
        "resolvedFactoryCode": factory_code,
        "resolvedSku": sku_val,
        "tcsMeta": {
            "test_server_ips": test_server_ips,
            "machine_tags": machine_tags,
            "uut_machine_name": uut_machine_name,
        },
        "resolvedExecutionProfile": {
            "datacenter_cmd": REPLAY_DATACENTER_CMD,
            "bundle_paths": bundle_paths,
            "test_bay_location": test_bay_location,
            "port": port,
        },
        "redactedMappedFields": redacted_fields,
        "datafilePreview": "\n".join(datafile_lines),
        "commandPreview": command_preview,
    }

