"""Convert downloaded VOC / YOLO ad datasets into unified YOLO mini_ad training set on D:."""

from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

from voc_utils import IMAGE_EXTS, find_image_for_stem, load_yolo_class_names, read_yolo_label, voc_xml_to_yolo_lines


def write_dataset_yaml(dataset_root: Path) -> None:
    dataset_root.joinpath("dataset.yaml").write_text(
        "\n".join(
            [
                f"path: {dataset_root.as_posix()}",
                "train: images/train",
                "val: images/val",
                "names:",
                "  0: mini_ad",
                "",
            ]
        ),
        encoding="utf-8",
    )


def collect_voc_pairs(raw_root: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for xml_path in sorted(raw_root.rglob("*.xml")):
        if xml_path.name.lower() in {"classes.xml", "annotations.xml"}:
            continue
        img_dir = xml_path.parent
        img = find_image_for_stem(img_dir, xml_path.stem)
        if img is None:
            for sub in ("images", "JPEGImages"):
                for ext in IMAGE_EXTS:
                    alt = img_dir / sub / f"{xml_path.stem}{ext}"
                    if alt.is_file():
                        img = alt
                        break
                if img:
                    break
        if img is None:
            continue
        pairs.append((img, xml_path))
    return pairs


def collect_yolo_pairs(raw_root: Path) -> list[tuple[Path, Path, list[str]]]:
    pairs: list[tuple[Path, Path, list[str]]] = []
    class_names = load_yolo_class_names(raw_root)

    # Standard Roboflow / ultralytics layout: train/images + train/labels
    for split in ("train", "valid", "val", "test"):
        for img_dir in raw_root.rglob(split):
            if img_dir.name != "images" or img_dir.parent.name not in {"train", "valid", "val", "test"}:
                continue
            label_dir = img_dir.parent / "labels"
            if not label_dir.is_dir():
                continue
            local_names = load_yolo_class_names(img_dir.parent) or class_names
            for img in sorted(img_dir.rglob("*")):
                if img.suffix.lower() not in IMAGE_EXTS:
                    continue
                lbl = label_dir / f"{img.stem}.txt"
                lines = read_yolo_label(lbl, local_names)
                if lines:
                    pairs.append((img, lbl, lines))

    # Flat images/ + labels/ at root (building facades)
    for img_root in raw_root.rglob("images"):
        if not img_root.is_dir():
            continue
        label_root = img_root.parent / "labels"
        if not label_root.is_dir():
            continue
        local_names = load_yolo_class_names(img_root.parent) or class_names
        for sub in ("train", "test", "val", ""):
            scan = img_root / sub if sub else img_root
            if not scan.is_dir():
                continue
            lbl_scan = label_root / sub if sub else label_root
            for img in sorted(scan.rglob("*")):
                if img.suffix.lower() not in IMAGE_EXTS:
                    continue
                lbl = lbl_scan / f"{img.stem}.txt"
                lines = read_yolo_label(lbl, local_names)
                if lines:
                    pairs.append((img, lbl, lines))

    return pairs


def copy_sample(
    img: Path,
    label_lines: list[str],
    dataset_root: Path,
    split: str,
    stem: str,
) -> bool:
    if not label_lines:
        return False
    img_out = dataset_root / "images" / split / f"{stem}{img.suffix.lower()}"
    lbl_out = dataset_root / "labels" / split / f"{stem}.txt"
    img_out.parent.mkdir(parents=True, exist_ok=True)
    lbl_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(img, img_out)
    lbl_out.write_text("\n".join(label_lines) + "\n", encoding="utf-8")
    return True


def ingest_raw_dir(raw_sub: Path, prefix: str) -> list[tuple[Path, list[str], str]]:
    out: list[tuple[Path, list[str], str]] = []
    seen: set[str] = set()

    for img, xml_path in collect_voc_pairs(raw_sub):
        key = f"{prefix}_{xml_path.stem}"
        if key in seen:
            continue
        _, _, lines = voc_xml_to_yolo_lines(xml_path)
        if lines:
            out.append((img, lines, key))
            seen.add(key)

    for img, _lbl, lines in collect_yolo_pairs(raw_sub):
        key = f"{prefix}_{img.stem}"
        if key in seen:
            continue
        out.append((img, lines, key))
        seen.add(key)

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="准备小广告 YOLO 数据集（多源 → 单类 mini_ad）")
    parser.add_argument("--work-root", type=Path, default=Path("D:/chepai2_train/mini_ad"))
    parser.add_argument("--raw-root", type=Path, default=None)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-samples", type=int, default=0)
    args = parser.parse_args()

    work_root = args.work_root.resolve()
    raw_root = (args.raw_root or work_root / "raw").resolve()
    dataset_root = work_root / "datasets" / "mini_ad"

    if not raw_root.is_dir():
        raise SystemExit(f"未找到原始数据: {raw_root}\n请先运行 download_mini_ad.bat --all")

    samples: list[tuple[Path, list[str], str]] = []
    subs = sorted(p for p in raw_root.iterdir() if p.is_dir())
    if subs:
        for sub in subs:
            samples.extend(ingest_raw_dir(sub, sub.name))
    else:
        samples.extend(ingest_raw_dir(raw_root, "raw"))

    if not samples:
        raise SystemExit(
            f"在 {raw_root} 下未找到可用标注。\n"
            "请运行 download_mini_ad.bat --all 或手动解压 FIRC 数据到 raw/"
        )

    if args.max_samples > 0 and len(samples) > args.max_samples:
        random.Random(args.seed).shuffle(samples)
        samples = samples[: args.max_samples]

    rng = random.Random(args.seed)
    rng.shuffle(samples)
    val_n = max(1, int(len(samples) * args.val_ratio))
    val_set = samples[:val_n]
    train_set = samples[val_n:]

    for split in ("train", "val"):
        for p in (dataset_root / "images" / split, dataset_root / "labels" / split):
            if p.exists():
                shutil.rmtree(p)

    for split_name, subset in (("train", train_set), ("val", val_set)):
        kept = 0
        for img, lines, stem in subset:
            if copy_sample(img, lines, dataset_root, split_name, stem):
                kept += 1
        print(f"{split_name}: {kept} images")

    write_dataset_yaml(dataset_root)
    print(f"dataset ready: {dataset_root / 'dataset.yaml'}")
    print(f"total={len(samples)} train={len(train_set)} val={len(val_set)}")


if __name__ == "__main__":
    main()
