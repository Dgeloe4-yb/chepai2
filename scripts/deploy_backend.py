#!/usr/bin/env python3
"""Upload chepai-bakend sources and rebuild on the cloud server."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOCAL_ROOT = ROOT / "chepai-bakend"
REMOTE_SRC = "/opt/chepai-bakend/src/chepai-bakend"

UPLOAD_ROOTS = [
    LOCAL_ROOT / "src" / "main" / "java",
    LOCAL_ROOT / "src" / "main" / "resources",
]
EXTRA = [
    LOCAL_ROOT / "build.gradle",
    LOCAL_ROOT / "settings.gradle",
]


def collect() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for base in UPLOAD_ROOTS:
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if "__pycache__" in p.parts:
                continue
            rel = p.relative_to(LOCAL_ROOT).as_posix()
            out.append((p, f"{REMOTE_SRC}/{rel}"))
    for p in EXTRA:
        if p.is_file():
            out.append((p, f"{REMOTE_SRC}/{p.name}"))
    return out


def main() -> None:
    import scripts.ssh_run as s

    files = collect()
    print(f"upload {len(files)} files")
    client = s.connect("server")
    sftp = client.open_sftp()

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

    for i, (local, remote) in enumerate(files, 1):
        ensure_dir(os.path.dirname(remote))
        print(f"  [{i}/{len(files)}] {local.relative_to(LOCAL_ROOT)}")
        sftp.put(str(local), remote)
    sftp.close()

    cmd = f"""
set -e
mkdir -p /opt/chepai-bakend/data/voice /opt/chepai-bakend/data/snapshots
cd {REMOTE_SRC}
chmod +x gradlew 2>/dev/null || true
./gradlew bootJar -x test --no-daemon
cp -f build/libs/*.jar /opt/chepai-bakend/app.jar
systemctl restart chepai-bakend
sleep 8
curl -sS -m 8 http://127.0.0.1:18080/api/health || true
echo
systemctl is-active chepai-bakend
"""
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
    print(stdout.read().decode(errors="replace"))
    err = stderr.read().decode(errors="replace")
    if err:
        print(err, file=sys.stderr)
    code = stdout.channel.recv_exit_status()
    client.close()
    if code != 0:
        raise SystemExit(code)
    print("Backend redeployed")


if __name__ == "__main__":
    main()
