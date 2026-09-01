"""Set IPC hostname + avahi (.local) so LAN can use chepai-rk3588 without looking up IP."""
from __future__ import annotations

import base64
import sys

from _ipc_conn import HOSTNAME, connect, sudo_bash


def main() -> None:
    try:
        c, used = connect()
    except Exception as exc:
        print(f"连接失败: {exc}")
        sys.exit(1)
    print(f"SSH via {used}", flush=True)

    # Discover current LAN IPv4 for optional /etc/hosts self-map
    _code, ip_out, _ = sudo_bash(
        c,
        "ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -1",
        20,
    )
    lan_ip = (ip_out or "").strip().splitlines()[-1] if ip_out.strip() else ""

    script = f"""
set -e
hostnamectl set-hostname {HOSTNAME}
echo {HOSTNAME} > /etc/hostname
sed -i '/chepai-rk3588/d' /etc/hosts
if grep -q '^127.0.1.1' /etc/hosts; then
  sed -i 's/^127.0.1.1.*/127.0.1.1\\t{HOSTNAME}/' /etc/hosts
else
  printf '127.0.1.1\\t{HOSTNAME}\\n' >> /etc/hosts
fi
if [ -n "{lan_ip}" ]; then
  printf '{lan_ip}\\t{HOSTNAME}\\n' >> /etc/hosts
fi
if ! command -v avahi-daemon >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq || true
  apt-get install -y -qq avahi-daemon libnss-mdns || true
fi
systemctl enable --now avahi-daemon || true
if [ -f /etc/avahi/avahi-daemon.conf ]; then
  sed -i 's/^#\\?host-name=.*/host-name={HOSTNAME}/' /etc/avahi/avahi-daemon.conf || true
  systemctl restart avahi-daemon || true
fi
echo hostname=$(hostname)
echo hosts:
grep -E 'chepai|127.0.1.1' /etc/hosts || true
systemctl is-active avahi-daemon || true
"""
    payload = base64.b64encode(script.encode()).decode()
    code, o, e = sudo_bash(c, f"echo {payload} | base64 -d | bash", 180)
    print(o)
    if code != 0:
        print(e[-1000:])
        c.close()
        sys.exit(1)
    c.close()
    print(f"完成。优先用: http://{HOSTNAME}.local:8765  （IP 变了也通常还能用）")
    print(f"短名 http://{HOSTNAME}:8765 依赖本机 hosts/mDNS；Windows hosts 写死 IP 后 IP 变了要改。")


if __name__ == "__main__":
    main()
