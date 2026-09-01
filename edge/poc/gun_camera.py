"""Open camera and show mini-ad detections in real time."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


def fit_display(image: np.ndarray, max_width: int, max_height: int) -> np.ndarray:
    """Scale for imshow while keeping aspect ratio (avoid stretched/cropped window)."""
    h, w = image.shape[:2]
    if w <= max_width and h <= max_height:
        return image
    scale = min(max_width / w, max_height / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def open_capture(source: str | int) -> cv2.VideoCapture:
    if isinstance(source, str) and source.startswith(("rtsp://", "http://", "https://")):
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap
    return cv2.VideoCapture(source)


def main() -> None:
    parser = argparse.ArgumentParser(description="摄像头实时识别小广告")
    parser.add_argument("--source", default="", help="视频源：摄像头索引、RTSP/HTTP 地址或文件路径")
    parser.add_argument("--camera", type=int, default=0, help="未指定 --source 时使用的摄像头索引，默认 0")
    parser.add_argument(
        "--weights",
        type=Path,
        default=Path(__file__).resolve().parent / "weights" / "mini_ad.pt",
    )
    parser.add_argument("--conf", type=float, default=0.35, help="置信度阈值")
    parser.add_argument("--device", default="0", help="0=GPU, cpu=CPU")
    parser.add_argument("--display-width", type=int, default=1280, help="预览窗口最大宽度")
    parser.add_argument("--display-height", type=int, default=720, help="预览窗口最大高度")
    args = parser.parse_args()

    if not args.weights.exists():
        raise SystemExit(f"找不到模型: {args.weights}")

    model = YOLO(str(args.weights))
    source: str | int = args.source if args.source else args.camera
    cap = open_capture(source)
    if not cap.isOpened():
        raise SystemExit(f"无法打开视频源: {source}")

    ok, frame = cap.read()
    if not ok or frame is None:
        raise SystemExit(f"无法读取视频源首帧: {source}")
    src_h, src_w = frame.shape[:2]
    print(
        f"视频源已打开: {source}\n"
        f"原始分辨率: {src_w}x{src_h}，预览缩放至 {args.display_width}x{args.display_height} 内\n"
        f"模型: {args.weights.name}，按 q 退出"
    )

    cv2.namedWindow("mini-ad-camera", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("mini-ad-camera", min(args.display_width, src_w), min(args.display_height, src_h))

    while True:
        result = model.predict(frame, conf=args.conf, device=args.device, verbose=False)[0]
        annotated = result.plot()
        count = 0 if result.boxes is None else len(result.boxes)

        label = f"mini_ad: {count}" if count else "mini_ad: none"
        color = (0, 255, 0) if count else (0, 0, 255)
        cv2.putText(
            annotated,
            label,
            (16, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            color,
            3,
            cv2.LINE_AA,
        )

        display = fit_display(annotated, args.display_width, args.display_height)
        cv2.imshow("mini-ad-camera", display)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

        ok, frame = cap.read()
        if not ok:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
