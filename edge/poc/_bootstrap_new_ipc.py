"""Bootstrap chepai-edge on a fresh IPC. Does NOT touch bluetooth/boot/DTB."""
from __future__ import annotations

import base64
import os
import sys
import textwrap
from pathlib import Path

from _ipc_conn import CONDA_PY, HOSTNAME, REMOTE_ROOT, USER, connect, sudo_bash

ROOT = Path(__file__).resolve().parents[2]
LOCAL_AGENT = ROOT / "edge" / "agent" / "chepai_edge"
LOCAL_SHARED = ROOT / "edge" / "shared"
LOCAL_SYSTEMD = ROOT / "edge" / "agent" / "systemd"
LOCAL_WEIGHTS = ROOT / "edge" / "poc" / "weights"
LOCAL_RKNN = LOCAL_WEIGHTS / "rknn"
LOCAL_ONNX2RKNN = ROOT / "scripts" / "onnx2rknn_board.py"
LOCAL_TEST = ROOT / "edge" / "agent" / "scripts" / "test_rknn_board.py"

RKNN_WEIGHTS = ("yolov8n.rknn", "plate_color.rknn", "mini_ad.rknn")
WEIGHT_ASSETS = ("park_align.json",)
_SKIP_AGENT_PARTS = {"debug_web.py", "debug_static", "debug_log.py", "chepai-edge-debug.service"}


def log(msg: str) -> None:
    print(msg, flush=True)


def run(c, cmd: str, timeout: int = 600) -> tuple[int, str, str]:
    if "\n" in cmd:
        payload = base64.b64encode(cmd.encode("utf-8")).decode("ascii")
        code, o, e = sudo_bash(c, f"echo {payload} | base64 -d | bash", timeout)
        log("  $ <script>")
    else:
        log(f"  $ {cmd}")
        code, o, e = sudo_bash(c, cmd, timeout)
    if o.strip():
        log(textwrap.indent(o.rstrip(), "    "))
    if e.strip() and "password" not in e.lower() and "unable to resolve host" not in e.lower():
        log(textwrap.indent(f"stderr: {e.rstrip()[:1500]}", "    "))
    return code, o, e


def collect_uploads() -> list[tuple[Path, str]]:
    uploads: list[tuple[Path, str]] = []
    for p in LOCAL_AGENT.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        if any(part in _SKIP_AGENT_PARTS for part in p.parts) or p.name in _SKIP_AGENT_PARTS:
            continue
        uploads.append((p, f"{REMOTE_ROOT}/edge/agent/chepai_edge/{p.relative_to(LOCAL_AGENT).as_posix()}"))
    for p in LOCAL_SHARED.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        uploads.append((p, f"{REMOTE_ROOT}/edge/shared/{p.relative_to(LOCAL_SHARED).as_posix()}"))
    unit = LOCAL_SYSTEMD / "chepai-edge.service"
    if unit.is_file():
        uploads.append((unit, f"{REMOTE_ROOT}/edge/agent/systemd/{unit.name}"))
    for name in WEIGHT_ASSETS:
        p = LOCAL_WEIGHTS / name
        if p.is_file():
            uploads.append((p, f"{REMOTE_ROOT}/weights/{name}"))
    for name in RKNN_WEIGHTS:
        p = LOCAL_RKNN / name
        if p.is_file():
            uploads.append((p, f"{REMOTE_ROOT}/weights/{name}"))
    if LOCAL_ONNX2RKNN.is_file():
        uploads.append((LOCAL_ONNX2RKNN, f"{REMOTE_ROOT}/onnx2rknn_board.py"))
    if LOCAL_TEST.is_file():
        uploads.append((LOCAL_TEST, f"{REMOTE_ROOT}/test_rknn_board.py"))
    mini_onnx = LOCAL_WEIGHTS / "mini_ad.onnx"
    if mini_onnx.is_file() and not (LOCAL_RKNN / "mini_ad.rknn").is_file():
        uploads.append((mini_onnx, f"{REMOTE_ROOT}/weights/mini_ad.onnx"))
    return uploads


def ensure_remote_dir(sftp, remote: str) -> None:
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


def main() -> None:
    uploads = collect_uploads()
    log(f"全新机引导 → {REMOTE_ROOT}（不碰蓝牙）")
    try:
        c, used = connect()
    except Exception as exc:
        log(f"SSH 失败: {exc}")
        sys.exit(1)
    log(f"已连接 {used}")

    log("[1/5] 用户/目录 …")
    code, o, _ = run(
        c,
        f"""
set -e
export DEBIAN_FRONTEND=noninteractive
command -v ffmpeg >/dev/null && command -v curl >/dev/null || {{
  apt-get update -qq
  apt-get install -y -qq ffmpeg curl ca-certificates
}}
test -x {CONDA_PY} || {{ echo CONDA_RKNN_MISSING; exit 1; }}
id chepai >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin -d {REMOTE_ROOT} chepai
usermod -aG render,video,audio chepai 2>/dev/null || true
mkdir -p {REMOTE_ROOT}/weights {REMOTE_ROOT}/snapshots {REMOTE_ROOT}/voice
chown -R chepai:chepai {REMOTE_ROOT}
{CONDA_PY} -c 'import rknnlite.api, cv2, numpy; print("py ok")'
sudo -u chepai {CONDA_PY} -c 'import rknnlite.api; print("chepai ok")'
echo BOOTSTRAP_OK
""",
        900,
    )
    if code != 0 or "BOOTSTRAP_OK" not in o:
        raise SystemExit(f"初始化失败 code={code}")

    log(f"[2/5] 上传 {len(uploads)} 文件 …")
    run(c, f"chown -R {USER}:{USER} {REMOTE_ROOT}", 30)
    sftp = c.open_sftp()
    for i, (local, remote) in enumerate(uploads, 1):
        ensure_remote_dir(sftp, os.path.dirname(remote))
        log(f"  [{i}/{len(uploads)}] {local.name}")
        sftp.put(str(local), remote)
    sftp.close()

    log("[3/5] mini_ad.rknn …")
    _c, o, _ = run(c, f"test -f {REMOTE_ROOT}/weights/mini_ad.rknn && echo HAS || echo NEED", 20)
    if "NEED" in o:
        _c2, o2, _ = run(c, f"{CONDA_PY} -c 'import rknn.api' 2>/dev/null && echo CAN || echo NO", 30)
        if "CAN" in o2:
            run(
                c,
                f"{CONDA_PY} {REMOTE_ROOT}/onnx2rknn_board.py "
                f"{REMOTE_ROOT}/weights/mini_ad.onnx {REMOTE_ROOT}/weights/mini_ad.rknn 640",
                900,
            )

    log("[4/5] systemd …")
    for cmd in (
        f"chown -R chepai:chepai {REMOTE_ROOT}",
        f"ln -sfn {REMOTE_ROOT}/edge/shared {REMOTE_ROOT}/shared",
        f"printf '127.0.1.1\\t{HOSTNAME}\\n' >> /etc/hosts",
        f"hostnamectl set-hostname {HOSTNAME} || true",
        f"cp -f {REMOTE_ROOT}/edge/agent/systemd/chepai-edge.service /etc/systemd/system/chepai-edge.service",
        f"sed -i 's|/opt/chepai-edge/venv/bin/python|{CONDA_PY}|g' /etc/systemd/system/chepai-edge.service",
        "systemctl daemon-reload",
        "systemctl unmask chepai-edge.service 2>/dev/null || true",
        "systemctl enable --now chepai-edge.service",
        "sleep 4",
        "systemctl is-active chepai-edge.service",
        "systemctl is-enabled chepai-edge.service",
    ):
        run(c, cmd, 120)

    log("[5/5] 验证 …")
    for cmd in (
        f"ls -lh {REMOTE_ROOT}/weights/*.rknn 2>/dev/null || true",
        "journalctl -u chepai-edge.service -n 30 --no-pager",
        "curl -sS -m 8 http://127.0.0.1:8765/api/state.json | head -c 500 || true",
    ):
        run(c, cmd, 60)
    c.close()
    log(f"完成 — http://{used}:8765 / http://{HOSTNAME}.local:8765")


if __name__ == "__main__":
    main()
