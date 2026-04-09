# -*- coding: utf-8 -*-
"""SSH helpers for Crabber offline replay datafile push and console transcript / verdict."""

from __future__ import annotations

import posixpath
import re
import shlex
import time
from typing import Any, Dict, Optional, Tuple

import paramiko

from config.debug_config import (
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
