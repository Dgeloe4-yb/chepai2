"""Draw random label previews for quick QC."""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import cv2


def draw_preview(image_path: Path, label_path: Path, out_path: Path) -> bool:
    image = cv2.imread(str(image_path))
    if image is None:
        return False

    h, w = image.shape[:2]
    if label_path.exists() and label_path.read_text(encoding="utf-8").strip():
        for line in label_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            _, cx, cy, bw, bh = map(float, parts)
            x1 = int((cx - bw / 2) * w)
            y1 = int((cy - bh / 2) * h)
            x2 = int((cx + bw / 2) * w)
            y2 = int((cy + bh / 2) * h)
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 3)
            cv2.putText(image, "gun", (x1, max(30, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
    else:
        cv2.putText(image, "NO LABEL", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), image)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "datasets" / "gun",
    )
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    preview_dir = dataset_root / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[tuple[Path, Path]] = []
    for split in ("train", "val"):
        image_dir = dataset_root / "images" / split
        label_dir = dataset_root / "labels" / split
        for image_path in sorted(image_dir.glob("*")):
            if image_path.is_file():
                candidates.append((image_path, label_dir / f"{image_path.stem}.txt"))

    rng = random.Random(args.seed)
    sample = rng.sample(candidates, k=min(args.count, len(candidates)))
    saved = 0
    for image_path, label_path in sample:
        out_path = preview_dir / f"{image_path.parent.name}_{image_path.name}"
        if draw_preview(image_path, label_path, out_path):
            saved += 1

    print(f"Saved {saved} previews to {preview_dir}")


if __name__ == "__main__":
    main()
