"""Upload mini_ad.onnx, convert to RKNN on board, restart production agent."""
from __future__ import annotations

import sys
from pathlib import Path

from _ipc_conn import CONDA_PY, REMOTE_ROOT, connect, sudo_bash

CONVERT = f"{REMOTE_ROOT}/onnx2rknn_board.py"
REMOTE_WEIGHTS = f"{REMOTE_ROOT}/weights"
ROOT = Path(__file__).resolve().parents[2]
ONNX = ROOT / "edge" / "poc" / "weights" / "mini_ad.onnx"


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> None:
    if not ONNX.is_file():
        log(f"缺少 {ONNX}，请先导出 ONNX")
        sys.exit(1)

    log("[1/5] 连接 IPC …")
    c, used = connect()
    log(f"  via {used}")

    log(f"[2/5] 上传 {ONNX.name} …")
    sudo_bash(c, f"chown -R admin:admin {REMOTE_WEIGHTS}", 30)
    sftp = c.open_sftp()
    remote_onnx = f"{REMOTE_WEIGHTS}/mini_ad.onnx"
    sftp.put(str(ONNX), remote_onnx)
    sftp.close()

    log("[3/5] 板端 ONNX → RKNN …")
    code, o, e = sudo_bash(
        c,
        f"{CONDA_PY} {CONVERT} {remote_onnx} {REMOTE_WEIGHTS}/mini_ad.rknn 640",
        timeout=900,
    )
    if o.strip():
        log(o.rstrip()[-2000:])
    if code != 0:
        log(e[-1000:])
        log("RKNN 转换失败")
        c.close()
        sys.exit(1)

    log("[4/5] 重启生产服务 …")
    for cmd in (
        f"chown chepai:chepai {REMOTE_WEIGHTS}/mini_ad.*",
        "systemctl restart chepai-edge.service",
        "sleep 3",
        "systemctl is-active chepai-edge.service",
        f"ls -lh {REMOTE_WEIGHTS}/mini_ad.*",
    ):
        _c, out, _e = sudo_bash(c, cmd, 60)
        if out.strip():
            log(out.strip())

    log("[5/5] smoke test …")
    test_py = (
        "import sys; sys.path[:0]=['/opt/chepai-edge/edge/agent','/opt/chepai-edge'];"
        "import numpy as np; from chepai_edge.inference import RknnEngine;"
        "from pathlib import Path;"
        "p=Path('/opt/chepai-edge/weights/mini_ad.rknn');"
        "e=RknnEngine(p); d=e.predict(np.zeros((480,640,3),dtype=np.uint8),0.25);"
        "print('mini_ad.rknn ok', len(d))"
    )
    _c, out, _e = sudo_bash(c, f"{CONDA_PY} -c {test_py!r}", 120)
    log(out.strip() or _e[-500:])
    c.close()
    log("完成")


if __name__ == "__main__":
    main()
