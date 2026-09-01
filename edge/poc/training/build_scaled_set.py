"""Shrink labeled objects in-frame to simulate far / small-target scenes."""

from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def parse_labels(text: str) -> list[tuple[int, float, float, float, float]]:
    rows: list[tuple[int, float, float, float, float]] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        cls, cx, cy, bw, bh = parts
        rows.append((int(float(cls)), float(cx), float(cy), float(bw), float(bh)))
    return rows


def format_labels(rows: list[tuple[int, float, float, float, float]]) -> str:
    if not rows:
        return ""
    return "\n".join(f"{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}" for cls, cx, cy, bw, bh in rows) + "\n"


def scale_labels(
    rows: list[tuple[int, float, float, float, float]],
    w: int,
    h: int,
    scale: float,
) -> list[tuple[int, float, float, float, float]]:
    if not rows:
        return []
    cx0, cy0 = w / 2, h / 2
    out: list[tuple[int, float, float, float, float]] = []
    for cls, cx, cy, bw, bh in rows:
        x1 = (cx - bw / 2) * w
        y1 = (cy - bh / 2) * h
        x2 = (cx + bw / 2) * w
        y2 = (cy + bh / 2) * h
        nx1 = cx0 + (x1 - cx0) * scale
        ny1 = cy0 + (y1 - cy0) * scale
        nx2 = cx0 + (x2 - cx0) * scale
        ny2 = cy0 + (y2 - cy0) * scale
        nx1 = max(0.0, min(float(w), nx1))
        ny1 = max(0.0, min(float(h), ny1))
        nx2 = max(0.0, min(float(w), nx2))
        ny2 = max(0.0, min(float(h), ny2))
        if nx2 - nx1 < 2 or ny2 - ny1 < 2:
            continue
        ncx = ((nx1 + nx2) / 2) / w
        ncy = ((ny1 + ny2) / 2) / h
        nbw = (nx2 - nx1) / w
        nbh = (ny2 - ny1) / h
        out.append((cls, ncx, ncy, nbw, nbh))
    return out


def shrink_frame(image: np.ndarray, scale: float) -> np.ndarray:
    h, w = image.shape[:2]
    bg = cv2.GaussianBlur(image, (51, 51), 0)
    bg = cv2.addWeighted(bg, 0.55, np.zeros_like(bg), 0.0, 0)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    small = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    x0 = (w - new_w) // 2
    y0 = (h - new_h) // 2
    out = bg.copy()
    out[y0 : y0 + new_h, x0 : x0 + new_w] = small
    return out


def box_area_sum(rows: list[tuple[int, float, float, float, float]]) -> float:
    return sum(bw * bh for _, _, _, bw, bh in rows)


def draw_boxes(image: np.ndarray, rows: list[tuple[int, float, float, float, float]]) -> np.ndarray:
    canvas = image.copy()
    h, w = canvas.shape[:2]
    for _, cx, cy, bw, bh in rows:
        x1 = int((cx - bw / 2) * w)
        y1 = int((cy - bh / 2) * h)
        x2 = int((cx + bw / 2) * w)
        y2 = int((cy + bh / 2) * h)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 0), 2)
    return canvas


def next_index(image_dir: Path) -> int:
    max_idx = -1
    for path in image_dir.glob("*"):
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        stem = path.stem
        if stem.isdigit():
            max_idx = max(max_idx, int(stem))
    return max_idx + 1


def collect_positive_pairs(dataset_root: Path, split: str) -> list[tuple[Path, Path]]:
    image_dir = dataset_root / "images" / split
    label_dir = dataset_root / "labels" / split
    pairs: list[tuple[Path, Path]] = []
    for image_path in sorted(image_dir.iterdir()):
        if image_path.suffix.lower() not in IMAGE_EXTS:
            continue
        label_path = label_dir / f"{image_path.stem}.txt"
        if label_path.exists() and label_path.read_text(encoding="utf-8").strip():
            pairs.append((image_path, label_path))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="把已标注正样本缩小到画幅中，模拟远景小目标")
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "datasets" / "gun",
    )
    parser.add_argument("--split", choices=("train", "val"), default="train")
    parser.add_argument("--scales", default="0.35,0.5,0.65", help="缩小比例，逗号分隔")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 张，0=全部正样本")
    parser.add_argument("--preview-count", type=int, default=12, help="生成多少组对比预览")
    parser.add_argument("--apply", action="store_true", help="写入 train 集（默认只出预览）")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    scales = [float(x.strip()) for x in args.scales.split(",") if x.strip()]
    pairs = collect_positive_pairs(dataset_root, args.split)
    if args.limit > 0:
        pairs = pairs[: args.limit]
    if not pairs:
        raise SystemExit("没有找到带标注的正样本")

    preview_dir = dataset_root / "previews_scaled"
    preview_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    preview_samples = rng.sample(pairs, k=min(args.preview_count, len(pairs)))

    area_stats: list[tuple[float, float, float]] = []
    generated = 0
    out_pairs: list[tuple[Path, Path]] = []

    for image_path, label_path in pairs:
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        rows = parse_labels(label_path.read_text(encoding="utf-8"))
        if not rows:
            continue
        orig_area = box_area_sum(rows)

        for scale in scales:
            scaled_img = shrink_frame(image, scale)
            scaled_rows = scale_labels(rows, image.shape[1], image.shape[0], scale)
            if not scaled_rows:
                continue
            new_area = box_area_sum(scaled_rows)
            area_stats.append((orig_area, new_area, scale))

            stem = f"scaled_{int(scale * 100):03d}_{image_path.stem}"
            if (image_path, label_path) in preview_samples:
                before = draw_boxes(image, rows)
                after = draw_boxes(scaled_img, scaled_rows)
                combo = np.hstack([before, after])
                cv2.putText(
                    combo,
                    f"{image_path.name}  scale={scale:.2f}  area {orig_area:.2f}->{new_area:.2f}",
                    (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.imwrite(str(preview_dir / f"{stem}.jpg"), combo)

            if args.apply and args.split == "train":
                out_pairs.append((scaled_img, scaled_rows, scale, image_path.suffix.lower()))

    if args.apply and args.split == "train":
        image_dir = dataset_root / "images" / "train"
        label_dir = dataset_root / "labels" / "train"
        idx = next_index(image_dir)
        for scaled_img, scaled_rows, scale, suffix in out_pairs:
            name = f"{idx:05d}{suffix}"
            cv2.imwrite(str(image_dir / name), scaled_img)
            (label_dir / f"{idx:05d}.txt").write_text(format_labels(scaled_rows), encoding="utf-8")
            idx += 1
            generated += 1

    if area_stats:
        orig_mean = sum(x[0] for x in area_stats) / len(area_stats)
        new_mean = sum(x[1] for x in area_stats) / len(area_stats)
        print(f"pairs={len(pairs)} scales={scales}")
        print(f"avg box area: {orig_mean:.3f} -> {new_mean:.3f} ({new_mean / orig_mean:.1%} of original)")
        print(f"previews saved to {preview_dir}")
        if args.apply:
            print(f"added {generated} scaled samples to train")
        else:
            print("dry-run only; add --apply to import into train")


if __name__ == "__main__":
    main()
