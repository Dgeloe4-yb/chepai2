"""IPC health: service status, load, NPU, temps, live API snapshot."""
from __future__ import annotations

import json
import urllib.request

from _ipc_conn import HOSTNAME, connect, sudo_bash


def main() -> None:
    c, host = connect()
    print(f"SSH via {host}", flush=True)

    code, o, e = sudo_bash(
        c,
        r"""
set -e
echo '=== service ==='
systemctl is-enabled chepai-edge.service || true
systemctl is-active chepai-edge.service || true
PID=$(systemctl show -p MainPID --value chepai-edge)
echo PID=$PID
ps -o pid,etime,pcpu,pmem,rss,cmd -p $PID 2>/dev/null || true
echo threads=$(ls /proc/$PID/task 2>/dev/null | wc -l)
echo '=== load ==='
uptime
nproc
free -h | head -3
echo '=== npu ==='
cat /sys/kernel/debug/rknpu/load 2>/dev/null || echo no_rknpu_load
echo '=== temps ==='
for f in /sys/class/thermal/thermal_zone*/temp; do
  z=$(dirname "$f"); t=$(cat "$f"); type=$(cat "$z/type")
  awk -v t="$t" -v n="$type" 'BEGIN{printf "%s: %.1f C\n", n, t/1000}'
done
echo '=== top ==='
ps -eo pid,pcpu,pmem,rss,cmd --sort=-pcpu | head -n 10
""",
        timeout=60,
    )
    print(o)
    if code != 0 and e.strip():
        print(e[-800:])
    c.close()

    for base in (f"http://{host}:8765", f"http://{HOSTNAME}:8765", f"http://{HOSTNAME}.local:8765"):
        try:
            with urllib.request.urlopen(f"{base}/api/state.json", timeout=6) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            cams = d.get("cameras") or []
            print(
                f"API {base} ok cameras={len(cams)} "
                f"rtsp={cams[0].get('rtsp') if cams else None} "
                f"frame={d.get('frameW')}x{d.get('frameH')}",
                flush=True,
            )
            break
        except Exception as exc:  # noqa: BLE001
            print(f"API {base} fail: {exc}", flush=True)


if __name__ == "__main__":
    main()
