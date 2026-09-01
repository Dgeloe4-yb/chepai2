"""Backup existing auto labels before manual re-annotation."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


def backup_labels(dataset_root: Path) -> Path:
    dataset_root = dataset_root.resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = dataset_root / f"labels_backup_{stamp}"
    for split in ("train", "val"):
        src = dataset_root / "labels" / split
        if not src.exists():
            continue
        dst = backup_root / split
        shutil.copytree(src, dst)
    if not backup_root.exists():
        raise SystemExit("没有找到可备份的标签目录")
    print(f"labels backed up to {backup_root}")
    return backup_root


def main() -> None:
    parser = argparse.ArgumentParser(description="备份当前自动标注标签")
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "datasets" / "gun",
    )
    args = parser.parse_args()
    backup_labels(args.dataset_root)


if __name__ == "__main__":
    main()
