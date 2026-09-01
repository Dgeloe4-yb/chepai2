"""Parse CCPD / CCPD-Green filenames into YOLO boxes."""

from __future__ import annotations

from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def parse_ccpd_bbox(stem: str) -> tuple[int, int, int, int]:
    """Return x1, y1, x2, y2 from a CCPD image filename stem."""
    parts = stem.split("-")
    if len(parts) < 3:
        raise ValueError(f"invalid CCPD filename: {stem}")
    bbox_part = parts[2].split("_")
    if len(bbox_part) < 2:
        raise ValueError(f"invalid CCPD bbox field: {stem}")
    x1, y1 = map(int, bbox_part[0].split("&"))
    x2, y2 = map(int, bbox_part[1].split("&"))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def to_yolo_line(class_id: int, x1: int, y1: int, x2: int, y2: int, img_w: int, img_h: int) -> str:
    x1 = max(0, min(img_w - 1, x1))
    x2 = max(0, min(img_w - 1, x2))
    y1 = max(0, min(img_h - 1, y1))
    y2 = max(0, min(img_h - 1, y2))
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    cx = ((x1 + x2) / 2) / img_w
    cy = ((y1 + y2) / 2) / img_h
    return f"{class_id} {cx:.6f} {cy:.6f} {bw / img_w:.6f} {bh / img_h:.6f}"


def iter_ccpd_images(root: Path) -> list[Path]:
    images: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            images.append(path)
    return sorted(images)
