# -*- coding: utf-8 -*-
"""ETF Status Flask blueprint: /etf page, /api/etf/data, scan, reset, remark."""

import csv
import io
import json
import os
import threading
from datetime import datetime

import paramiko
import requests

from config.app_config import ANALYTICS_CACHE_DIR
from sfc import client as sfc_client
from sfc import parser as sfc_parser
from config.etf_config import ROOMS, ETF_POLL_INTERVAL_SEC, SFC_LEVEL_GRADE, SFC_TRAY_STATUS_URL
from flask import Blueprint, jsonify, render_template, request

bp = Blueprint("etf", __name__, url_prefix="", template_folder="../templates")

_cache_lock = threading.Lock()
_cache: dict = {}
_remarks_path = os.path.join(ANALYTICS_CACHE_DIR, "etf_remarks.json")
_cache_dir = os.path.join(ANALYTICS_CACHE_DIR, "etf_cache")


def _load_remarks():
    if not os.path.isfile(_remarks_path):
        return {}
    try:
        with open(_remarks_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_remarks(data):
    os.makedirs(os.path.dirname(_remarks_path), exist_ok=True)
    with open(_remarks_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _get_room_config(room):
    r = ROOMS.get(room)
    if not r:
        return None
    return r


def _run_script_on_host(host, user, password, script_path, state_dir, reset_first=False):
    """Run scan script on a single host. Returns (raw_output, None) or (None, error_str)."""
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username=user, password=password, timeout=30)
        if reset_first:
            stdin, stdout, stderr = client.exec_command(
                f"rm -rf {state_dir}/* 2>/dev/null; mkdir -p {state_dir}",
                timeout=10,
            )
            stdout.channel.recv_exit_status()
        cmd = f"OUTPUT_RAW=1 SCAN_STATE_DIR={state_dir} bash {script_path} 2>/dev/null"
        stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
        out = stdout.read().decode("utf-8", errors="replace")
        client.close()
        return out, None
    except Exception as e:
        return None, str(e)


def _run_script(room, reset_first=False):
    """Run script for room. Returns (rows_with_ssh_host, None) or (None, error_str).
    For rooms with ssh_hosts, aggregates from all hosts. Each row gets ssh_host."""
    cfg = _get_room_config(room)
    if not cfg:
        return None, "unknown room"
    user = cfg["ssh_user"]
    password = cfg["ssh_pass"]
    script_path = cfg["script_path"]
    state_dir = cfg["state_dir"]

    hosts = cfg.get("ssh_hosts")
    if hosts:
        all_rows = []
        for host in hosts:
            out, err = _run_script_on_host(host, user, password, script_path, state_dir, reset_first=reset_first)
            if err:
                continue
            if not out:
                continue
            rows = _parse_tsv(out)
            for r in rows:
                r["ssh_host"] = host
            all_rows.extend(rows)
        return all_rows, None

    host = cfg.get("ssh_host")
    if not host:
        return None, "no ssh_host or ssh_hosts"
    out, err = _run_script_on_host(host, user, password, script_path, state_dir, reset_first=reset_first)
    if err:
        return None, err
    rows = _parse_tsv(out)
    for r in rows:
        r["ssh_host"] = host
    return rows, None


def _get_col(row, *keys):
    """Lay gia tri tu row theo nhieu ten cot (alias), tra ve chuoi rong neu thieu."""
    for k in keys:
        v = (row.get(k) or "").strip()
        if v:
            return v
    return ""


def _parse_tsv(raw):
    """Parse TSV output vao list of dicts.
    Script co the output thieu cot/du lieu - backend doc theo header, fill "" khi thieu.
    Header support: BMC_IP/IP, SN/CHASSIS_SERIAL, PN, BMC_MAC/BMC_FRU_MAC, SYS_IP/SMM_IP, SYS_MAC/SMM_FRU_MAC, FRU_STATUS."""
    rows = []
    if not raw or not raw.strip():
        return rows
    buf = io.StringIO(raw.strip())
    try:
        reader = csv.DictReader(buf, delimiter="\t", restval="")
        for r in reader:
            status = (r.get("FRU_STATUS") or r.get("status") or "").strip().upper()
            if status and status != "OK":
                continue
            rows.append({
                "bmc_ip": _get_col(r, "BMC_IP", "IP") or "-",
                "sn": _get_col(r, "SN", "CHASSIS_SERIAL"),
                "pn": _get_col(r, "PN", "CHASSIS_PN"),
                "bmc_mac": _get_col(r, "BMC_MAC", "BMC_FRU_MAC"),
                "sys_ip": _get_col(r, "SYS_IP", "SMM_IP") or "N/A",
                "sys_mac": _get_col(r, "SYS_MAC", "SMM_FRU_MAC"),
            })
    except Exception:
        pass
    return rows


def _merge_remarks(rows, room):
    remarks = _load_remarks()
    room_remarks = remarks.get(room) or {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        key = r.get("sn") or r.get("pn") or r.get("bmc_ip") or ""
        r["remark"] = room_remarks.get(key, "")
    return [r for r in (rows or []) if isinstance(r, dict)]


def _looks_like_mac(s):
    """BMC/SYS MAC should be XX:XX:XX:XX:XX:XX or NA."""
    if not s or str(s).strip() in ("", "NA", "N/A", "-"):
        return True
    return ":" in str(s) and len(str(s).replace(":", "")) == 12


def _looks_like_serial(s):
    """SN thường là 10-15 chữ số."""
    if not s or str(s).strip() in ("", "NA", "N/A", "-"):
        return False
    return str(s).replace("-", "").replace(".", "").isdigit() and 10 <= len(str(s)) <= 15


def _validate_cache_rows(rows):
    """Reject cache if bmc_mac contains SN-like values (sai vi tri)."""
    if not rows:
        return True
    bad = 0
    for r in rows:
        if not isinstance(r, dict):
            return False
        bmc = (r.get("bmc_mac") or "").strip()
        if bmc and bmc not in ("NA", "N/A") and _looks_like_serial(bmc) and not _looks_like_mac(bmc):
            bad += 1
    return bad == 0


def _load_room_cache(room):
    path = os.path.join(_cache_dir, f"{room}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
            rows = [r for r in (d.get("rows") or []) if isinstance(r, dict)]
            if not _validate_cache_rows(rows):
                try:
                    os.remove(path)
                except Exception:
                    pass
                return None
            return {"rows": rows, "last_updated": d.get("last_updated", "")}
    except Exception:
        return None


def _save_room_cache(room, rows, last_updated):
    os.makedirs(_cache_dir, exist_ok=True)
    path = os.path.join(_cache_dir, f"{room}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"rows": rows, "last_updated": last_updated}, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _background_scan_rooms():
    """Scan all rooms periodically and update disk cache."""
    while True:
        try:
            for room in ROOMS:
                rows, err = _run_script(room, reset_first=False)
                if not err and rows:
                    rows = _merge_remarks(rows, room)
                    if _validate_cache_rows(rows):
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        with _cache_lock:
                            _cache[room] = {"rows": rows, "last_updated": now}
                        _save_room_cache(room, rows, now)
        except Exception:
            pass
        threading.Event().wait(ETF_POLL_INTERVAL_SEC)


_background_started = False


def _ensure_background_poller():
    global _background_started
    if _background_started:
        return
    with _cache_lock:
        if _background_started:
            return
        t = threading.Thread(target=_background_scan_rooms, daemon=True)
        t.start()
        _background_started = True


@bp.route("/etf")
def etf_page():
    """Redirect to debug (ETF container is now embedded there)."""
    from flask import redirect
    return redirect("/debug", code=302)


def _maybe_start_background():
    try:
        _ensure_background_poller()
    except Exception:
        pass


@bp.route("/api/sfc/tray-status")
def api_sfc_tray_status():
    """Proxy SFC Test_Fixture_Status API; return sn_map for frontend merge. On SFC failure returns 200 with ok=False so UI still loads."""
    try:
        r = requests.post(
            SFC_TRAY_STATUS_URL,
            json={"Level_Grade": SFC_LEVEL_GRADE},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": str(e), "sn_map": {}})
    except (ValueError, TypeError) as e:
        return jsonify({"ok": False, "error": f"Invalid response: {e}", "sn_map": {}})

    raw_list = data.get("DATA") if isinstance(data, dict) else None
    if not isinstance(raw_list, list):
        return jsonify({"ok": True, "sn_map": {}})

    sn_map = {}
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        sn = (item.get("Serial_Number") or "").strip()
        if not sn:
            continue
        if sn not in sn_map:
            sn_map[sn] = {
                "fixture_no": (item.get("Fixture_No") or "").strip() or None,
                "slot_no": (item.get("Slot_No") or "").strip() or None,
                "status": (item.get("Status") or "").strip() or None,
                "last_end_time": (item.get("Last_End_Time") or "").strip() or None,
                "remark": (item.get("Remark") or "").strip() or None,
            }
    return jsonify({"ok": True, "sn_map": sn_map})


@bp.route("/api/sfc/assy-info", methods=["POST"])
def api_sfc_assy_info():
    """Fetch AssyInfo HTML for each SN, parse SEMI PN/SN for sys_mac and bmc_mac. Returns sn_map."""
    MAX_SNS = 50
    try:
        data = request.get_json() or {}
        sns = data.get("sns") or []
        if not isinstance(sns, list):
            sns = []
        sns = [str(s).strip() for s in sns[:MAX_SNS] if s]
    except Exception:
        sns = []
    sn_map = {}
    for sn in sns:
        if not sn:
            continue
        try:
            ok, html = sfc_client.request_assy_info(sn)
            if not ok or not html:
                continue
            parsed = sfc_parser.parse_assy_info_html(html)
            if parsed:
                sn_map[sn] = {
                    "sys_mac": parsed.get("sys_mac") or "",
                    "bmc_mac": parsed.get("bmc_mac") or "",
                    "all_keys": parsed.get("all_keys") or {},
                }
        except Exception:
            continue
    return jsonify({"ok": True, "sn_map": sn_map})


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@bp.route("/api/sfc/assy-info-raw", methods=["GET"])
def api_sfc_assy_info_raw():
    """Fetch AssyInfo HTML for one SN and save to project debug/ folder. For debugging wrong MAC data."""
    sn = (request.args.get("sn") or "").strip()
    if not sn:
        return jsonify({"ok": False, "error": "missing sn"}), 400
    try:
        ok, html = sfc_client.request_assy_info(sn)
        if not ok:
            return jsonify({"ok": False, "error": "fetch failed", "sn": sn}), 502
        debug_dir = os.path.join(_project_root(), "debug")
        os.makedirs(debug_dir, exist_ok=True)
        filename = f"assy_info_{sn}.html"
        filepath = os.path.join(debug_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        return jsonify({"ok": True, "sn": sn, "path": filepath, "filename": filename})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "sn": sn}), 500


@bp.route("/api/etf/data")
def api_etf_data():
    """Return cached rows for room. Load from disk cache first, run script if empty."""
    _maybe_start_background()
    room = (request.args.get("room") or "etf").strip().lower()
    if room not in ROOMS:
        return jsonify({"error": "unknown room", "rows": []}), 400
    with _cache_lock:
        entry = _cache.get(room)
        if not entry:
            entry = _load_room_cache(room)
            if entry:
                _cache[room] = entry
        if entry:
            rows = _merge_remarks(entry["rows"], room)
            return jsonify({
                "ok": True,
                "rows": rows,
                "last_updated": entry["last_updated"],
            })
    rows, err = _run_script(room, reset_first=False)
    if err:
        disk = _load_room_cache(room)
        if disk:
            rows = _merge_remarks(disk["rows"], room)
            return jsonify({"ok": True, "rows": rows, "last_updated": disk["last_updated"]})
        return jsonify({"ok": False, "error": err, "rows": []}), 502
    rows = _merge_remarks(rows or [], room)
    if not _validate_cache_rows(rows):
        return jsonify({
            "ok": False,
            "error": "Script output has wrong column mapping (SN in BMC_MAC). Run reset or update script on server.",
            "rows": [],
        }), 502
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _cache_lock:
        _cache[room] = {"rows": rows, "last_updated": now}
    _save_room_cache(room, rows, now)
    return jsonify({"ok": True, "rows": rows, "last_updated": now})


@bp.route("/api/etf/scan")
def api_etf_scan():
    """Run script on remote, parse TSV, update cache, return rows."""
    room = (request.args.get("room") or "etf").strip().lower()
    if room not in ROOMS:
        return jsonify({"error": "unknown room", "rows": []}), 400
    rows, err = _run_script(room, reset_first=False)
    if err:
        return jsonify({"ok": False, "error": err, "rows": []}), 502
    rows = _merge_remarks(rows or [], room)
    if not _validate_cache_rows(rows):
        return jsonify({
            "ok": False,
            "error": "Script output has wrong column mapping (SN in BMC_MAC). Run reset or update script on server.",
            "rows": [],
        }), 502
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _cache_lock:
        _cache[room] = {"rows": rows, "last_updated": now}
    _save_room_cache(room, rows, now)
    return jsonify({"ok": True, "rows": rows, "last_updated": now})


@bp.route("/api/etf/reset", methods=["POST"])
def api_etf_reset():
    """Clear backend cache + DHCP server cache, then run script."""
    room = request.args.get("room") or (request.json or {}).get("room") or "etf"
    if isinstance(room, str):
        room = room.strip().lower()
    else:
        room = "etf"
    if room not in ROOMS:
        return jsonify({"error": "unknown room", "rows": []}), 400
    # Xoa cache backend truoc
    with _cache_lock:
        _cache.pop(room, None)
    # Xoa cache DHCP + chay script
    rows, err = _run_script(room, reset_first=True)
    if err:
        return jsonify({"ok": False, "error": err, "rows": []}), 502
    rows = _merge_remarks(rows or [], room)
    if not _validate_cache_rows(rows):
        return jsonify({
            "ok": False,
            "error": "Script output has wrong column mapping (SN in BMC_MAC). Update script: python scripts/upload_scan_tray_v3.py",
            "rows": [],
        }), 502
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _cache_lock:
        _cache[room] = {"rows": rows, "last_updated": now}
    _save_room_cache(room, rows, now)
    return jsonify({"ok": True, "rows": rows, "last_updated": now})


def _row_matches_query(row, q):
    """Check if row matches search query (case-insensitive)."""
    if not isinstance(row, dict):
        return False
    if not q or not q.strip():
        return False
    ql = q.strip().lower()
    fields = [
        row.get("sn") or "",
        row.get("pn") or "",
        row.get("bmc_mac") or "",
        row.get("bmc_ip") or "",
        row.get("sys_ip") or "",
        row.get("sys_mac") or "",
    ]
    return any(ql in (str(f).lower()) for f in fields if f)


@bp.route("/api/etf/search")
def api_etf_search():
    """Search for SN/MAC/IP across all rooms. Returns matching rows with room and ssh_host."""
    _maybe_start_background()
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": True, "rows": []})
    results = []
    with _cache_lock:
        for room in ROOMS:
            entry = _cache.get(room) or _load_room_cache(room)
            if not entry:
                continue
            rows = _merge_remarks(entry["rows"], room)
            for r in rows:
                if _row_matches_query(r, q):
                    r_copy = dict(r)
                    r_copy["room"] = room
                    results.append(r_copy)
    return jsonify({"ok": True, "rows": results})


@bp.route("/api/etf/remark", methods=["POST"])
def api_etf_remark():
    """Store remark for room+SN. Body: {room, sn, remark}."""
    payload = request.json or {}
    room = (payload.get("room") or "etf").strip().lower()
    sn = (payload.get("sn") or "").strip()
    remark = (payload.get("remark") or "").strip()
    if room not in ROOMS:
        return jsonify({"error": "unknown room"}), 400
    if not sn:
        return jsonify({"error": "sn required"}), 400
    remarks = _load_remarks()
    if room not in remarks:
        remarks[room] = {}
    if remark:
        remarks[room][sn] = remark
    else:
        remarks[room].pop(sn, None)
    _save_remarks(remarks)
    return jsonify({"ok": True})
