"""Shared SSH defaults for chepai IPC tooling.

Prefer hostname; IP is fallback when mDNS/hosts unavailable.
"""
from __future__ import annotations

import os
from typing import Iterable

import paramiko

# Prefer stable name; IP may change via DHCP.
HOST = os.environ.get("CHEPAI_IPC_HOST", "chepai-rk3588")
HOST_FALLBACKS: tuple[str, ...] = tuple(
    h
    for h in (
        os.environ.get("CHEPAI_IPC_HOST_FALLBACK", "chepai-rk3588.local"),
        "192.168.10.100",
    )
    if h
)
USER = os.environ.get("CHEPAI_IPC_USER", "admin")
PASSWORD = os.environ.get("CHEPAI_IPC_PASSWORD", "admin")
SUDO = os.environ.get("CHEPAI_IPC_SUDO", PASSWORD)
CONDA_PY = os.environ.get(
    "CHEPAI_IPC_PYTHON",
    "/home/admin/miniconda3/envs/rknn/bin/python",
)
REMOTE_ROOT = "/opt/chepai-edge"
HOSTNAME = "chepai-rk3588"


def connect(hosts: Iterable[str] | None = None, timeout: int = 12) -> tuple[paramiko.SSHClient, str]:
    """Connect trying hostname first, then fallbacks. Returns (client, host_used)."""
    tried: list[str] = []
    last_err: Exception | None = None
    for host in list(hosts or (HOST, *HOST_FALLBACKS)):
        if not host or host in tried:
            continue
        tried.append(host)
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(
                host,
                username=USER,
                password=PASSWORD,
                timeout=timeout,
                banner_timeout=timeout,
                auth_timeout=timeout,
            )
            return c, host
        except Exception as exc:  # noqa: BLE001 — try next host
            last_err = exc
            try:
                c.close()
            except Exception:
                pass
    raise ConnectionError(f"SSH failed for {tried}: {last_err}")


def sudo_bash(c: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    wrapped = cmd if USER == "root" else f"echo {SUDO} | sudo -S bash -lc {cmd!r}"
    _, out, err = c.exec_command(wrapped, timeout=timeout)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    code = out.channel.recv_exit_status()
    return code, o, e
