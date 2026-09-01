"""Benchmark full FramePipeline latency on IPC; recommend analyze_fps.

??: python _bench_infer_fps.py [image_path]
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from _ipc_conn import CONDA_PY, connect, sudo_bash

REMOTE_IMG = "/tmp/chepai_bench_scene.png"
REMOTE_PY = "/tmp/chepai_bench_infer.py"
WARMUP = 2
ROUNDS = 8


def main() -> None:
    img = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if img is None or not img.is_file():
        raise SystemExit("??: python _bench_infer_fps.py <image_path>")

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
        from edge.shared.roi_rules import RoiRule

        cfg = AgentConfig.from_env()
        frame = cv2.imread({REMOTE_IMG!r})
        if frame is None:
            raise SystemExit("imread failed")
        vehicle = create_engine(cfg.inference_backend, cfg.resolve_weight(cfg.vehicle_weights))
        plate = create_engine(cfg.inference_backend, cfg.resolve_weight(cfg.plate_weights))
        mini_ad = create_engine(cfg.inference_backend, cfg.resolve_weight(cfg.mini_ad_weights))
        park_path = cfg.resolve_park_align()
        park = load_profile(park_path if park_path.is_file() else None)
        rules = rules_from_dict({{}})
        pipe = FramePipeline(vehicle, plate, mini_ad, rules, park_align=park)
        rois = [
            RoiRule(kind="ad", polygon=[(0.21, 0.01), (0.92, 0.01), (0.92, 0.97), (0.21, 0.97)],
                    normalized=True, name="ad_zone", roi_id=1)
        ]

        def once():
            t0 = time.perf_counter()
            alerts, dbg = pipe.analyze_debug(frame, rois, rules)
            return (time.perf_counter() - t0) * 1000.0, len(dbg.vehicles), len(dbg.plates), len(alerts)

        for _ in range({WARMUP}):
            once()
        samples = []
        last = None
        for _ in range({ROUNDS}):
            last = once()
            samples.append(last[0])
        samples.sort()
        out = {{
            "vehicles": last[1], "plates": last[2], "alerts": last[3],
            "ms_min": samples[0],
            "ms_median": samples[len(samples)//2],
            "ms_mean": sum(samples)/len(samples),
            "ms_p90": samples[max(0, int(len(samples)*0.9)-1)],
            "ms_max": samples[-1],
            "samples_ms": [round(x, 1) for x in samples],
        }}
        print("BENCH_JSON:" + json.dumps(out, ensure_ascii=False))
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
        _code, stdout, stderr = sudo_bash(c, f"{env}{CONDA_PY} {REMOTE_PY}", 300)
        print(stdout, flush=True)
        if stderr.strip() and "password" not in stderr.lower():
            print("STDERR:", stderr[-1500:], flush=True)
    finally:
        sudo_bash(c, "systemctl start chepai-edge.service", 60)
    c.close()

    line = next((ln for ln in stdout.splitlines() if ln.startswith("BENCH_JSON:")), None)
    if not line:
        raise SystemExit("benchmark JSON missing")
    data = json.loads(line.split("BENCH_JSON:", 1)[1])
    med = float(data["ms_median"])
    p90 = float(data["ms_p90"])
    max_fps = 1000.0 / (p90 * 1.4)
    candidates = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    recommended = max((f for f in candidates if f <= max_fps + 1e-9), default=0.5)
    if recommended > 2.0 and max_fps < 3.5:
        recommended = 2.0
    print(json.dumps(data, indent=2, ensure_ascii=False), flush=True)
    print(
        f"median={med:.1f}ms p90={p90:.1f}ms safe_max?{max_fps:.2f}fps "
        f"recommend_analyze_fps={recommended}",
        flush=True,
    )


if __name__ == "__main__":
    main()
