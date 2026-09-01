# Chepai Edge Agent (RK3588)

Production edge daemon: multi-stream RTSP analysis, POST alerts to Spring Boot.

## Detection flow (per camera)

1. **Vehicle** (COCO YOLOv8n): car / bus / truck
2. **Parking ROI** (manual polygons from admin): `bad_park` if misaligned / low IoU (angled stop)
3. **Vehicle in slot**: `non_sedan` for bus/truck
4. **Plate color** (`plate_color.pt`): 在车位内 **整车框** 内搜蓝/绿牌 → `oil_car`（仅允许绿牌）
5. **Gun** (`gun.pt`): alarm if detected **outside** pile ROI **and** outside any vehicle box → `gun_misplace`

## Admin UI (cloud)

`http://38.207.179.218:18081/` — nginx 静态站，`/api` 反代到本机 `:18080`（独立端口，不影响 `:8080` docker）。

部署：`python scripts/deploy_frontend.py`

## Backend

Production API: `http://38.207.179.218:18080`

- Pull config: `GET /api/edge/config?edgeBoxId=...`
- Push alerts: `POST /api/alerts`
- Header when enabled: `X-Chepai-Edge-Token` (must match backend `chepai.edge.token`)

## Dev run (Windows, Ultralytics)

```powershell
cd edge\agent
.\run_agent.bat
```

Requires backend with cameras bound to `edgeBoxId=rk3588-01`, ROI in DB, weights in `edge/poc/weights/`.

## Dual-machine deploy (RK3588 + cloud)

| Node | Role |
|------|------|
| RK3588 `192.168.1.56` | `chepai-edge.service`, RKNN inference |
| Cloud `38.207.179.218:18080` | `chepai-bakend.service`, MySQL `chepai` |

Credentials: copy `deploy.env.local.example` → `deploy.env.local` (gitignored).

```powershell
# From repo root
python scripts/sync_edge_board.py          # agent code + systemd unit
python edge/agent/scripts/export_rknn.ps1  # ONNX on PC → RKNN on server → edge/poc/weights/rknn
```

### RK3588 layout

```
/opt/chepai-edge/
  edge/agent/       # chepai_edge package
  venv/
  weights/*.rknn
  snapshots/
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chepai-edge
journalctl -u chepai-edge -f
```

systemd `Type=notify` + `WatchdogSec=60`: agent sends `READY=1` after startup, then `WATCHDOG=1` from the main loop while inference is still completing. If frames keep arriving but no analyze succeeds for ~48s (NPU / `infer_lock` hang), the process stops petting and systemd restarts it. Camera outage alone does not trip the watchdog.

Board RKNN smoke test:

```bash
/opt/chepai-edge/venv/bin/python /opt/chepai-edge/test_rknn_board.py
```

### 客户端对接（生产 Local API）

`chepai-edge.service` 内嵌 Local API（默认 `:8765`）。Flutter 客户端直连生产进程，**不再使用** `chepai-edge-debug` / `debug_web`。

```bash
sudo systemctl enable --now chepai-edge
# 客户端: http://<板子IP>:8765 或 http://chepai-rk3588:8765
```

## RKNN export (Windows cannot run rknn-toolkit2)

1. `export_rknn.ps1` exports ONNX locally, uploads to cloud x86 host, runs `scripts/onnx2rknn_board.py`, downloads `.rknn` to `edge/poc/weights/rknn/`, then sync to board `weights/`.

2. Set `CHEPAI_INFERENCE=rknn` and `*.rknn` weight names (see `systemd/chepai-edge.service`).

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| CHEPAI_BACKEND_URL | http://38.207.179.218:18080 | Spring Boot |
| CHEPAI_EDGE_BOX_ID | rk3588-01 | matches camera.edge_box_id |
| CHEPAI_INFERENCE | ultralytics / rknn | inference backend |
| CHEPAI_WEIGHTS_DIR | /opt/chepai-edge/weights | model files |
| CHEPAI_EDGE_TOKEN | (empty) | edge auth token |

## DB migration

Apply `chepai-bakend/db/migrations/001_edge_config.sql` and `002_alert_idempotency.sql` on server MySQL database `chepai`.
