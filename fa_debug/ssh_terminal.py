# -*- coding: utf-8 -*-
"""SSH terminal WebSocket handler: bridges browser xterm to SSH on DHCP server."""

import socket
import threading

import paramiko

from config.debug_config import (
    BMC_SSH_PASSWORD,
    BMC_SSH_USER,
    HOST_SSH_PASSWORD,
    HOST_SSH_USER,
    SSH_DHCP_HOST,
    SSH_DHCP_PASSWORD,
    SSH_DHCP_USER,
)
from config.etf_config import ROOMS


def _credentials_for_host(host):
    """Return (user, password) for host. Look up in ROOMS, else use SSH_DHCP_*."""
    if not host:
        return SSH_DHCP_USER, SSH_DHCP_PASSWORD
    host_s = str(host).strip()
    for room, cfg in ROOMS.items():
        h = cfg.get("ssh_host")
        if h and str(h).strip() == host_s:
            return cfg.get("ssh_user", "root"), cfg.get("ssh_pass", "root")
        for hh in (cfg.get("ssh_hosts") or []):
            if str(hh).strip() == host_s:
                return cfg.get("ssh_user", "root"), cfg.get("ssh_pass", "root")
    return SSH_DHCP_USER, SSH_DHCP_PASSWORD


def register_ssh_ws(sock):
    """Register the /ws/ssh WebSocket route."""

    @sock.route("/ws/ssh")
    def handle_ssh_ws(ws):
        client = None
        chan = None
        stop = threading.Event()
        password_sent = [False]
        inner_password = []

        def ssh_to_ws():
            try:
                if chan:
                    chan.settimeout(1.0)
                while not stop.is_set() and chan and not chan.exit_status_ready():
                    try:
                        data = chan.recv(4096)
                    except socket.timeout:
                        continue
                    except (EOFError, OSError, paramiko.SSHException):
                        break
                    if not data:
                        break
                    if inner_password and not password_sent[0]:
                        try:
                            buf = data.decode("utf-8", errors="replace").lower()
                            if "password" in buf or "passphrase" in buf:
                                chan.send((inner_password[0] + "\r\n").encode("utf-8"))
                                password_sent[0] = True
                        except Exception:
                            pass
                    try:
                        ws.send(data)
                    except Exception:
                        break
            except Exception:
                pass
            finally:
                stop.set()

        def ws_to_ssh():
            try:
                while not stop.is_set():
                    try:
                        data = ws.receive()
                    except Exception:
                        break
                    if not data:
                        break
                    payload = data.encode("utf-8") if isinstance(data, str) else data
                    if chan and chan.exit_status_ready() is False:
                        try:
                            chan.send(payload)
                        except Exception:
                            break
            except Exception:
                pass
            finally:
                stop.set()

        try:
            from flask import request
            ws_type = (request.args.get("type") or "").strip().lower()
            target = (request.args.get("target") or "").strip()
            jump_host = (request.args.get("jump_host") or "").strip()

            if ws_type == "bmc" and target and jump_host:
                host = jump_host
                user, password = _credentials_for_host(jump_host)
                inner_password.append(BMC_SSH_PASSWORD)
            elif ws_type == "host" and target and jump_host:
                host = jump_host
                user, password = _credentials_for_host(jump_host)
                inner_password.append(HOST_SSH_PASSWORD)
            elif ws_type == "bmc" and target:
                host = target
                user, password = BMC_SSH_USER, BMC_SSH_PASSWORD
            elif ws_type == "host" and target:
                host = target
                user, password = HOST_SSH_USER, HOST_SSH_PASSWORD
            else:
                host = (request.args.get("host") or "").strip() or SSH_DHCP_HOST
                user, password = _credentials_for_host(host)
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, username=user, password=password, timeout=15)
            transport = client.get_transport()
            if not transport:
                ws.send(b"SSH: no transport\r\n")
                return
            chan = transport.open_session()
            chan.get_pty()
            chan.invoke_shell()

            if ws_type == "bmc" and target and jump_host:
                clear_cmd = 'ssh-keygen -f ~/.ssh/known_hosts -R "' + target + '" 2>/dev/null; '
                chan.send((clear_cmd + "ssh -o StrictHostKeyChecking=no " + BMC_SSH_USER + "@" + target + "\r\n").encode("utf-8"))
            elif ws_type == "host" and target and jump_host:
                clear_cmd = 'ssh-keygen -f ~/.ssh/known_hosts -R "' + target + '" 2>/dev/null; '
                chan.send((clear_cmd + "ssh -o StrictHostKeyChecking=no " + HOST_SSH_USER + "@" + target + "\r\n").encode("utf-8"))

            t1 = threading.Thread(target=ssh_to_ws, daemon=True)
            t2 = threading.Thread(target=ws_to_ssh, daemon=True)
            t1.start()
            t2.start()
            stop.wait()

        except paramiko.AuthenticationException as e:
            try:
                ws.send(f"SSH auth failed: {e}\r\n".encode())
            except Exception:
                pass
        except paramiko.SSHException as e:
            try:
                ws.send(f"SSH error: {e}\r\n".encode())
            except Exception:
                pass
        except Exception as e:
            try:
                ws.send(f"SSH connect failed: {e}\r\n".encode())
            except Exception:
                pass
        finally:
            stop.set()
            if chan:
                try:
                    chan.close()
                except Exception:
                    pass
            if client:
                try:
                    client.close()
                except Exception:
                    pass
