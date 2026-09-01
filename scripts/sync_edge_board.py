#!/usr/bin/env python3
"""Upload edge agent code to RK3588 (/opt/chepai-edge/edge/agent)."""

from __future__ import annotations

import os
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
AGENT = ROOT / "edge" / "agent"
SHARED = ROOT / "edge" / "shared"
REMOTE_AGENT = "/opt/chepai-edge/edge/agent"
REMOTE_SHARED = "/opt/chepai-edge/edge/shared"
SKIP = {".venv", "__pycache__", ".pytest_cache", ".mypy_cache"}


def main() -> None:
    import scripts.ssh_run as s

    client = s.connect("board")
    sftp = client.open_sftp()

    def ensure_remote_dir(path: str) -> None:
        parts = path.strip("/").split("/")
        cur = ""
        for p in parts:
            cur += "/" + p
            try:
                sftp.stat(cur)
            except OSError:
                sftp.mkdir(cur)

    def upload_tree(local_root: Path, remote_root: str) -> None:
        for dirpath, dirnames, filenames in os.walk(local_root):
            dirnames[:] = [d for d in dirnames if d not in SKIP]
            rel = Path(dirpath).relative_to(local_root)
            remote_dir = remote_root if rel == Path(".") else f"{remote_root}/{rel.as_posix()}"
            ensure_remote_dir(remote_dir)
            for name in filenames:
                if name.endswith(".pyc"):
                    continue
                local = Path(dirpath) / name
                remote = f"{remote_dir}/{name}"
                print("put", remote)
                sftp.put(str(local), remote)

    upload_tree(AGENT, REMOTE_AGENT)
    if SHARED.is_dir():
        upload_tree(SHARED, REMOTE_SHARED)

    test_script = ROOT / "edge" / "agent" / "scripts" / "test_rknn_board.py"
    sftp.put(str(test_script), "/opt/chepai-edge/test_rknn_board.py")
    for unit_name in ("chepai-edge.service",):
        local_unit = AGENT / "systemd" / unit_name
        if local_unit.is_file():
            sftp.put(str(local_unit), f"/etc/systemd/system/{unit_name}")
    sftp.close()
    client.close()
    print("sync done")


if __name__ == "__main__":
    main()
