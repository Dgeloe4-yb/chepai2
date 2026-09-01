"""Zero-shot pseudo-labeling for charging gun images using YOLO-World."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

PROMPTS = [
    "charging gun",
    "EV charging connector",
    "electric vehicle charging gun",
    "dc charging connector",
    "charging plug",
    "ev charger handle",
    "充电枪",
]


def xyxy_to_yolo(box: list[float], width: int, height: int) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = box
    cx = ((x1 + x2) / 2) / width
    cy = ((y1 + y2) / 2) / height
    w = (x2 - x1) / width
    h = (y2 - y1) / height
    return cx, cy, w, h


def write_label(label_path: Path, cx: float, cy: float, bw: float, bh: float) -> None:
    label_path.write_text(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n", encoding="utf-8")


def has_label(label_path: Path) -> bool:
    return label_path.exists() and bool(label_path.read_text(encoding="utf-8").strip())


def pick_best_box(result) -> tuple[list[float], float] | None:
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return None

    best_box = None
    best_score = -1.0
    for box in boxes:
        xyxy = box.xyxy[0].tolist()
        area = max(0.0, xyxy[2] - xyxy[0]) * max(0.0, xyxy[3] - xyxy[1])
        conf = float(box.conf[0])
        score = area * conf
        if score > best_score:
            best_score = score
            best_box = (xyxy, conf)
    return best_box


def fallback_bbox(image_path: Path) -> tuple[float, float, float, float]:
    image = cv2.imread(str(image_path))
    if image is None:
        return 0.5, 0.5, 0.65, 0.75

    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (7, 7), 0)
    edges = cv2.Canny(blur, 40, 120)
    kernel = np.ones((7, 7), np.uint8)
    mask = cv2.dilate(edges, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_rect = None
    best_score = -1.0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 0.01 * w * h:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        cx = x + bw / 2
        cy = y + bh / 2
        center_score = 1.0 - (abs(cx - w / 2) / (w / 2) + abs(cy - h / 2) / (h / 2)) / 2
        score = area * max(0.1, center_score)
        if score > best_score:
            best_score = score
            best_rect = (x, y, x + bw, y + bh)

    if best_rect is None:
        return 0.5, 0.5, 0.65, 0.75

    x1, y1, x2, y2 = best_rect
    pad_x = 0.08 * (x2 - x1)
    pad_y = 0.08 * (y2 - y1)
    x1 = max(0.0, x1 - pad_x)
    y1 = max(0.0, y1 - pad_y)
    x2 = min(float(w), x2 + pad_x)
    y2 = min(float(h), y2 + pad_y)
    return xyxy_to_yolo([x1, y1, x2, y2], w, h)


def label_split(
    model: YOLO,
    image_dir: Path,
    label_dir: Path,
    conf: float,
    imgsz: int,
    device: str,
    only_missing: bool,
) -> tuple[int, int, list[str]]:
    label_dir.mkdir(parents=True, exist_ok=True)
    labeled = 0
    skipped = 0
    skipped_names: list[str] = []

    images = sorted(p for p in image_dir.glob("*") if p.is_file())
    pending = []
    for image_path in images:
        label_path = label_dir / f"{image_path.stem}.txt"
        if only_missing and has_label(label_path):
            continue
        pending.append(image_path)

    if not pending:
        return 0, 0, []

    batch_size = 1
    for start in range(0, len(pending), batch_size):
        chunk = pending[start : start + batch_size]
        results = model.predict(
            source=[str(p) for p in chunk],
            conf=conf,
            imgsz=imgsz,
            device=device,
            verbose=False,
        )
        for image_path, result in zip(chunk, results, strict=True):
            label_path = label_dir / f"{image_path.stem}.txt"
            picked = pick_best_box(result)
            if picked is None:
                skipped += 1
                skipped_names.append(image_path.name)
                label_path.write_text("", encoding="utf-8")
                continue

            xyxy, _ = picked
            h, w = result.orig_shape
            cx, cy, bw, bh = xyxy_to_yolo(xyxy, w, h)
            write_label(label_path, cx, cy, bw, bh)
            labeled += 1

    return labeled, skipped, skipped_names


def apply_fallback(dataset_root: Path) -> int:
    filled = 0
    for split in ("train", "val"):
        image_dir = dataset_root / "images" / split
        label_dir = dataset_root / "labels" / split
        for image_path in sorted(p for p in image_dir.glob("*") if p.is_file()):
            label_path = label_dir / f"{image_path.stem}.txt"
            if has_label(label_path):
                continue
            cx, cy, bw, bh = fallback_bbox(image_path)
            write_label(label_path, cx, cy, bw, bh)
            filled += 1
    return filled


def collect_skipped(dataset_root: Path) -> list[str]:
    skipped: list[str] = []
    for split in ("train", "val"):
        image_dir = dataset_root / "images" / split
        label_dir = dataset_root / "labels" / split
        for image_path in sorted(p for p in image_dir.glob("*") if p.is_file()):
            label_path = label_dir / f"{image_path.stem}.txt"
            if not has_label(label_path):
                skipped.append(f"{split}/{image_path.name}")
    return skipped


def run_labeling(
    dataset_root: Path,
    model_name: str,
    conf: float,
    imgsz: int,
    device: str,
    only_missing: bool,
) -> tuple[int, int]:
    model = YOLO(model_name)
    model.set_classes(PROMPTS)

    total_labeled = 0
    total_skipped = 0
    for split in ("train", "val"):
        labeled, skipped, _ = label_split(
            model,
            dataset_root / "images" / split,
            dataset_root / "labels" / split,
            conf=conf,
            imgsz=imgsz,
            device=device,
            only_missing=only_missing,
        )
        total_labeled += labeled
        total_skipped += skipped
        print(f"{split}: labeled={labeled} skipped={skipped}")
    return total_labeled, total_skipped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "datasets" / "gun",
    )
    parser.add_argument("--model", default="yolov8s-worldv2.pt")
    parser.add_argument("--conf", type=float, default=0.05)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    for conf in [args.conf, 0.03]:
        labeled, skipped = run_labeling(
            dataset_root,
            args.model,
            conf,
            args.imgsz,
            args.device,
            only_missing=True,
        )
        print(f"pass conf={conf}: labeled={labeled} skipped={skipped}")
        if skipped == 0:
            break

    fallback_count = apply_fallback(dataset_root)
    if fallback_count:
        print(f"fallback_labels={fallback_count}")

    skipped = collect_skipped(dataset_root)
    skipped_path = dataset_root / "skipped.txt"
    skipped_path.write_text("\n".join(skipped) + ("\n" if skipped else ""), encoding="utf-8")
    total = sum(1 for p in (dataset_root / "images").rglob("*") if p.is_file())
    labeled_total = total - len(skipped)
    print(f"final_labeled={labeled_total} final_skipped={len(skipped)} total={total}")


if __name__ == "__main__":
    main()
