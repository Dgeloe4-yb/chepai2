#!/usr/bin/env python3
"""Upload files to board or server via SFTP. Usage: python ssh_upload.py board local remote"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    if len(sys.argv) < 4:
        print("Usage: ssh_upload.py board|server <local_path> <remote_path>")
        sys.exit(1)
    target, local, remote = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    from scripts.ssh_run import connect, load_env  # noqa: PLC2701

    import paramiko

    client = connect(target)
    sftp = client.open_sftp()

    def put(path: Path, rpath: str) -> None:
        if path.is_dir():
            try:
                sftp.mkdir(rpath)
            except OSError:
                pass
            for child in path.rglob("*"):
                if child.is_file():
                    rel = child.relative_to(path).as_posix()
                    rp = f"{rpath.rstrip('/')}/{rel}"
                    parts = rp.split("/")
                    acc = ""
                    for part in parts[:-1]:
                        acc = f"{acc}/{part}" if acc else part
                        try:
                            sftp.mkdir(acc)
                        except OSError:
                            pass
                    sftp.put(str(child), rp)
        else:
            parent = "/".join(remote.rsplit("/", 1)[:-1])
            if parent:
                try:
                    sftp.mkdir(parent)
                except OSError:
                    pass
            sftp.put(str(path), remote)

    put(local.resolve(), remote)
    sftp.close()
    client.close()
    print(f"uploaded {local} -> {remote}")


if __name__ == "__main__":
    main()
