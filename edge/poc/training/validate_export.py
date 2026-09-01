"""Validate and export an existing gun detector checkpoint."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--weights",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "runs" / "gun" / "gun_v8s" / "weights" / "best.pt",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "datasets" / "gun",
    )
    parser.add_argument("--device", default="0")
    parser.add_argument("--export-onnx", action="store_true")
    args = parser.parse_args()

    dataset_yaml = args.dataset_root / "dataset.yaml"
    model = YOLO(str(args.weights))
    metrics = model.val(data=str(dataset_yaml), device=args.device, workers=0)
    metric_dict = {"map50": float(metrics.box.map50), "map50_95": float(metrics.box.map)}

    run_dir = args.weights.parent.parent
    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metric_dict, indent=2), encoding="utf-8")

    model.predict(
        source=str(args.dataset_root / "images" / "val"),
        save=True,
        project=str(run_dir),
        name="predict_val",
        exist_ok=True,
        conf=0.25,
        device=args.device,
        workers=0,
    )

    delivered = Path(__file__).resolve().parents[1] / "weights" / "gun.pt"
    delivered.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.weights, delivered)

    result = {"best_pt": str(args.weights), "delivered": str(delivered), **metric_dict}
    if args.export_onnx:
        result["onnx"] = str(model.export(format="onnx", opset=17, simplify=True))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
