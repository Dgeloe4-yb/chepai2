"""Add background / hard-negative samples to reduce false positives."""

from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

import cv2

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def parse_yolo_boxes(label_path: Path, w: int, h: int) -> list[tuple[int, int, int, int]]:
    if not label_path.exists() or not label_path.read_text(encoding="utf-8").strip():
        return []
    boxes: list[tuple[int, int, int, int]] = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        _, cx, cy, bw, bh = map(float, parts)
        x1 = int((cx - bw / 2) * w)
        y1 = int((cy - bh / 2) * h)
        x2 = int((cx + bw / 2) * w)
        y2 = int((cy + bh / 2) * h)
        boxes.append((x1, y1, x2, y2))
    return boxes


def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def random_background_crop(
    image: cv2.Mat, gun_boxes: list[tuple[int, int, int, int]], max_iou: float
) -> cv2.Mat | None:
    h, w = image.shape[:2]
    min_side = min(h, w)
    crop_size = random.randint(int(0.35 * min_side), int(0.85 * min_side))
    for _ in range(40):
        x1 = random.randint(0, max(0, w - crop_size))
        y1 = random.randint(0, max(0, h - crop_size))
        x2, y2 = x1 + crop_size, y1 + crop_size
        patch_box = (x1, y1, x2, y2)
        if all(iou(patch_box, gun) <= max_iou for gun in gun_boxes):
            return image[y1:y2, x1:x2].copy()
    return None


def import_external_negatives(src_dir: Path, dst_image_dir: Path, dst_label_dir: Path, prefix: str) -> int:
    if not src_dir.exists():
        return 0
    count = 0
    existing = len(list(dst_image_dir.glob(f"{prefix}_*.jpg")))
    for idx, src in enumerate(sorted(p for p in src_dir.rglob("*") if p.suffix.lower() in IMAGE_EXTS)):
        dst_name = f"{prefix}_{existing + idx:05d}.jpg"
        image = cv2.imread(str(src))
        if image is None:
            continue
        cv2.imwrite(str(dst_image_dir / dst_name), image)
        (dst_label_dir / f"{dst_name.replace('.jpg', '.txt')}").write_text("", encoding="utf-8")
        count += 1
    return count


def mine_from_split(
    image_dir: Path,
    label_dir: Path,
    dst_image_dir: Path,
    dst_label_dir: Path,
    per_image: int,
    seed: int,
) -> int:
    rng = random.Random(seed)
    images = sorted(p for p in image_dir.glob("*") if p.suffix.lower() in IMAGE_EXTS)
    rng.shuffle(images)
    saved = 0
    for image_path in images:
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        h, w = image.shape[:2]
        label_path = label_dir / f"{image_path.stem}.txt"
        gun_boxes = parse_yolo_boxes(label_path, w, h)
        if not gun_boxes:
            continue
        for _ in range(per_image):
            crop = random_background_crop(image, gun_boxes, max_iou=0.05)
            if crop is None:
                continue
            name = f"neg_mined_{saved:05d}.jpg"
            cv2.imwrite(str(dst_image_dir / name), crop)
            (dst_label_dir / f"neg_mined_{saved:05d}.txt").write_text("", encoding="utf-8")
            saved += 1
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "datasets" / "gun",
    )
    parser.add_argument(
        "--external-root",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "负样本",
        help="可选：手动放入误检场景照片（无标注）",
    )
    parser.add_argument("--per-image", type=int, default=2, help="每张正样本图挖掘多少背景负样本")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    train_image_dir = dataset_root / "images" / "train"
    train_label_dir = dataset_root / "labels" / "train"

    for old in train_image_dir.glob("neg_*"):
        old.unlink(missing_ok=True)
    for old in train_label_dir.glob("neg_*"):
        old.unlink(missing_ok=True)

    mined = mine_from_split(
        train_image_dir,
        train_label_dir,
        train_image_dir,
        train_label_dir,
        per_image=args.per_image,
        seed=args.seed,
    )
    external = import_external_negatives(
        args.external_root,
        train_image_dir,
        train_label_dir,
        prefix="neg_ext",
    )

    print(f"mined_negatives={mined} external_negatives={external} total_added={mined + external}")
    if external == 0 and not args.external_root.exists():
        print(f"提示：可将误检场景照片放到 {args.external_root} 后重新运行本脚本")


if __name__ == "__main__":
    main()
