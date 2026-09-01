"""Import new images into the YOLO dataset for manual labeling."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from prepare_dataset import IMAGE_EXTS, find_images


def next_index(image_dir: Path) -> int:
    max_idx = -1
    for path in image_dir.glob("*"):
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        stem = path.stem
        if stem.isdigit():
            max_idx = max(max_idx, int(stem))
    return max_idx + 1


def import_images(sources: list[Path], dataset_root: Path, split: str, create_empty_labels: bool) -> None:
    dataset_root = dataset_root.resolve()
    image_dir = dataset_root / "images" / split
    label_dir = dataset_root / "labels" / split
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)

    idx = next_index(image_dir)
    imported = 0
    for src in sources:
        dst_name = f"{idx:05d}{src.suffix.lower()}"
        dst_image = image_dir / dst_name
        shutil.copy2(src, dst_image)
        label_path = label_dir / f"{dst_name.rsplit('.', 1)[0]}.txt"
        if create_empty_labels and not label_path.exists():
            label_path.write_text("", encoding="utf-8")
        print(f"imported {src.name} -> {dst_image.name}")
        idx += 1
        imported += 1

    print(f"done: imported {imported} images into {split}")


def main() -> None:
    parser = argparse.ArgumentParser(description="把新图片导入 datasets/gun 以便手动标注")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "datasets" / "gun",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="图片文件或目录，可重复指定。默认导入 负样本/ 目录",
    )
    parser.add_argument("--split", choices=("train", "val"), default="train")
    parser.add_argument("--no-empty-label", action="store_true", help="不创建空标签文件")
    args = parser.parse_args()

    if args.source:
        roots = [Path(p).resolve() for p in args.source]
    else:
        roots = [args.repo_root / "负样本"]

    images: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.lower() in IMAGE_EXTS:
            images.append(root)
        elif root.is_dir():
            images.extend(find_images(root))

    images = sorted(set(images))
    if not images:
        raise SystemExit(f"未找到图片: {roots}")

    import_images(images, args.dataset_root, args.split, create_empty_labels=not args.no_empty_label)


if __name__ == "__main__":
    main()
