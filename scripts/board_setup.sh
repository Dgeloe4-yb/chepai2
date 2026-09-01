#!/bin/bash
set -euo pipefail
id -u chepai &>/dev/null || useradd -r -m -s /usr/sbin/nologin chepai
mkdir -p /opt/chepai-edge/{agent,weights,snapshots,venv}
chown -R chepai:chepai /opt/chepai-edge
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip libgl1 libglib2.0-0 2>/dev/null || true
python3 -m venv /opt/chepai-edge/venv
/opt/chepai-edge/venv/bin/pip install -q -U pip
/opt/chepai-edge/venv/bin/pip install -q numpy opencv-python-headless
# rknnlite: try pip, else user installs wheel manually
/opt/chepai-edge/venv/bin/pip install -q rknn-toolkit-lite2 2>/dev/null || echo "WARN: pip rknn-toolkit-lite2 failed; install wheel manually"
chown -R chepai:chepai /opt/chepai-edge
echo board_setup_ok
