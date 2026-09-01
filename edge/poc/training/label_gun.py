"""Interactive YOLO bbox labeling tool for the charging-gun dataset."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
CLASS_ID = 0
WINDOW = "label-gun"


@dataclass
class Box:
    x1: int
    y1: int
    x2: int
    y2: int

    def normalized(self, w: int, h: int) -> tuple[float, float, float, float]:
        x1, x2 = sorted((self.x1, self.x2))
        y1, y2 = sorted((self.y1, self.y2))
        x1 = max(0, min(w - 1, x1))
        x2 = max(0, min(w - 1, x2))
        y1 = max(0, min(h - 1, y1))
        y2 = max(0, min(h - 1, y2))
        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)
        cx = (x1 + x2) / 2 / w
        cy = (y1 + y2) / 2 / h
        return cx, cy, bw / w, bh / h

    @classmethod
    def from_normalized(cls, cx: float, cy: float, bw: float, bh: float, w: int, h: int) -> Box:
        px = cx * w
        py = cy * h
        pw = bw * w
        ph = bh * h
        return cls(int(px - pw / 2), int(py - ph / 2), int(px + pw / 2), int(py + ph / 2))


def list_images(image_dir: Path) -> list[Path]:
    return sorted(
        p for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )


def load_boxes(label_path: Path, w: int, h: int) -> list[Box]:
    if not label_path.exists():
        return []
    boxes: list[Box] = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        _, cx, cy, bw, bh = map(float, parts)
        boxes.append(Box.from_normalized(cx, cy, bw, bh, w, h))
    return boxes


def save_boxes(label_path: Path, boxes: list[Box], w: int, h: int) -> None:
    label_path.parent.mkdir(parents=True, exist_ok=True)
    if not boxes:
        label_path.write_text("", encoding="utf-8")
        return
    lines = []
    for box in boxes:
        cx, cy, bw, bh = box.normalized(w, h)
        lines.append(f"{CLASS_ID} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    label_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fit_display(image: np.ndarray, max_w: int, max_h: int) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    if scale >= 1.0:
        return image.copy(), 1.0
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA), scale


def to_image_point(x: int, y: int, scale: float) -> tuple[int, int]:
    inv = 1.0 / scale
    return int(x * inv), int(y * inv)


class LabelApp:
    def __init__(
        self,
        image_paths: list[Path],
        label_paths: list[Path],
        start_index: int,
        max_display_w: int,
        max_display_h: int,
        progress_path: Path | None,
    ) -> None:
        if len(image_paths) != len(label_paths):
            raise ValueError("image_paths and label_paths length mismatch")
        if not image_paths:
            raise ValueError("no images to label")

        self.image_paths = image_paths
        self.label_paths = label_paths
        self.index = max(0, min(start_index, len(image_paths) - 1))
        self.max_display_w = max_display_w
        self.max_display_h = max_display_h
        self.progress_path = progress_path

        self.image: np.ndarray | None = None
        self.display: np.ndarray | None = None
        self.scale = 1.0
        self.boxes: list[Box] = []
        self.draft: Box | None = None
        self.dragging = False
        self.dirty = False
        self.status = ""

        self.load_current()

    def load_current(self) -> None:
        path = self.image_paths[self.index]
        image = cv2.imread(str(path))
        if image is None:
            raise SystemExit(f"无法读取图片: {path}")
        self.image = image
        h, w = image.shape[:2]
        self.boxes = load_boxes(self.label_paths[self.index], w, h)
        self.draft = None
        self.dragging = False
        self.dirty = False
        self.refresh_display()
        self.set_status(f"已加载 {path.name}")

    def set_status(self, msg: str) -> None:
        self.status = msg

    def refresh_display(self) -> None:
        assert self.image is not None
        canvas = self.image.copy()
        for box in self.boxes:
            cv2.rectangle(canvas, (box.x1, box.y1), (box.x2, box.y2), (0, 255, 0), 2)
            cv2.putText(
                canvas,
                "gun",
                (box.x1, max(20, box.y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
        if self.draft is not None:
            cv2.rectangle(canvas, (self.draft.x1, self.draft.y1), (self.draft.x2, self.draft.y2), (255, 200, 0), 2)

        total = len(self.image_paths)
        name = self.image_paths[self.index].name
        split_hint = "负样本" if not self.boxes else f"{len(self.boxes)} 框"
        header = f"[{self.index + 1}/{total}] {name}  {split_hint}"
        cv2.putText(canvas, header, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, header, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 1, cv2.LINE_AA)

        help_text = "拖动画框 | s保存 | n下一张 | p上一张 | d删最后 | c清空 | u撤销 | q退出"
        cv2.putText(canvas, help_text, (12, canvas.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, help_text, (12, canvas.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
        if self.status:
            cv2.putText(canvas, self.status, (12, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2, cv2.LINE_AA)

        self.display, self.scale = fit_display(canvas, self.max_display_w, self.max_display_h)

    def save_current(self) -> None:
        assert self.image is not None
        h, w = self.image.shape[:2]
        save_boxes(self.label_paths[self.index], self.boxes, w, h)
        self.dirty = False
        self.persist_progress()
        tag = "负样本" if not self.boxes else f"{len(self.boxes)} 框"
        self.set_status(f"已保存 ({tag})")

    def persist_progress(self) -> None:
        if self.progress_path is None:
            return
        payload = {
            "index": self.index,
            "image": self.image_paths[self.index].name,
        }
        self.progress_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def goto(self, new_index: int, autosave: bool = True) -> None:
        if autosave and self.dirty:
            self.save_current()
        self.index = max(0, min(new_index, len(self.image_paths) - 1))
        self.load_current()

    def on_mouse(self, event: int, x: int, y: int, _flags: int, _param: object) -> None:
        if self.image is None:
            return
        ix, iy = to_image_point(x, y, self.scale)
        if event == cv2.EVENT_LBUTTONDOWN:
            self.dragging = True
            self.draft = Box(ix, iy, ix, iy)
        elif event == cv2.EVENT_MOUSEMOVE and self.dragging and self.draft is not None:
            self.draft.x2 = ix
            self.draft.y2 = iy
            self.refresh_display()
            cv2.imshow(WINDOW, self.display)
        elif event == cv2.EVENT_LBUTTONUP and self.dragging and self.draft is not None:
            self.dragging = False
            x1, x2 = sorted((self.draft.x1, self.draft.x2))
            y1, y2 = sorted((self.draft.y1, self.draft.y2))
            if (x2 - x1) >= 4 and (y2 - y1) >= 4:
                self.boxes.append(Box(x1, y1, x2, y2))
                self.dirty = True
            self.draft = None
            self.refresh_display()
            cv2.imshow(WINDOW, self.display)

    def undo(self) -> None:
        if self.boxes:
            self.boxes.pop()
            self.dirty = True
            self.set_status("已撤销最后一个框")

    def delete_last(self) -> None:
        self.undo()

    def clear_boxes(self) -> None:
        self.boxes = []
        self.dirty = True
        self.set_status("已清空（负样本）")

    def run(self) -> None:
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(WINDOW, self.on_mouse)
        while True:
            self.refresh_display()
            cv2.imshow(WINDOW, self.display)
            key = cv2.waitKey(20) & 0xFF
            if key in (ord("q"), 27):
                if self.dirty:
                    self.save_current()
                break
            if key in (ord("s"), 13):
                self.save_current()
            elif key in (ord("n"), ord(" ")):
                self.goto(self.index + 1)
            elif key in (ord("p"), ord("b")):
                self.goto(self.index - 1)
            elif key == ord("d"):
                self.delete_last()
            elif key == ord("c"):
                self.clear_boxes()
            elif key == ord("u"):
                self.undo()
            elif key == ord("g"):
                self.save_current()
                self.goto(min(self.index + 1, len(self.image_paths) - 1), autosave=False)

        cv2.destroyAllWindows()


def collect_dataset_items(dataset_root: Path, split: str) -> tuple[list[Path], list[Path]]:
    image_dir = dataset_root / "images" / split
    label_dir = dataset_root / "labels" / split
    images = list_images(image_dir)
    labels = [label_dir / f"{img.stem}.txt" for img in images]
    return images, labels


def collect_folder_items(image_dir: Path, label_dir: Path | None) -> tuple[list[Path], list[Path]]:
    images = list_images(image_dir)
    out_label_dir = label_dir or (image_dir.parent / "labels" / image_dir.name)
    labels = [out_label_dir / f"{img.stem}.txt" for img in images]
    return images, labels


def filter_items(
    images: list[Path],
    labels: list[Path],
    mode: str,
) -> tuple[list[Path], list[Path]]:
    if mode == "all":
        return images, labels
    filtered_images: list[Path] = []
    filtered_labels: list[Path] = []
    for image, label in zip(images, labels, strict=True):
        has_label = label.exists() and bool(label.read_text(encoding="utf-8").strip())
        if mode == "unlabeled" and has_label:
            continue
        if mode == "labeled" and not has_label:
            continue
        filtered_images.append(image)
        filtered_labels.append(label)
    return filtered_images, filtered_labels


def read_progress(progress_path: Path) -> int:
    if not progress_path.exists():
        return 0
    try:
        data = json.loads(progress_path.read_text(encoding="utf-8"))
        return int(data.get("index", 0))
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="充电枪 YOLO 手动标注工具")
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "datasets" / "gun",
        help="标准 YOLO 数据集根目录",
    )
    parser.add_argument("--split", choices=("train", "val", "both"), default="train", help="标注 train/val/both")
    parser.add_argument("--images", type=Path, default=None, help="自定义图片目录（优先于 --split）")
    parser.add_argument("--labels", type=Path, default=None, help="自定义标签目录，默认与 images 对应")
    parser.add_argument("--filter", choices=("all", "unlabeled", "labeled"), default="all", help="只显示未标注/已标注")
    parser.add_argument("--start", type=int, default=-1, help="起始索引，-1 表示读取上次进度")
    parser.add_argument("--display-width", type=int, default=1400)
    parser.add_argument("--display-height", type=int, default=900)
    args = parser.parse_args()

    if args.images:
        image_paths, label_paths = collect_folder_items(args.images.resolve(), args.labels.resolve() if args.labels else None)
        progress_path = (args.labels or args.images.parent / "labels" / args.images.name).resolve() / ".label_progress.json"
    else:
        dataset_root = args.dataset_root.resolve()
        image_paths: list[Path] = []
        label_paths: list[Path] = []
        splits = ("train", "val") if args.split == "both" else (args.split,)
        for split in splits:
            imgs, labs = collect_dataset_items(dataset_root, split)
            image_paths.extend(imgs)
            label_paths.extend(labs)
        progress_path = dataset_root / ".label_progress.json"

    image_paths, label_paths = filter_items(image_paths, label_paths, args.filter)
    if not image_paths:
        raise SystemExit("没有符合条件的图片。可先运行 import_images.py 导入，或把 --filter 改成 all。")

    start_index = read_progress(progress_path) if args.start < 0 else args.start
    print(
        f"共 {len(image_paths)} 张待标注\n"
        f"保存到对应 labels/*.txt（YOLO 格式，单类 gun）\n"
        f"快捷键: 拖动=画框, s=保存, n/空格=下一张, p=上一张, c=负样本, d/u=删框, q=退出"
    )

    app = LabelApp(
        image_paths=image_paths,
        label_paths=label_paths,
        start_index=start_index,
        max_display_w=args.display_width,
        max_display_h=args.display_height,
        progress_path=progress_path,
    )
    app.run()


if __name__ == "__main__":
    main()
