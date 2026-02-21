#!/usr/bin/env python3
"""Upload scan_tray_bmc_mpi_new.sh to all DHCP servers (etf, room6 x3, room7, room8)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko

from config.etf_config import ROOMS


def _targets_from_rooms():
    """Yield (room, host, user, pass, remote_path) for each DHCP server."""
    for room, cfg in ROOMS.items():
        user = cfg.get("ssh_user", "root")
        password = cfg.get("ssh_pass", "root")
        remote_path = cfg.get("script_path", "/root/TIN/scan_tray_bmc_mpi_new.sh")

        hosts = cfg.get("ssh_hosts")
        if hosts:
            for host in hosts:
                yield room, host, user, password, remote_path
        elif cfg.get("ssh_host"):
            yield room, cfg["ssh_host"], user, password, remote_path


def upload_to_host(room: str, host: str, user: str, password: str, remote_path: str, content: str) -> bool:
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username=user, password=password, timeout=15)

        remote_dir = os.path.dirname(remote_path)
        client.exec_command(f"mkdir -p {remote_dir}")

        # Backup existing file before overwrite
        backup_path = remote_path + ".bak"
        stdin, stdout, stderr = client.exec_command(f"cp -f {remote_path} {backup_path} 2>/dev/null || true")
        stdout.channel.recv_exit_status()

        sftp = client.open_sftp()
        with sftp.open(remote_path, "w") as f:
            f.write(content)
        sftp.close()
        client.exec_command(f"chmod +x {remote_path}")
        client.close()
        return True
    except Exception as e:
        print(f" ERROR: {e}")
        return False


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(script_dir, "scan_tray_bmc_mpi_new.sh")
    with open(local_path, "r", encoding="utf-8") as f:
        content = f.read()

    ok = 0
    failed = []
    for room, host, user, password, remote_path in _targets_from_rooms():
        print(f"{room} ({host}): ", end="")
        if upload_to_host(room, host, user, password, remote_path, content):
            print(f"OK -> {remote_path}")
            ok += 1
        else:
            print("FAILED")
            failed.append(f"{room} ({host})")

    print(f"Done. Uploaded to {ok} DHCP server(s)." + (f" Failed: {', '.join(failed)}" if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
