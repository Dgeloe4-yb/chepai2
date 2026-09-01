"""Capture webcam frames as hard-negative training samples."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import cv2


def main() -> None:
    parser = argparse.ArgumentParser(description="按 s 保存当前摄像头画面为负样本")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "负样本",
    )
    args = parser.parse_args()

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit(f"无法打开摄像头 {args.camera}")

    print(f"负样本保存目录: {out_dir}")
    print("按 s 保存当前帧，按 q 退出")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        preview = frame.copy()
        cv2.putText(
            preview,
            "s=save negative   q=quit",
            (16, 36),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.imshow("capture-negative", preview)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            name = datetime.now().strftime("neg_%Y%m%d_%H%M%S_%f.jpg")
            path = out_dir / name
            cv2.imwrite(str(path), frame)
            print(f"saved {path}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
