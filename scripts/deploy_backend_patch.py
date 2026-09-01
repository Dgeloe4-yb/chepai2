#!/usr/bin/env python3
"""Upload changed Java sources and rebuild chepai-bakend on cloud server."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

JAVA_ROOT = (
    ROOT / "chepai-bakend" / "src" / "main" / "java" / "com" / "atguigu" / "chepaibakend"
)
REMOTE_SRC = "/opt/chepai-bakend/src/chepai-bakend"
FILES = [
    JAVA_ROOT / "web" / "RoiController.java",
    JAVA_ROOT / "repository" / "RoiRepository.java",
    JAVA_ROOT / "web" / "CameraController.java",
    JAVA_ROOT / "repository" / "CameraRepository.java",
    JAVA_ROOT / "dto" / "CameraDtos.java",
]


def main() -> None:
    import scripts.ssh_run as s

    client = s.connect("server")
    sftp = client.open_sftp()

    for local in FILES:
        if not local.is_file():
            print("skip missing", local)
            continue
        rel = local.relative_to(JAVA_ROOT).as_posix()
        remote = f"{REMOTE_SRC}/src/main/java/com/atguigu/chepaibakend/{rel}"
        print("put", remote)
        sftp.put(str(local), remote)

    sftp.close()

    cmd = f"""
set -e
cd {REMOTE_SRC}
chmod +x gradlew
./gradlew bootJar -x test --no-daemon
cp -f build/libs/*.jar /opt/chepai-bakend/app.jar
systemctl restart chepai-bakend
sleep 4
curl -s http://127.0.0.1:18080/api/health
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
    print("Backend redeployed with DELETE /api/rois/{id}")


if __name__ == "__main__":
    main()
