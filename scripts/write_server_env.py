#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts.ssh_run as s

cfg = s.load_env()
lines = [
    f"SERVER_PORT={cfg.get('SERVER_PORT', '18080')}",
    f"MYSQL_HOST={cfg.get('MYSQL_HOST', '127.0.0.1')}",
    f"MYSQL_PORT={cfg.get('MYSQL_PORT', '3306')}",
    f"MYSQL_DATABASE={cfg.get('MYSQL_DATABASE', 'chepai')}",
    f"MYSQL_USER={cfg.get('MYSQL_USER', '')}",
    f"MYSQL_PASSWORD={cfg.get('MYSQL_PASSWORD', '')}",
    f"CHEPAI_EDGE_TOKEN={cfg.get('CHEPAI_EDGE_TOKEN', '')}",
    "CHEPAI_SNAPSHOTS_DIR=/opt/chepai-bakend/data/snapshots",
]
content = "\n".join(lines) + "\n"
tmp = Path(__file__).resolve().parents[1] / ".tmp_application.env"
tmp.write_text(content, encoding="utf-8")
client = s.connect("server")
sftp = client.open_sftp()
sftp.put(str(tmp), "/opt/chepai-bakend/application.env")
sftp.close()
client.exec_command("chmod 600 /opt/chepai-bakend/application.env")
client.close()
tmp.unlink(missing_ok=True)
print("ok")
