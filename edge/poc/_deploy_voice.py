"""Deploy voice wavs to IPC and set USB speaker as ALSA playback target."""
from __future__ import annotations

import base64
from pathlib import Path

from _ipc_conn import REMOTE_ROOT, USER, connect, sudo_bash

LOCAL_VOICE = Path(__file__).resolve().parents[1] / "agent" / "voice"
WAVS = (
    "dual_slot.wav",
    "car_in_bus_slot.wav",
    "bad_park.wav",
    "mini_ad.wav",
    "non_sedan.wav",
    "oil_car.wav",
)
LOCAL_UNIT = Path(__file__).resolve().parents[1] / "agent" / "systemd" / "chepai-edge.service"
LOCAL_VOICE_PY = Path(__file__).resolve().parents[1] / "agent" / "chepai_edge" / "voice.py"


def main() -> None:
    missing = [n for n in WAVS if not (LOCAL_VOICE / n).is_file()]
    if missing:
        raise SystemExit(f"缺少 wav，先跑 _gen_voice_wavs.py: {missing}")

    c, host = connect()
    print(f"SSH via {host}", flush=True)
    sudo_bash(c, f"mkdir -p {REMOTE_ROOT}/voice; chown -R {USER}:{USER} {REMOTE_ROOT}/voice", 30)

    sftp = c.open_sftp()
    for name in WAVS:
        local = LOCAL_VOICE / name
        remote = f"{REMOTE_ROOT}/voice/{name}"
        print(f"  put {name} ({local.stat().st_size} bytes)", flush=True)
        sftp.put(str(local), remote)
    sftp.put(str(LOCAL_VOICE_PY), f"/tmp/voice.py")
    sftp.put(str(LOCAL_UNIT), f"/tmp/chepai-edge.service")
    sftp.close()

    script = f"""
set -e
cp -f /tmp/voice.py {REMOTE_ROOT}/edge/agent/chepai_edge/voice.py
cp -f /tmp/chepai-edge.service /etc/systemd/system/chepai-edge.service
# keep conda python path if already patched
if ! grep -q miniconda3 /etc/systemd/system/chepai-edge.service; then
  sed -i 's|/opt/chepai-edge/venv/bin/python|/home/admin/miniconda3/envs/rknn/bin/python|g' /etc/systemd/system/chepai-edge.service
fi
chown -R chepai:chepai {REMOTE_ROOT}/voice {REMOTE_ROOT}/edge/agent/chepai_edge/voice.py

# ALSA default -> USB card named Device (GEMBIRD)
cat > /etc/asound.conf <<'EOF'
pcm.!default {{
    type plug
    slave.pcm "dmix_usb"
}}
pcm.dmix_usb {{
    type dmix
    ipc_key 1234
    slave {{
        pcm "hw:Device,0"
        period_time 0
        period_size 1024
        buffer_size 4096
        rate 44100
    }}
}}
ctl.!default {{
    type hw
    card Device
}}
EOF

# unmute USB
amixer -c Device sset PCM 85% unmute 2>/dev/null || amixer -c 5 sset PCM 85% unmute 2>/dev/null || true

systemctl daemon-reload
systemctl restart chepai-edge.service
sleep 3
systemctl is-active chepai-edge.service
ls -lh {REMOTE_ROOT}/voice/
echo '=== smoke aplay mini_ad ==='
sudo -u chepai aplay -D plughw:Device,0 -q {REMOTE_ROOT}/voice/mini_ad.wav
echo APLAY_OK
journalctl -u chepai-edge -n 15 --no-pager | grep -i voice || true
"""
    payload = base64.b64encode(script.encode()).decode()
    code, o, e = sudo_bash(c, f"echo {payload} | base64 -d | bash", 120)
    print(o)
    if e.strip() and "password" not in e.lower():
        print("STDERR", e[-1500:])
    c.close()
    if code != 0 or "APLAY_OK" not in o:
        raise SystemExit(f"deploy failed code={code}")
    print("完成：wav 已部署，默认走 USB，并已试播 mini_ad.wav")


if __name__ == "__main__":
    main()
