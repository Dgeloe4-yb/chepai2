"""Convert CCPD2019 (blue) + CCPD-Green (green) into YOLO plate_color dataset."""

from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

import cv2

from ccpd_utils import iter_ccpd_images, parse_ccpd_bbox, to_yolo_line

CLASS_BLUE = 0
CLASS_GREEN = 1

CCPD2019_SUBSETS = (
    "ccpd_base",
    "ccpd_blur",
    "ccpd_challenge",
    "ccpd_db",
    "ccpd_fn",
    "ccpd_rotate",
    "ccpd_tilt",
    "ccpd_weather",
)


def write_dataset_yaml(dataset_root: Path) -> None:
    dataset_root.joinpath("dataset.yaml").write_text(
        "\n".join(
            [
                f"path: {dataset_root.as_posix()}",
                "train: images/train",
                "val: images/val",
                "names:",
                "  0: plate_blue",
                "  1: plate_green",
                "",
            ]
        ),
        encoding="utf-8",
    )


def collect_sources(ccpd2019_root: Path, ccpd2020_root: Path, subsets: tuple[str, ...]) -> list[tuple[Path, int]]:
    items: list[tuple[Path, int]] = []
    for subset in subsets:
        subset_dir = ccpd2019_root / subset
        if subset_dir.exists():
            items.extend((p, CLASS_BLUE) for p in iter_ccpd_images(subset_dir))
    green_root = ccpd2020_root / "ccpd_green"
    if green_root.exists():
        items.extend((p, CLASS_GREEN) for p in iter_ccpd_images(green_root))
    return items


def convert_one(src: Path, class_id: int) -> tuple[str, str] | None:
    image = cv2.imread(str(src))
    if image is None:
        return None
    h, w = image.shape[:2]
    try:
        x1, y1, x2, y2 = parse_ccpd_bbox(src.stem)
    except ValueError:
        return None
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    label = to_yolo_line(class_id, x1, y1, x2, y2, w, h)
    return label, f"{src.suffix.lower()}"


def main() -> None:
    parser = argparse.ArgumentParser(description="CCPD 自动转 YOLO 蓝牌/绿牌数据集")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument(
        "--ccpd2019-root",
        type=Path,
        default=Path(__file__).resolve().parents[4] / "data" / "CCPD2019",
    )
    parser.add_argument(
        "--ccpd2020-root",
        type=Path,
        default=Path(__file__).resolve().parents[4] / "data" / "CCPD2020",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "datasets" / "plate_color",
    )
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-per-class", type=int, default=10000, help="每类最多采样数，0=不限制")
    parser.add_argument(
        "--subsets",
        default=",".join(CCPD2019_SUBSETS),
        help="CCPD2019 子集，逗号分隔",
    )
    args = parser.parse_args()

    subsets = tuple(s.strip() for s in args.subsets.split(",") if s.strip())
    ccpd2019_root = args.ccpd2019_root.resolve()
    ccpd2020_root = args.ccpd2020_root.resolve()
    dataset_root = args.dataset_root.resolve()

    sources = collect_sources(ccpd2019_root, ccpd2020_root, subsets)
    if not sources:
        raise SystemExit(
            "未找到 CCPD 图片。请先运行:\n"
            f"  python training/plate_color/download_datasets.py\n"
            f"或手动解压到:\n"
            f"  {ccpd2019_root}\n"
            f"  {ccpd2020_root / 'ccpd_green'}"
        )

    rng = random.Random(args.seed)
    by_class: dict[int, list[Path]] = {CLASS_BLUE: [], CLASS_GREEN: []}
    for path, class_id in sources:
        by_class[class_id].append(path)
    for class_id, paths in by_class.items():
        rng.shuffle(paths)
        if args.max_per_class > 0:
            by_class[class_id] = paths[: args.max_per_class]

    for class_id, paths in by_class.items():
        rng.shuffle(paths)
        if args.max_per_class > 0:
            by_class[class_id] = paths[: args.max_per_class]

    train_items: list[tuple[Path, int]] = []
    val_items: list[tuple[Path, int]] = []
    for class_id, paths in by_class.items():
        if not paths:
            continue
        val_count = max(1, int(len(paths) * args.val_ratio))
        val_items.extend((p, class_id) for p in paths[:val_count])
        train_items.extend((p, class_id) for p in paths[val_count:])
    rng.shuffle(train_items)
    rng.shuffle(val_items)

    for split in ("train", "val"):
        for sub in ("images", "labels"):
            target = dataset_root / sub / split
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=True)

    stats = {"train": 0, "val": 0, "skipped": 0, "blue": 0, "green": 0}

    def ingest(items: list[tuple[Path, int]], split: str) -> None:
        image_dir = dataset_root / "images" / split
        label_dir = dataset_root / "labels" / split
        for idx, (src, class_id) in enumerate(items):
            converted = convert_one(src, class_id)
            if converted is None:
                stats["skipped"] += 1
                continue
            label, suffix = converted
            dst_name = f"{idx:06d}{suffix}"
            shutil.copy2(src, image_dir / dst_name)
            (label_dir / f"{idx:06d}.txt").write_text(label + "\n", encoding="utf-8")
            stats[split] += 1
            if class_id == CLASS_BLUE:
                stats["blue"] += 1
            else:
                stats["green"] += 1

    ingest(train_items, "train")
    ingest(val_items, "val")
    write_dataset_yaml(dataset_root)

    manifest = dataset_root / "manifest.txt"
    manifest.write_text(
        "\n".join(
            [
                f"train={stats['train']} val={stats['val']} skipped={stats['skipped']}",
                f"plate_blue={stats['blue']} plate_green={stats['green']}",
                f"ccpd2019={ccpd2019_root}",
                f"ccpd2020={ccpd2020_root}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Prepared plate_color dataset at {dataset_root}")
    print(manifest.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
