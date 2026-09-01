"""Train, validate, and export the charging-gun YOLOv8s detector."""

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
    train_result = model.train(
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

    best_pt = Path(train_result.save_dir) / "weights" / "best.pt"
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
        "--dataset-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "datasets" / "gun",
    )
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=24, help="batch size，4060 笔记本建议 24")
    parser.add_argument("--workers", type=int, default=4, help="数据加载线程，提高 GPU 利用率")
    parser.add_argument(
        "--cache",
        default="disk",
        choices=("false", "true", "disk"),
        help="缓存图片：disk 减少磁盘 IO 等待",
    )
    parser.add_argument("--device", default="0")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1] / "runs" / "gun")
    parser.add_argument("--name", default="gun_v8s")
    parser.add_argument("--base-weights", type=str, default="", help="可选：从已有权重继续微调")
    parser.add_argument("--export-onnx", action="store_true")
    args = parser.parse_args()

    require_cuda()
    print(f"Using GPU: {torch.cuda.get_device_name(0)}")

    cache_map: dict[str, str | bool] = {"false": False, "true": True, "disk": "disk"}
    cache = cache_map[args.cache]

    dataset_root = args.dataset_root.resolve()
    dataset_yaml = dataset_root / "dataset.yaml"
    if not dataset_yaml.exists():
        raise SystemExit(f"Missing dataset yaml: {dataset_yaml}")

    print(f"train config: batch={args.batch} workers={args.workers} cache={cache} imgsz={args.imgsz}")

    best_pt, metrics = train_and_validate(
        dataset_yaml=dataset_yaml,
        project=args.project.resolve(),
        name=args.name,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        base_weights=args.base_weights or None,
        workers=args.workers,
        cache=cache,
    )

    run_dir = args.project.resolve() / args.name
    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    val_model = YOLO(str(best_pt))
    val_model.predict(
        source=str(dataset_root / "images" / "val"),
        save=True,
        project=str(run_dir),
        name="predict_val",
        exist_ok=True,
        conf=0.25,
    )

    weights_dir = Path(__file__).resolve().parents[1] / "weights"
    weights_dir.mkdir(parents=True, exist_ok=True)
    delivered = weights_dir / "gun.pt"
    shutil.copy2(best_pt, delivered)

    if args.export_onnx:
        val_model.export(format="onnx", opset=17, simplify=True)

    print(json.dumps({"best_pt": str(best_pt), "delivered": str(delivered), **metrics}, indent=2))


if __name__ == "__main__":
    main()
