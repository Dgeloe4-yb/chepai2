"""Collect charging-gun photos into YOLO dataset layout with train/val split."""

from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def find_images(*roots: Path) -> list[Path]:
    images: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
                images.append(path.resolve())
    return sorted(set(images))


def split_items(items: list[Path], val_ratio: float, seed: int) -> tuple[list[Path], list[Path]]:
    rng = random.Random(seed)
    shuffled = items.copy()
    rng.shuffle(shuffled)
    val_count = max(1, int(len(shuffled) * val_ratio))
    val_items = sorted(shuffled[:val_count], key=lambda p: p.name)
    train_items = sorted(shuffled[val_count:], key=lambda p: p.name)
    return train_items, val_items


def copy_split(items: list[Path], dst_dir: Path) -> list[str]:
    dst_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for idx, src in enumerate(items):
        dst_name = f"{idx:05d}{src.suffix.lower()}"
        shutil.copy2(src, dst_dir / dst_name)
        names.append(dst_name)
    return names


def write_dataset_yaml(dataset_root: Path) -> None:
    yaml_path = dataset_root / "dataset.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                f"path: {dataset_root.as_posix()}",
                "train: images/train",
                "val: images/val",
                "names:",
                "  0: gun",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--dataset-root", type=Path, default=Path(__file__).resolve().parents[1] / "datasets" / "gun")
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    source_dirs = [
        args.repo_root / "充电枪采集照片1",
        args.repo_root / "充电枪采集照片2",
    ]
    images = find_images(*source_dirs)
    if not images:
        raise SystemExit(f"No images found under: {source_dirs}")

    dataset_root = args.dataset_root.resolve()
    for sub in ("images/train", "images/val", "labels/train", "labels/val", "previews"):
        (dataset_root / sub).mkdir(parents=True, exist_ok=True)

    train_items, val_items = split_items(images, args.val_ratio, args.seed)
    train_names = copy_split(train_items, dataset_root / "images" / "train")
    val_names = copy_split(val_items, dataset_root / "images" / "val")
    write_dataset_yaml(dataset_root)

    manifest = dataset_root / "manifest.txt"
    manifest.write_text(
        "\n".join(
            [
                f"total={len(images)}",
                f"train={len(train_items)}",
                f"val={len(val_items)}",
                "",
                "[train]",
                *[f"{name}\t{src}" for name, src in zip(train_names, train_items, strict=True)],
                "",
                "[val]",
                *[f"{name}\t{src}" for name, src in zip(val_names, val_items, strict=True)],
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"Prepared dataset at {dataset_root}")
    print(f"train={len(train_items)} val={len(val_items)} total={len(images)}")


if __name__ == "__main__":
    main()
