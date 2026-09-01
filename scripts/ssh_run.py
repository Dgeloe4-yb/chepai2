#!/usr/bin/env python3
"""Run remote commands via SSH (reads deploy.env.local). Usage: python ssh_run.py board|server 'cmd'"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for name in ("deploy.env.local", "deploy.env"):
        p = ROOT / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
        break
    return env


def connect(target: str):
    import paramiko

    cfg = load_env()
    if target == "board":
        hosts = [cfg.get("BOARD_HOST", "192.168.1.56")]
        fallback = cfg.get("CHEPAI_IPC_HOST_FALLBACK") or cfg.get("BOARD_HOST_FALLBACK")
        if fallback:
            hosts.append(fallback)
        if "192.168.10.100" not in hosts:
            hosts.append("192.168.10.100")
        port = int(cfg.get("BOARD_PORT", "22"))
        user = cfg.get("BOARD_USER", "root")
        password = cfg.get("BOARD_PASSWORD", "")
    else:
        hosts = [cfg.get("DEPLOY_HOST", "38.207.179.218")]
        port = int(cfg.get("DEPLOY_PORT", "57777"))
        user = cfg.get("DEPLOY_USER", "root")
        password = cfg.get("DEPLOY_PASSWORD", "")

    if not password:
        raise SystemExit(f"Missing password for {target} in deploy.env.local")

    last_err: Exception | None = None
    tried: list[str] = []
    for host in hosts:
        if not host or host in tried:
            continue
        tried.append(host)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(host, port=port, username=user, password=password, timeout=20)
            return client
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            try:
                client.close()
            except Exception:
                pass
    raise SystemExit(f"SSH failed for {target} hosts={tried}: {last_err}")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    target, cmd = sys.argv[1], sys.argv[2]
    client = connect(target)
    try:
        stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        code = stdout.channel.recv_exit_status()
        if out:
            print(out, end="" if out.endswith("\n") else "\n")
        if err:
            print(err, file=sys.stderr, end="" if err.endswith("\n") else "\n")
        sys.exit(code)
    finally:
        client.close()


if __name__ == "__main__":
    main()
