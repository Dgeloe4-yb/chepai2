"""Sync local edge agent/shared + systemd to industrial PC; enable production on boot."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from _ipc_conn import CONDA_PY, HOST, REMOTE_ROOT, USER, connect, sudo_bash

ROOT = Path(__file__).resolve().parents[2]  # chepai2/
LOCAL_AGENT = ROOT / "edge" / "agent" / "chepai_edge"
LOCAL_SHARED = ROOT / "edge" / "shared"
LOCAL_SYSTEMD = ROOT / "edge" / "agent" / "systemd"
LOCAL_WEIGHTS = ROOT / "edge" / "poc" / "weights"
LOCAL_VOICE = ROOT / "edge" / "agent" / "voice"
WEIGHT_ASSETS = ("park_align.json",)
VOICE_WAVS = (
    "dual_slot.wav",
    "car_in_bus_slot.wav",
    "bad_park.wav",
    "mini_ad.wav",
    "non_sedan.wav",
    "oil_car.wav",
)

UPLOADS: list[tuple[Path, str]] = []

_SKIP_AGENT_PARTS = {"debug_web.py", "debug_static", "debug_log.py"}


def log(msg: str) -> None:
    print(msg, flush=True)


def collect() -> None:
    UPLOADS.clear()
    for p in LOCAL_AGENT.rglob("*"):
        if not p.is_file():
            continue
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        if any(part in _SKIP_AGENT_PARTS for part in p.parts):
            continue
        if p.name in _SKIP_AGENT_PARTS:
            continue
        rel = p.relative_to(LOCAL_AGENT).as_posix()
        UPLOADS.append((p, f"{REMOTE_ROOT}/edge/agent/chepai_edge/{rel}"))

    for p in LOCAL_SHARED.rglob("*"):
        if not p.is_file():
            continue
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        rel = p.relative_to(LOCAL_SHARED).as_posix()
        UPLOADS.append((p, f"{REMOTE_ROOT}/edge/shared/{rel}"))

    unit = LOCAL_SYSTEMD / "chepai-edge.service"
    if unit.is_file():
        UPLOADS.append((unit, f"{REMOTE_ROOT}/edge/agent/systemd/{unit.name}"))

    for name in WEIGHT_ASSETS:
        p = LOCAL_WEIGHTS / name
        if p.is_file():
            UPLOADS.append((p, f"{REMOTE_ROOT}/weights/{name}"))
        else:
            log(f"警告: 本地缺少权重附属文件 {p}，跳过")

    for name in VOICE_WAVS:
        p = LOCAL_VOICE / name
        if p.is_file():
            UPLOADS.append((p, f"{REMOTE_ROOT}/voice/{name}"))
        else:
            log(f"警告: 本地缺少语音 {p}，跳过")


def main() -> None:
    collect()
    log(f"[1/4] 待上传 {len(UPLOADS)} 个文件")
    log(f"[2/4] 正在连接 {HOST} …")
    try:
        c, used = connect()
    except Exception as exc:
        log(f"连接失败: {exc}")
        sys.exit(1)
    log(f"[2/4] 已连接 ({used})，开始上传 …")
    if USER != "root":
        sudo_bash(c, f"chown -R {USER}:{USER} {REMOTE_ROOT}", timeout=60)

    sftp = c.open_sftp()

    def ensure_dir(remote: str) -> None:
        parts = remote.strip("/").split("/")
        cur = ""
        for part in parts:
            cur += "/" + part
            try:
                sftp.stat(cur)
            except OSError:
                try:
                    sftp.mkdir(cur)
                except OSError:
                    pass

    for i, (local, remote) in enumerate(UPLOADS, 1):
        ensure_dir(os.path.dirname(remote))
        log(f"  [{i}/{len(UPLOADS)}] {local.name} -> {remote}")
        sftp.put(str(local), remote)
    sftp.close()

    log("[3/4] 上传完成，切换为生产自启 …")
    cmds = [
        f"mkdir -p {REMOTE_ROOT}/data {REMOTE_ROOT}/snapshots",
        f"chown -R chepai:chepai {REMOTE_ROOT}/edge {REMOTE_ROOT}/data {REMOTE_ROOT}/snapshots "
        f"{REMOTE_ROOT}/weights/park_align.json 2>/dev/null || true",
        f"ln -sfn {REMOTE_ROOT}/edge/shared {REMOTE_ROOT}/shared 2>/dev/null || true",
        "systemctl stop chepai-edge-debug.service 2>/dev/null || true",
        "systemctl disable chepai-edge-debug.service 2>/dev/null || true",
        "rm -f /etc/systemd/system/chepai-edge-debug.service "
        f"{REMOTE_ROOT}/edge/agent/systemd/chepai-edge-debug.service "
        f"{REMOTE_ROOT}/edge/agent/chepai_edge/debug_web.py",
        f"rm -rf {REMOTE_ROOT}/edge/agent/chepai_edge/debug_static",
        "systemctl unmask chepai-edge.service 2>/dev/null || true",
        f"cp -f {REMOTE_ROOT}/edge/agent/systemd/chepai-edge.service /etc/systemd/system/chepai-edge.service",
        f"sed -i 's|/opt/chepai-edge/venv/bin/python|{CONDA_PY}|g' /etc/systemd/system/chepai-edge.service",
        "systemctl daemon-reload",
        "systemctl enable --now chepai-edge.service",
        "systemctl restart chepai-edge.service",
        "sleep 3",
        "systemctl is-active chepai-edge.service",
        "systemctl is-enabled chepai-edge.service",
        "curl -sS -m 8 http://127.0.0.1:8765/api/state.json | head -c 500 || true",
    ]
    for cmd in cmds:
        log(f"  $ {cmd}")
        _code, o, e = sudo_bash(c, cmd, timeout=120)
        if o.strip():
            log(f"    {o.strip()}")
        if e.strip() and "password" not in e.lower() and "unable to resolve host" not in e.lower():
            log(f"    ERR: {e.strip()[:500]}")

    c.close()
    log(f"[4/4] 完成 — http://{used}:8765")


if __name__ == "__main__":
    main()
