"""Train YOLOv8 mini_ad detector (replaces charging-gun model)."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import torch
from ultralytics import YOLO


def require_cuda() -> None:
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available. Install GPU-enabled PyTorch before training.")


def train_and_validate(
    dataset_yaml: Path,
    project: Path,
    name: str,
    epochs: int,
    imgsz: int,
    batch: int,
    device: str,
    base_weights: str | None = None,
    workers: int = 4,
    cache: str | bool = "disk",
) -> tuple[Path, dict]:
    model = YOLO(base_weights or "yolov8s.pt")
    model.train(
        data=str(dataset_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        patience=30,
        project=str(project),
        name=name,
        mosaic=0.8,
        copy_paste=0.0,
        hsv_h=0.015,
        hsv_s=0.5,
        hsv_v=0.3,
        degrees=8,
        translate=0.08,
        scale=0.4,
        fliplr=0.5,
        cache=cache,
        workers=workers,
        amp=True,
        exist_ok=True,
    )

    best_pt = project / name / "weights" / "best.pt"
    val_model = YOLO(str(best_pt))
    metrics = val_model.val(data=str(dataset_yaml), device=device, workers=workers)
    metric_dict = {
        "map50": float(metrics.box.map50),
        "map50_95": float(metrics.box.map),
    }
    return best_pt, metric_dict


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path("D:/chepai2_train/mini_ad"),
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
        help="default: work-root/datasets/mini_ad",
    )
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=24)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--cache",
        default="disk",
        choices=("false", "true", "disk"),
    )
    parser.add_argument("--device", default="0")
    parser.add_argument("--name", default="mini_ad_v8s")
    parser.add_argument("--base-weights", type=str, default="")
    parser.add_argument("--export-onnx", action="store_true")
    parser.add_argument("--skip-predict", action="store_true")
    args = parser.parse_args()

    require_cuda()
    print(f"Using GPU: {torch.cuda.get_device_name(0)}")

    work_root = args.work_root.resolve()
    dataset_root = (args.dataset_root or work_root / "datasets" / "mini_ad").resolve()
    project = work_root / "runs"
    dataset_yaml = dataset_root / "dataset.yaml"
    if not dataset_yaml.is_file():
        raise SystemExit(
            f"Missing dataset: {dataset_yaml}\n"
            "Run: download_mini_ad.bat then prepare_mini_ad.bat"
        )

    cache_map: dict[str, str | bool] = {"false": False, "true": True, "disk": "disk"}
    cache = cache_map[args.cache]

    print(f"dataset={dataset_root} batch={args.batch} imgsz={args.imgsz}")

    best_pt, metrics = train_and_validate(
        dataset_yaml=dataset_yaml,
        project=project,
        name=args.name,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        base_weights=args.base_weights or None,
        workers=args.workers,
        cache=cache,
    )

    run_dir = project / args.name
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    if not args.skip_predict:
        val_model = YOLO(str(best_pt))
        val_img = dataset_root / "images" / "val"
        if val_img.is_dir():
            val_model.predict(
                source=str(val_img),
                save=True,
                project=str(run_dir),
                name="predict_val",
                exist_ok=True,
                conf=0.25,
            )

    poc_weights = Path(__file__).resolve().parents[2] / "weights"
    poc_weights.mkdir(parents=True, exist_ok=True)
    delivered = poc_weights / "mini_ad.pt"
    shutil.copy2(best_pt, delivered)

    if args.export_onnx:
        YOLO(str(best_pt)).export(format="onnx", opset=17, simplify=True)

    print(json.dumps({"best_pt": str(best_pt), "delivered": str(delivered), **metrics}, indent=2))


if __name__ == "__main__":
    main()
