"""Upload a scene image to IPC and run one FramePipeline inference (+ optional load)."""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from _ipc_conn import CONDA_PY, connect, sudo_bash

REMOTE_IMG = "/tmp/chepai_infer_scene.png"
REMOTE_PY = "/tmp/chepai_infer_once.py"


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python _ipc_infer.py <image_path>")
        raise SystemExit(2)
    img = Path(sys.argv[1])
    if not img.is_file():
        raise SystemExit(f"image not found: {img}")

    c, host = connect()
    print(f"SSH via {host}; upload {img.name}", flush=True)
    sftp = c.open_sftp()
    sftp.put(str(img), REMOTE_IMG)

    board = textwrap.dedent(
        f"""
        import json, sys, time, os
        sys.path[:0] = ["/opt/chepai-edge/edge/agent", "/opt/chepai-edge"]
        os.environ.setdefault("CHEPAI_EDGE_HOME", "/opt/chepai-edge")
        os.environ.setdefault("CHEPAI_WEIGHTS_DIR", "/opt/chepai-edge/weights")
        os.environ.setdefault("CHEPAI_INFERENCE", "rknn")
        os.environ.setdefault("CHEPAI_VEHICLE_WEIGHTS", "yolov8n.rknn")
        os.environ.setdefault("CHEPAI_PLATE_WEIGHTS", "plate_color.rknn")
        os.environ.setdefault("CHEPAI_MINI_AD_WEIGHTS", "mini_ad.rknn")

        import cv2
        from chepai_edge.config import AgentConfig
        from chepai_edge.inference import create_engine
        from chepai_edge.pipeline import FramePipeline, rules_from_dict
        from edge.shared.park_align import load_profile

        cfg = AgentConfig.from_env()
        frame = cv2.imread({REMOTE_IMG!r})
        if frame is None:
            raise SystemExit("imread failed")
        h, w = frame.shape[:2]
        vehicle = create_engine(cfg.inference_backend, cfg.resolve_weight(cfg.vehicle_weights))
        plate = create_engine(cfg.inference_backend, cfg.resolve_weight(cfg.plate_weights))
        mini_ad = create_engine(cfg.inference_backend, cfg.resolve_weight(cfg.mini_ad_weights))
        park_path = cfg.resolve_park_align()
        park = load_profile(park_path if park_path.is_file() else None)
        rules = rules_from_dict({{}})
        pipe = FramePipeline(vehicle, plate, mini_ad, rules, park_align=park)
        pipe.analyze_debug(frame, [], rules)
        t0 = time.perf_counter()
        alerts, dbg = pipe.analyze_debug(frame, [], rules)
        ms = (time.perf_counter() - t0) * 1000.0
        vehicles = [
            {{"name": d.class_name, "cls": d.class_id, "conf": round(d.confidence, 3),
              "xyxy": [round(x, 1) for x in d.xyxy]}}
            for d in dbg.vehicles
        ]
        plates = [
            {{"name": det.class_name, "cls": det.class_id, "conf": round(det.confidence, 3),
              "xyxy": [round(x, 1) for x in det.xyxy]}}
            for det, _crop in dbg.plates
        ]
        out = {{
            "size": [w, h],
            "infer_ms": round(ms, 1),
            "vehicles": vehicles,
            "plates": plates,
            "mini_ads": len(dbg.mini_ads),
            "alerts": [{{"type": a.alert_type, "score": a.score}} for a in alerts],
        }}
        print("INFER_JSON=" + json.dumps(out, ensure_ascii=False))
        """
    )
    with sftp.file(REMOTE_PY, "w") as f:
        f.write(board)
    sftp.close()

    sudo_bash(c, "systemctl stop chepai-edge.service", 60)
    try:
        env = (
            "CHEPAI_EDGE_HOME=/opt/chepai-edge CHEPAI_WEIGHTS_DIR=/opt/chepai-edge/weights "
            "CHEPAI_INFERENCE=rknn CHEPAI_VEHICLE_WEIGHTS=yolov8n.rknn "
            "CHEPAI_PLATE_WEIGHTS=plate_color.rknn CHEPAI_MINI_AD_WEIGHTS=mini_ad.rknn "
            "PYTHONPATH=/opt/chepai-edge/edge/agent:/opt/chepai-edge "
        )
        _, o, e = sudo_bash(c, f"{env}{CONDA_PY} {REMOTE_PY}", 180)
        print(o)
        if e.strip() and "password" not in e.lower():
            print(e[-1000:])
        for line in o.splitlines():
            if line.startswith("INFER_JSON="):
                print(json.dumps(json.loads(line[len("INFER_JSON=") :]), ensure_ascii=False, indent=2))
    finally:
        sudo_bash(c, "systemctl start chepai-edge.service", 60)
    c.close()


if __name__ == "__main__":
    main()
