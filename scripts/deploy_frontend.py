#!/usr/bin/env python3
"""Build Vue admin and deploy to cloud server on port 18081 (nginx, isolated)."""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FRONT = ROOT / "chepai-fronted"
NGINX = ROOT / "deploy" / "chepai-fronted.nginx"


def main() -> None:
    import scripts.ssh_run as s

    if not (FRONT / "package.json").is_file():
        raise SystemExit("chepai-fronted not found")

    env = {"VITE_API_BASE_URL": ""}
    print("npm run build (same-origin /api via nginx 18081)...")
    subprocess.run(
        ["npm", "run", "build"],
        cwd=FRONT,
        env={**os.environ, **env},
        check=True,
        shell=sys.platform == "win32",
    )
    dist = FRONT / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("dist/ missing after build")

    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tar_path = Path(tmp.name)
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(dist, arcname="dist")

    client = s.connect("server")
    sftp = client.open_sftp()
    remote_tar = "/tmp/chepai-fronted-dist.tar.gz"
    sftp.put(str(tar_path), remote_tar)
    sftp.put(str(NGINX), "/tmp/chepai-fronted.nginx")
    sftp.close()
    tar_path.unlink(missing_ok=True)

    cmd = """
set -e
mkdir -p /opt/chepai-fronted
rm -rf /opt/chepai-fronted/*
tar -xzf /tmp/chepai-fronted-dist.tar.gz -C /tmp
cp -a /tmp/dist/* /opt/chepai-fronted/
cp /tmp/chepai-fronted.nginx /etc/nginx/conf.d/chepai-fronted.conf
nginx -t
systemctl reload nginx
ss -tlnp | grep 18081 || true
echo OK: http://38.207.179.218:18081/
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
    print("Deployed: http://38.207.179.218:18081/")


if __name__ == "__main__":
    main()
