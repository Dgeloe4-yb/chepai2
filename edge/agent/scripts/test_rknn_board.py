#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, "/opt/chepai-edge/edge/agent")
sys.path.insert(0, "/opt/chepai-edge")

import numpy as np
from chepai_edge.inference import RknnEngine

for name in ("yolov8n.rknn", "mini_ad.rknn", "plate_color.rknn"):
    p = Path(f"/opt/chepai-edge/weights/{name}")
    e = RknnEngine(p)
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    d = e.predict(img, 0.25)
    print(name, "ok", len(d))
print("all models ok")
