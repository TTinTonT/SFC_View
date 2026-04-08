# -*- coding: utf-8 -*-
"""SSH helpers for Crabber offline replay datafile push."""

from __future__ import annotations

import posixpath
from typing import Tuple

import paramiko

from config.debug_config import (
    REPLAY_DATAFILE_DIR,
    REPLAY_EXECUTION_HOST,
    REPLAY_SSH_PASSWORD,
    REPLAY_SSH_USER,
    SSH_DHCP_HOST,
    SSH_DHCP_PASSWORD,
    SSH_DHCP_USER,
)
from config.site_defaults import get_default


def _resolve_execution_host(host_override: str = "") -> str:
    return (host_override or REPLAY_EXECUTION_HOST or get_default("ETF_SSH_HOST") or SSH_DHCP_HOST or "").strip()


def _resolve_credentials() -> Tuple[str, str]:
    user = (REPLAY_SSH_USER or SSH_DHCP_USER or "").strip()
    pw = (REPLAY_SSH_PASSWORD or SSH_DHCP_PASSWORD or "").strip()
    return user, pw


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
        # wildcard fallback
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

