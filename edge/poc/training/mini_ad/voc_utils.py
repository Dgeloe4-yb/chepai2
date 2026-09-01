"""Pascal VOC XML → YOLO label helpers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

# Names treated as mini_ad (case-insensitive). Others in multi-class YOLO are skipped.
AD_CLASS_ALIASES = {
    "adv",
    "guanggao",
    "huwaiguanggao",
    "mini_ad",
    "small_ad",
    "sticker_ad",
    "illegal_ad",
    "xiao_guanggao",
    "xiaoguanggao",
    "广告",
    "小广告",
    "banner",
    "billboard",
    "signboard",
    "win_ad",
    "graffiti",
    "bad_billboard",
    "broken_signage",
    "faded_signage",
    "ads",
    "ad",
    "illegal banner",
    "illegal_banner",
}


def find_image_for_stem(folder: Path, stem: str) -> Path | None:
    for ext in IMAGE_EXTS:
        p = folder / f"{stem}{ext}"
        if p.is_file():
            return p
    return None


def parse_voc_xml(xml_path: Path) -> tuple[int, int, list[tuple[str, float, float, float, float]]]:
    root = ET.parse(xml_path).getroot()
    size = root.find("size")
    if size is None:
        raise ValueError(f"missing size: {xml_path}")
    w = int(size.findtext("width", "0"))
    h = int(size.findtext("height", "0"))
    if w <= 0 or h <= 0:
        raise ValueError(f"invalid size in {xml_path}")

    boxes: list[tuple[str, float, float, float, float]] = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip()
        bnd = obj.find("bndbox")
        if not name or bnd is None:
            continue
        x1 = float(bnd.findtext("xmin", "0"))
        y1 = float(bnd.findtext("ymin", "0"))
        x2 = float(bnd.findtext("xmax", "0"))
        y2 = float(bnd.findtext("ymax", "0"))
        if x2 <= x1 or y2 <= y1:
            continue
        boxes.append((name, x1, y1, x2, y2))
    return w, h, boxes


def is_ad_class(name: str) -> bool:
    key = name.strip().lower().replace(" ", "_")
    if key in AD_CLASS_ALIASES or name.strip() in AD_CLASS_ALIASES:
        return True
    return key.replace("-", "_") in AD_CLASS_ALIASES


def to_yolo_line(class_id: int, x1: float, y1: float, x2: float, y2: float, w: int, h: int) -> str:
    xc = ((x1 + x2) / 2.0) / w
    yc = ((y1 + y2) / 2.0) / h
    bw = (x2 - x1) / w
    bh = (y2 - y1) / h
    xc = min(max(xc, 0.0), 1.0)
    yc = min(max(yc, 0.0), 1.0)
    bw = min(max(bw, 0.0), 1.0)
    bh = min(max(bh, 0.0), 1.0)
    return f"{class_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}"


def voc_xml_to_yolo_lines(xml_path: Path) -> tuple[int, int, list[str]]:
    w, h, boxes = parse_voc_xml(xml_path)
    lines: list[str] = []
    for name, x1, y1, x2, y2 in boxes:
        if not is_ad_class(name):
            continue
        lines.append(to_yolo_line(0, x1, y1, x2, y2, w, h))
    return w, h, lines


def load_yolo_class_names(root: Path) -> list[str]:
    candidates = [
        root / "classes.txt",
        root / "labels" / "classes.txt",
        root / "data.yaml",
    ]
    for p in root.rglob("classes.txt"):
        candidates.append(p)
    for path in candidates:
        if not path.is_file():
            continue
        if path.suffix == ".yaml":
            continue
        names = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if names:
            return names
    return []


def read_yolo_label(label_path: Path, class_names: list[str] | None = None) -> list[str]:
    if not label_path.is_file():
        return []
    names = class_names or []
    lines: list[str] = []
    for raw in label_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split()
        if len(parts) < 5:
            continue
        try:
            cls_id = int(float(parts[0]))
        except ValueError:
            continue
        if names:
            if cls_id < 0 or cls_id >= len(names):
                continue
            if not is_ad_class(names[cls_id]):
                continue
        lines.append(" ".join(["0", *parts[1:5]]))
    return lines
