# -*- coding: utf-8 -*-
"""SSH helpers for Crabber offline replay datafile push and console transcript / verdict."""

from __future__ import annotations

import posixpath
import re
import shlex
import time
from typing import Any, Dict, List, Optional, Tuple

import paramiko

from config.debug_config import (
    REPLAY_CLEANUP_CONSOLE_MAX_BYTES,
    REPLAY_CONSOLE_LOG_DIR,
    REPLAY_DATAFILE_DIR,
    REPLAY_EXECUTION_HOST,
    REPLAY_LOG_PARSE_MAX_BYTES,
    REPLAY_LOG_TAIL_MAX_LINES,
    REPLAY_SSH_PASSWORD,
    REPLAY_SSH_USER,
    REPLAY_STATUS_SSH_TIMEOUT_SEC,
    SSH_DHCP_HOST,
    SSH_DHCP_PASSWORD,
    SSH_DHCP_USER,
)
from config.site_defaults import get_default

_RE_N_MARKER = re.compile(r"\{\{N:(PASS|FAIL)\}\}")
_RE_RECIPE_STATUS = re.compile(r"^\s*Recipe Status\s*:\s*(PASS|FAIL)\s*$", re.MULTILINE | re.IGNORECASE)
_RE_TEST_ERROR_MSG = re.compile(r"^\s*Test Error Msg\s*:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)


def _resolve_execution_host(host_override: str = "") -> str:
    return (host_override or REPLAY_EXECUTION_HOST or get_default("ETF_SSH_HOST") or SSH_DHCP_HOST or "").strip()


def _resolve_credentials() -> Tuple[str, str]:
    user = (REPLAY_SSH_USER or SSH_DHCP_USER or "").strip()
    pw = (REPLAY_SSH_PASSWORD or SSH_DHCP_PASSWORD or "").strip()
    return user, pw


def sanitize_replay_path_component(s: str) -> str:
    """Allow only safe filename/path segment characters for remote log names."""
    return "".join(c for c in (s or "") if c.isalnum() or c in "_-")


def build_remote_replay_log_paths(
    sn: str,
    node_log_id: str,
    replay_run_id: str,
    *,
    console_dir: str = "",
    exit_dir: str = "",
) -> Tuple[str, str]:
    """Return (remote_console_log_path, remote_exit_code_path)."""
    base_console = (console_dir or REPLAY_CONSOLE_LOG_DIR or "/tmp/replay_console_logs").strip()
    base_exit = (exit_dir or base_console).strip()
    safe_sn = sanitize_replay_path_component(sn) or "sn"
    safe_node = sanitize_replay_path_component(node_log_id) or "node"
    safe_run = sanitize_replay_path_component(replay_run_id) or "run"
    name = f"console_{safe_sn}_{safe_node}_{safe_run}.log"
    exit_name = f"exit_{safe_sn}_{safe_node}_{safe_run}.txt"
    return posixpath.join(base_console, name), posixpath.join(base_exit, exit_name)


def build_wrapped_replay_command(inner_command: str, remote_console_log: str, remote_exit_sidecar: str) -> str:
    """
    Wrap inner replay command so stdout+stderr tee to remote log and real exit code is preserved.
    inner_command must already be a valid bash command line (e.g. built with shlex.quote per arg).
    """
    inner = (inner_command or "").strip()
    if not inner:
        return ""
    log_q = shlex.quote(remote_console_log)
    exit_q = shlex.quote(remote_exit_sidecar)
    # Single bash -lc script: pipefail + tee + PIPESTATUS + sidecar
    script = (
        f"set -o pipefail; mkdir -p $(dirname {log_q}) $(dirname {exit_q}); "
        f"{inner} 2>&1 | tee -a {log_q}; rc=${{PIPESTATUS[0]}}; echo $rc > {exit_q}; exit $rc"
    )
    return f"bash -lc {shlex.quote(script)}"


def push_datafile_text(filename: str, datafile_text: str, host_override: str = "") -> Tuple[str, str]:
    """Push datafile to replay execution host. Returns (remote_path, error)."""
    host = _resolve_execution_host(host_override=host_override)
    if not host:
        return "", "execution host not configured"
    user, password = _resolve_credentials()
    if not user or not password:
        return "", "replay SSH credentials missing"
    remote_dir = (REPLAY_DATAFILE_DIR or "/tmp/replay_datafiles").strip()
    remote_path = posixpath.join(remote_dir, filename)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=host, username=user, password=password, timeout=10, banner_timeout=10)
        sftp = client.open_sftp()
        try:
            try:
                sftp.stat(remote_dir)
            except Exception:
                sftp.mkdir(remote_dir)
            with sftp.file(remote_path, "w") as f:
                f.write(datafile_text)
            return remote_path, ""
        finally:
            try:
                sftp.close()
            except Exception:
                pass
    except Exception as e:
        return "", str(e)
    finally:
        try:
            client.close()
        except Exception:
            pass


def _sftp_connect(host_override: str) -> Tuple[Optional[paramiko.SSHClient], str]:
    host = _resolve_execution_host(host_override=host_override)
    if not host:
        return None, "execution host not configured"
    user, password = _resolve_credentials()
    if not user or not password:
        return None, "replay SSH credentials missing"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            username=user,
            password=password,
            timeout=REPLAY_STATUS_SSH_TIMEOUT_SEC,
            banner_timeout=REPLAY_STATUS_SSH_TIMEOUT_SEC,
        )
        return client, ""
    except Exception as e:
        try:
            client.close()
        except Exception:
            pass
        return None, str(e)


def remote_file_exists(host_override: str, remote_path: str) -> Tuple[bool, Optional[str]]:
    client, err = _sftp_connect(host_override)
    if err or not client:
        return False, err
    try:
        sftp = client.open_sftp()
        try:
            sftp.stat(remote_path)
            return True, None
        except Exception:
            return False, None
        finally:
            try:
                sftp.close()
            except Exception:
                pass
    finally:
        try:
            client.close()
        except Exception:
            pass


def read_remote_file_tail(
    host_override: str,
    remote_path: str,
    *,
    max_bytes: int = 0,
    max_lines: int = 0,
) -> Tuple[str, Optional[str]]:
    """Read tail of remote file (bounded). Returns (text, error)."""
    mb = max_bytes or REPLAY_LOG_PARSE_MAX_BYTES
    ml = max_lines or REPLAY_LOG_TAIL_MAX_LINES
    client, err = _sftp_connect(host_override)
    if err or not client:
        return "", err or "ssh connect failed"
    try:
        sftp = client.open_sftp()
        try:
            try:
                st = sftp.stat(remote_path)
            except Exception as e:
                return "", f"stat failed: {e}"
            size = int(getattr(st, "st_size", 0) or 0)
            to_read = min(size, mb) if mb > 0 else size
            start = max(0, size - to_read)
            with sftp.file(remote_path, "r") as f:
                if start > 0:
                    try:
                        f.seek(start)
                    except Exception:
                        pass
                raw = f.read()
            text = (raw or b"").decode("utf-8", errors="replace")
            if ml > 0 and text:
                lines = text.splitlines()
                if len(lines) > ml:
                    text = "\n".join(lines[-ml:])
            return text, None
        finally:
            try:
                sftp.close()
            except Exception:
                pass
    except Exception as e:
        return "", str(e)
    finally:
        try:
            client.close()
        except Exception:
            pass


def read_remote_exit_code(host_override: str, remote_path: str) -> Tuple[Optional[int], Optional[str]]:
    """Read integer exit code from sidecar file. Returns (code or None, error)."""
    text, err = read_remote_file_tail(
        host_override,
        remote_path,
        max_bytes=64,
        max_lines=5,
    )
    if err:
        return None, err
    s = (text or "").strip()
    if not s:
        return None, None
    try:
        return int(s.split()[0]), None
    except (ValueError, IndexError):
        return None, "invalid exit sidecar content"


def extract_test_error_msg(transcript: str) -> str:
    """Last Test Error Msg line value (trimmed)."""
    if not transcript:
        return ""
    matches = list(_RE_TEST_ERROR_MSG.finditer(transcript))
    if not matches:
        return ""
    return (matches[-1].group(1) or "").strip()


def parse_replay_transcript(transcript: str) -> Dict[str, Any]:
    """
    Derive verdict from bounded transcript tail.
    Precedence: last {{N:FAIL}}/{{N:PASS}}, then last Recipe Status, then exit code handled by caller.
    """
    t = transcript or ""
    err_msg = extract_test_error_msg(t)

    n_matches = list(_RE_N_MARKER.finditer(t))
    if n_matches:
        last = n_matches[-1].group(1).upper()
        if last == "FAIL":
            return {
                "verdict": "fail",
                "status_source": "n_marker",
                "error_summary": err_msg or "FAIL",
            }
        return {
            "verdict": "pass",
            "status_source": "n_marker",
            "error_summary": err_msg or "",
        }

    rs = list(_RE_RECIPE_STATUS.finditer(t))
    if rs:
        last = rs[-1].group(1).upper()
        if last == "FAIL":
            return {
                "verdict": "fail",
                "status_source": "recipe_status",
                "error_summary": err_msg or "Recipe Status FAIL",
            }
        return {
            "verdict": "pass",
            "status_source": "recipe_status",
            "error_summary": err_msg or "",
        }

    return {
        "verdict": "unknown",
        "status_source": "none",
        "error_summary": err_msg or "",
    }


_RE_LOGS_AT = re.compile(r"Logs at\s+(\S+)", re.IGNORECASE)
_RE_LOG_DIRECTORY = re.compile(r"^\s*Log\s+Directory\s*:\s*(\S+)", re.MULTILINE | re.IGNORECASE)
_RE_BASE_DIR_GV = re.compile(r"^\s*BASE_DIR\s*=\s*(\S+)\s*$", re.MULTILINE)


def bundle_root_from_script_path(script_path: str) -> str:
    """Directory containing run_datacenter.sh (BASE_DIR for Nautilus relative logs)."""
    sp = (script_path or "").strip()
    if not sp:
        return ""
    return posixpath.normpath(posixpath.dirname(sp))


def parse_logs_at_relative_path(console_text: str) -> Optional[str]:
    """Return relative path after 'Logs at' (e.g. logs/IGSJ_NA_...), last match wins."""
    if not (console_text or "").strip():
        return None
    matches = list(_RE_LOGS_AT.finditer(console_text))
    if not matches:
        return None
    raw = matches[-1].group(1).strip()
    # Drop trailing punctuation sometimes copied from log lines
    raw = raw.rstrip(").,;:")
    return raw


def parse_log_directory_relative_path(console_text: str) -> Optional[str]:
    """Nautilus prints 'Log Directory   : logs/...' — same relative form as 'Logs at'. Last match wins."""
    if not (console_text or "").strip():
        return None
    matches = list(_RE_LOG_DIRECTORY.finditer(console_text))
    if not matches:
        return None
    raw = matches[-1].group(1).strip().rstrip(").,;:")
    return raw if raw else None


def parse_nautilus_logs_relative_path(console_text: str) -> Optional[str]:
    """Prefer 'Logs at', else 'Log Directory :' from the replay console transcript."""
    return parse_logs_at_relative_path(console_text) or parse_log_directory_relative_path(console_text)


def parse_base_dir_from_console(console_text: str) -> Optional[str]:
    """Last 'BASE_DIR = /abs/path' from GV dump (printed early in replay console)."""
    if not (console_text or "").strip():
        return None
    matches = list(_RE_BASE_DIR_GV.finditer(console_text))
    if not matches:
        return None
    return matches[-1].group(1).strip().rstrip(").,;:") or None


def _paths_same_bundle_tree(manifest_root: str, console_base_dir: str) -> bool:
    """True if paths are equal or one is a strict subpath of the other (same install tree)."""
    a = posixpath.normpath((manifest_root or "").strip())
    b = posixpath.normpath((console_base_dir or "").strip())
    if not a or not b:
        return False
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def resolve_effective_nautilus_bundle_root(console_text: str, manifest_bundle_root: str) -> Tuple[str, str]:
    """
    Nautilus uses BASE_DIR from its own environment; prefer that from the replay console when safe.

    Returns (effective_root, note). Falls back to manifest bundle_root when console BASE_DIR is missing
    or does not sit in the same path tree as manifest (avoids trusting forged paths outside the bundle).
    """
    br = posixpath.normpath((manifest_bundle_root or "").strip().rstrip("/"))
    parsed = parse_base_dir_from_console(console_text)
    if not parsed:
        return br, ""
    pb = posixpath.normpath(parsed.strip())
    if ".." in pb.split("/"):
        return br, "BASE_DIR in console rejected (..)"
    if not pb.startswith("/"):
        return br, "BASE_DIR in console rejected (not absolute)"
    if not br:
        return pb, "using BASE_DIR from replay console"
    if not _paths_same_bundle_tree(br, pb):
        return br, "BASE_DIR in console ignored (path tree differs from manifest bundle_root)"
    return pb, "using BASE_DIR from replay console"


def resolve_nautilus_parent_and_run_name(bundle_root: str, relative: str) -> Optional[Tuple[str, str]]:
    """
    Parse path under bundle_root: logs/.../RUN_NAME -> parent = join(bundle_root, logs, ...), run_name = basename.
    Accepts ./logs/... Rejects absolute paths and '..'. Rejects path traversal.
    """
    br = posixpath.normpath((bundle_root or "").rstrip("/"))
    if not br:
        return None
    rel = (relative or "").strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    if not rel or rel.startswith("/"):
        return None
    if (len(rel) >= 2 and rel[0] in "\"'" and rel[-1] == rel[0]):
        rel = rel[1:-1].strip()
    parts = [p for p in rel.split("/") if p and p != "."]
    if ".." in parts:
        return None
    if len(parts) >= 2 and parts[0].lower() == "logs":
        parent = posixpath.join(br, *parts[:-1])
        run_name = parts[-1]
        return parent, run_name
    return None


def read_console_snapshot_and_parse_text(
    host_override: str,
    remote_path: str,
    *,
    max_bytes: int = 0,
) -> Tuple[str, str, bool, Optional[str]]:
    """
    Read remote console for cleanup: (manifest_snapshot, parse_text, truncated, error).

    When the file is larger than max_bytes, only the head is read into the snapshot budget, but
    the tail is also read and concatenated into parse_text so a late 'Logs at ...' line is not missed.
    """
    cap = max_bytes or REPLAY_CLEANUP_CONSOLE_MAX_BYTES
    head, truncated, err = read_remote_file_capped_from_start(host_override, remote_path, max_bytes=cap)
    if err:
        return "", "", False, err
    if not truncated:
        return head, head, False, None
    # max_lines=0 is interpreted as default tail line cap in read_remote_file_tail; use a huge cap
    # so we only bound by max_bytes (late "Logs at" must stay inside this window).
    tail, tail_err = read_remote_file_tail(
        host_override,
        remote_path,
        max_bytes=cap,
        max_lines=10_000_000,
    )
    if tail_err or not (tail or "").strip():
        return head, head, True, None
    sep = "\n--- … (middle of console omitted) … ---\n"
    manifest = (head or "") + sep + (tail or "")
    parse_text = (head or "") + "\n" + (tail or "")
    return manifest, parse_text, True, None


def _is_under_bundle_logs(bundle_root: str, target: str) -> bool:
    br = posixpath.normpath(bundle_root)
    logs_root = posixpath.normpath(posixpath.join(br, "logs"))
    tt = posixpath.normpath(target)
    return tt == logs_root or tt.startswith(logs_root + "/")


def read_remote_file_capped_from_start(
    host_override: str,
    remote_path: str,
    *,
    max_bytes: int = 0,
) -> Tuple[str, bool, Optional[str]]:
    """Read from start of file up to max_bytes. Returns (text, truncated, error)."""
    cap = max_bytes or REPLAY_CLEANUP_CONSOLE_MAX_BYTES
    client, err = _sftp_connect(host_override)
    if err or not client:
        return "", False, err or "ssh connect failed"
    try:
        sftp = client.open_sftp()
        try:
            try:
                st = sftp.stat(remote_path)
            except Exception as e:
                return "", False, f"stat failed: {e}"
            size = int(getattr(st, "st_size", 0) or 0)
            to_read = min(size, cap) if cap > 0 else size
            truncated = size > to_read
            with sftp.file(remote_path, "r") as f:
                raw = f.read(to_read)
            text = (raw or b"").decode("utf-8", errors="replace")
            return text, truncated, None
        finally:
            try:
                sftp.close()
            except Exception:
                pass
    except Exception as e:
        return "", False, str(e)
    finally:
        try:
            client.close()
        except Exception:
            pass


def remove_remote_file(host_override: str, remote_path: str) -> Optional[str]:
    """Unlink one file. Returns error string or None."""
    client, err = _sftp_connect(host_override)
    if err or not client:
        return err or "ssh connect failed"
    try:
        sftp = client.open_sftp()
        try:
            try:
                sftp.remove(remote_path)
            except Exception as e:
                return str(e)
            return None
        finally:
            try:
                sftp.close()
            except Exception:
                pass
    finally:
        try:
            client.close()
        except Exception:
            pass


def _ssh_rm_rf_path(host_override: str, path: str) -> Optional[str]:
    """Run rm -rf on one path (caller must validate). Returns error or None."""
    client, err = _sftp_connect(host_override)
    if err or not client:
        return err or "ssh connect failed"
    try:
        cmd = f"rm -rf {shlex.quote(path)}"
        _stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
        code = stdout.channel.recv_exit_status()
        if code != 0:
            err_b = stderr.read() or b""
            return (err_b.decode("utf-8", errors="replace") or f"exit {code}")[:300]
        return None
    except Exception as e:
        return str(e)
    finally:
        try:
            client.close()
        except Exception:
            pass


def cleanup_nautilus_run_artifacts(host_override: str, bundle_root: str, console_text: str) -> Tuple[List[str], str]:
    """
    Delete Nautilus run folder/file and matching .zip under BASE_DIR/logs by parsing the replay console.

    Uses manifest bundle_root for validation; effective directory is BASE_DIR from console when it matches
    the same bundle path tree (see resolve_effective_nautilus_bundle_root).
    Returns (deleted_paths, note).
    """
    if not (bundle_root or "").strip():
        return [], "no bundle_root (skipped)"
    rel = parse_nautilus_logs_relative_path(console_text)
    if not rel:
        return [], "no Logs at / Log Directory line in console (skipped)"
    effective_root, root_note = resolve_effective_nautilus_bundle_root(console_text, bundle_root)
    if not effective_root:
        return [], "no effective bundle root (skipped)"
    pr = resolve_nautilus_parent_and_run_name(effective_root, rel)
    if not pr:
        return [], "could not resolve Nautilus path from logs line (skipped)"
    parent, run_name = pr
    er = posixpath.normpath(effective_root)
    pn = posixpath.normpath(parent)
    if pn != er and not pn.startswith(er + "/"):
        return [], "resolved parent outside effective bundle root (skipped)"

    deleted: List[str] = []

    def _run_name_variants(name: str) -> List[str]:
        out = [name]
        markers = ("_T_", "_F_", "_P_")
        hit = ""
        for mk in markers:
            if mk in name:
                hit = mk
                break
        if not hit:
            return out
        for mk in markers:
            if mk == hit:
                continue
            out.append(name.replace(hit, mk, 1))
        return out

    targets: List[str] = []
    for rn in _run_name_variants(run_name):
        targets.append(posixpath.join(parent, rn))
        targets.append(posixpath.join(parent, rn + ".zip"))
    # keep order, remove duplicates
    targets = list(dict.fromkeys(targets))
    note_suffix = ("; " + root_note) if root_note else ""
    for full in targets:
        if not _is_under_bundle_logs(effective_root, full):
            continue
        exists, _ = remote_file_exists(host_override, full)
        if not exists:
            continue
        err = _ssh_rm_rf_path(host_override, full)
        if err is None:
            deleted.append(full)
    if deleted:
        return deleted, root_note.strip()
    return [], ("Nautilus artifacts not found or already removed (ok)" + note_suffix).strip()


def remove_replay_three_files(
    host_override: str,
    datafile: str,
    console_log: str,
    exit_sidecar: str,
) -> Tuple[List[str], List[str]]:
    """Best-effort remove three replay files. Returns (removed, errors)."""
    removed: List[str] = []
    errors: List[str] = []
    for p in (datafile, console_log, exit_sidecar):
        pt = (p or "").strip()
        if not pt:
            continue
        err = remove_remote_file(host_override, pt)
        if err is None:
            removed.append(pt)
            continue
        err2 = _ssh_rm_rf_path(host_override, pt)
        if err2 is None:
            removed.append(pt)
        else:
            errors.append(f"{pt}: {err}")
    return removed, errors


def resolve_datacenter_script_path(
    *,
    host_override: str = "",
    bundle_main: str = "",
    bundle_aux: str = "",
    cmd_name: str = "run_datacenter.sh",
) -> Tuple[str, str]:
    """Probe execution host for datacenter script path."""
    host = _resolve_execution_host(host_override=host_override)
    if not host:
        return "", "execution host not configured"
    user, password = _resolve_credentials()
    if not user or not password:
        return "", "replay SSH credentials missing"
    main_s = str(bundle_main or "").strip()
    aux_s = str(bundle_aux or "").strip()
    cands = []
    if main_s:
        cands.append(posixpath.join(posixpath.dirname(main_s), cmd_name))
        cands.append(posixpath.join(main_s, cmd_name))
    if aux_s:
        cands.append(posixpath.join(posixpath.dirname(aux_s), cmd_name))
        cands.append(posixpath.join(aux_s, cmd_name))
    cands.extend(
        [
            f"/app/cache/l10_inspect/{cmd_name}",
            f"/app/cache/l10_inspect/bundle_*/{cmd_name}",
            f"/root/nvidia_diag/**/{cmd_name}",
        ]
    )
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=host, username=user, password=password, timeout=10, banner_timeout=10)
        sftp = client.open_sftp()
        try:
            for p in cands[:4]:
                try:
                    sftp.stat(p)
                    return p, ""
                except Exception:
                    continue
        finally:
            try:
                sftp.close()
            except Exception:
                pass
        probe = (
            f"bash -lc \"ls -1 /app/cache/l10_inspect/bundle_*/{cmd_name} /root/nvidia_diag/**/{cmd_name} "
            f"2>/dev/null | head -n 1\""
        )
        _, stdout, _ = client.exec_command(probe, timeout=12)
        out = (stdout.read() or b"").decode("utf-8", errors="replace").strip()
        if out:
            return out, ""
        return "", "run_datacenter.sh not found on execution host"
    except Exception as e:
        return "", str(e)
    finally:
        try:
            client.close()
        except Exception:
            pass
