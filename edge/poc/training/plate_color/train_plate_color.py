"""Train YOLOv8n blue/green plate color detector."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import torch
from ultralytics import YOLO

DEFAULT_WORK_ROOT = Path("D:/chepai2_train")


def require_cuda() -> None:
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available. Install GPU-enabled PyTorch before training.")


def configure_work_dirs(work_root: Path) -> None:
    work_root = work_root.resolve()
    for sub in ("tmp", "runs", "datasets", "logs", "torch_home", "hf_home"):
        (work_root / sub).mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(work_root / "tmp")
    os.environ["TMP"] = str(work_root / "tmp")
    os.environ["TMPDIR"] = str(work_root / "tmp")
    os.environ["TORCH_HOME"] = str(work_root / "torch_home")
    os.environ["HF_HOME"] = str(work_root / "hf_home")


def main() -> None:
    parser = argparse.ArgumentParser(description="训练蓝牌/绿牌检测模型")
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--dataset-root", type=Path, default=None)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--cache", default="disk", choices=("false", "true", "disk"))
    parser.add_argument("--device", default="0")
    parser.add_argument("--project", type=Path, default=None)
    parser.add_argument("--name", default="plate_color_v8n")
    parser.add_argument("--base-weights", type=str, default="yolov8n.pt")
    parser.add_argument("--export-onnx", action="store_true")
    parser.add_argument("--skip-predict", action="store_true", help="跳过 val 批量出图，省磁盘")
    args = parser.parse_args()

    work_root = args.work_root.resolve()
    configure_work_dirs(work_root)

    dataset_root = (args.dataset_root or work_root / "datasets" / "plate_color").resolve()
    project = (args.project or work_root / "runs" / "plate_color").resolve()

    require_cuda()
    cache_map: dict[str, str | bool] = {"false": False, "true": True, "disk": "disk"}
    cache = cache_map[args.cache]

    dataset_yaml = dataset_root / "dataset.yaml"
    if not dataset_yaml.exists():
        raise SystemExit(f"Missing dataset yaml: {dataset_yaml}. Run prepare_ccpd.py first.")

    print(f"Using GPU: {torch.cuda.get_device_name(0)}")
    print(f"work_root={work_root}")
    print(f"dataset_root={dataset_root}")
    print(f"project={project}")
    print(f"train config: batch={args.batch} workers={args.workers} cache={cache} imgsz={args.imgsz}")

    model = YOLO(args.base_weights)
    train_result = model.train(
        data=str(dataset_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        patience=20,
        project=str(project),
        name=args.name,
        mosaic=0.5,
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        degrees=5,
        translate=0.05,
        scale=0.35,
        fliplr=0.5,
        cache=cache,
        workers=args.workers,
        amp=True,
        exist_ok=True,
    )

    best_pt = Path(train_result.save_dir) / "weights" / "best.pt"
    val_model = YOLO(str(best_pt))
    metrics = val_model.val(data=str(dataset_yaml), device=args.device, workers=args.workers)
    metric_dict = {
        "map50": float(metrics.box.map50),
        "map50_95": float(metrics.box.map),
    }

    run_dir = project / args.name
    (run_dir / "metrics.json").write_text(json.dumps(metric_dict, indent=2), encoding="utf-8")

    if not args.skip_predict:
        val_model.predict(
            source=str(dataset_root / "images" / "val"),
            save=True,
            project=str(run_dir),
            name="predict_val",
            exist_ok=True,
            conf=0.25,
        )

    weights_dir = Path(__file__).resolve().parents[2] / "weights"
    weights_dir.mkdir(parents=True, exist_ok=True)
    delivered = weights_dir / "plate_color.pt"
    shutil.copy2(best_pt, delivered)

    if args.export_onnx:
        val_model.export(format="onnx", opset=17, simplify=True)

    print(json.dumps({"best_pt": str(best_pt), "delivered": str(delivered), **metric_dict}, indent=2))


if __name__ == "__main__":
    main()
