# chepai2 Edge — Reference

## Key files

| File | Role |
|------|------|
| `edge/poc/poc_pipeline.py` | Main multi-model loop: vehicle YOLO, gun ROI, LPR/HSV plate hint, parking ROI |
| `edge/poc/gun_camera.py` | Standalone gun detector on camera/RTSP |
| `edge/poc/roi_rules.py` | `RoiRule`, point-in-polygon, IoU, parking slot eval |
| `edge/poc/lpr_hyperlpr.py` | HyperLPR3 wrapper |
| `edge/poc/training/train_gun.py` | Gun YOLOv8s training |
| `edge/poc/training/plate_color/prepare_ccpd.py` | CCPD → YOLO plate_blue/plate_green |
| `edge/poc/training/plate_color/train_plate_color.py` | Plate color YOLOv8n training |

## ROI JSON format (`sample_rois.json`)

```json
[
  {
    "kind": "pile",
    "normalized": true,
    "polygon": [[0.1, 0.2], [0.3, 0.2], [0.3, 0.5], [0.1, 0.5]]
  },
  {
    "kind": "parking",
    "normalized": true,
    "polygon": [[...]]
  }
]
```

- `pile` — charging station; gun model runs inside AABB of polygon
- `parking` — slot polygon; vehicle center inside triggers overlap check

## Dataset YAML examples

**Gun** (`datasets/gun/dataset.yaml`):

```yaml
path: ...
train: images/train
val: images/val
names:
  0: gun
```

**Plate color** (`D:/chepai2_train/datasets/plate_color/dataset.yaml`):

```yaml
path: D:/chepai2_train/datasets/plate_color
train: images/train
val: images/val
names:
  0: plate_blue
  1: plate_green
```

CCPD filename encodes bbox: stem split by `-`, field `[2]` → `x1&y1_x2&y2` (see `ccpd_utils.py`).

## Training outputs

| Task | Best weights | Metrics file |
|------|--------------|--------------|
| Gun | `edge/poc/weights/gun.pt` | `runs/gun/gun_manual_v2/metrics.json` |
| Plate color | `edge/poc/weights/plate_color.pt` | `D:/chepai2_train/runs/plate_color/plate_color_v8n/metrics.json` |

Plate color benchmark (current): mAP50 ≈ 0.995, mAP50-95 ≈ 0.843 on 4k val set.

## Disk hygiene

Safe to delete on C: when space tight:

- `data/downloads/.cache`, duplicate extracts, old `runs/gun/*` except best run
- `datasets/gun/previews*`, zzscaled train copies (`00506+`) if gun.pt is finalized
- YOLO label `.cache` files (regenerated on train)

Keep:

- `weights/gun.pt`, `weights/plate_color.pt`
- Original gun images + labels in `datasets/gun/`
- `edge/poc/.venv/`

## Planned pipeline integration (plate_color)

When wiring into `poc_pipeline.py`:

1. Add `--plate-color-weights` arg
2. On vehicle detect → crop plate region (reuse `plate_roi_from_vehicle` or vehicle crop)
3. Run plate_color YOLO; map class 0 → `blue_plate`, class 1 → `green_plate`
4. Emit `likely_ev_plate` / `possible_oil_block` with `"source": "plate_color"`
5. Keep HSV as fallback only when model not loaded or no detection

## RK3588 pipeline sketch

```
Per stream (704×576, 5–10 fps analyze):
  Thread/queue
    → vehicle RKNN (full frame, every N frames)
    → for each vehicle: plate_color RKNN (crop)
    → for pile ROI: gun RKNN (crop)
    → spatial rules: gun in pile OR vehicle → else alarm
    → JSON events → backend
```

Convert path: `yolo export format=onnx` → vendor RKNN toolkit → `.rknn` on board.

## Edge agent (production daemon)

Path: `edge/agent/chepai_edge/`

| Module | Role |
|--------|------|
| `main.py` | Entry: load config, spawn per-camera workers |
| `backend.py` | `GET /api/edge/config`, `POST /api/alerts` |
| `pipeline.py` | bad_park, non_sedan, oil_car, gun_misplace logic |
| `stream.py` | RTSP worker thread per camera |
| `inference.py` | Ultralytics (dev) / RknnEngine shared runtime (board) |

Backend URL fixed: `http://38.207.179.218:18080`

Dev run: `edge/agent/run_agent.bat` (uses `edge/poc/.venv` + `edge/poc/weights/`)

Deploy: `edge/agent/systemd/chepai-edge.service` → `/opt/chepai-edge/`

DB migration: `chepai-bakend/db/migrations/001_edge_config.sql`
