"""Batch inference smoke test for the trained gun detector."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--weights",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "weights" / "gun.pt",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.exists():
        raise SystemExit(f"Source not found: {source}")

    model = YOLO(str(args.weights))
    if source.is_dir():
        images = sorted(
            [p for p in source.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}]
        )[: args.limit]
        if not images:
            raise SystemExit(f"No images found in {source}")
        results = model.predict(source=[str(p) for p in images], conf=args.conf, device=args.device, verbose=False)
    else:
        results = model.predict(source=str(source), conf=args.conf, device=args.device, verbose=False)

    summary = []
    for result in results:
        count = 0 if result.boxes is None else len(result.boxes)
        summary.append({"image": Path(result.path).name, "detections": count})

    print(json.dumps({"weights": str(args.weights), "samples": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
