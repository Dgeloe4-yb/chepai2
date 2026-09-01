"""
单路视频 PoC（Windows / Jetson 均可调试）：
- YOLOv8n：车辆检测（整帧）
- plate_color / HyperLPR3：车牌（整帧车辆上）
- mini_ad：小广告（ad ROI 裁剪，无 ROI 则整帧）
- park_align：停正标定（车牌相对车框偏移）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from ultralytics import YOLO

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from edge.shared.mini_ad_detect import detect_mini_ads_in_rois, mini_ad_alerts

from lpr_hyperlpr import (
    create_catcher,
    is_probable_ev_plate,
    is_probable_fuel_plate,
    run_lpr_on_bgr,
)
from roi_rules import RoiRule
from edge.shared.park_align import load_profile, eval_alignment


COCO_VEHICLE = {2: "car", 5: "bus", 7: "truck"}


def plate_roi_from_vehicle(
    xyxy: Sequence[float],
    frame_shape: Tuple[int, int, int],
    margin: float = 0.05,
) -> Tuple[int, int, int, int]:
    """Whole vehicle box (+margin) for plate_color / HSV fallback."""
    x1, y1, x2, y2 = map(float, xyxy)
    bw, bh = x2 - x1, y2 - y1
    H, W = frame_shape[0], frame_shape[1]
    if bw < 2 or bh < 2:
        return int(x1), max(0, int(y2) - 10), int(x2), int(y2)
    dx, dy = margin * bw, margin * bh
    x_lo = max(0, int(x1 - dx))
    y_lo = max(0, int(y1 - dy))
    x_hi = min(W, int(x2 + dx))
    y_hi = min(H, int(y2 + dy))
    if x_hi <= x_lo or y_hi <= y_lo:
        return int(x1), int(y1), int(x2), int(y2)
    return x_lo, y_lo, x_hi, y_hi


def vehicle_crop(frame: np.ndarray, xyxy: Sequence[float], margin: float = 0.22) -> Optional[np.ndarray]:
    """供 HyperLPR3 使用的车辆扩充裁剪。"""
    x1, y1, x2, y2 = map(float, xyxy)
    w, h = x2 - x1, y2 - y1
    if w < 2 or h < 2:
        return None
    H, W = frame.shape[:2]
    dx = margin * w
    dy = margin * h
    nx1 = max(0, int(x1 - dx))
    ny1 = max(0, int(y1 - dy))
    nx2 = min(W, int(x2 + dx))
    ny2 = min(H, int(y2 + dy))
    if nx2 <= nx1 or ny2 <= ny1:
        return None
    return frame[ny1:ny2, nx1:nx2]


def classify_plate_color_hint(bgr: np.ndarray) -> str:
    if bgr.size == 0:
        return "unknown"
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([100, 40, 40])
    upper_blue = np.array([140, 255, 255])
    mask_blue = cv2.inRange(hsv, lower_blue, upper_blue)
    lower_green = np.array([35, 40, 40])
    upper_green = np.array([95, 255, 255])
    mask_green = cv2.inRange(hsv, lower_green, upper_green)
    lower_yellow = np.array([15, 70, 70])
    upper_yellow = np.array([35, 255, 255])
    mask_yellow = cv2.inRange(hsv, lower_yellow, upper_yellow)

    ratios = {
        "blue_plate": float(np.mean(mask_blue > 0)),
        "green_plate": float(np.mean(mask_green > 0)),
        "yellow_plate": float(np.mean(mask_yellow > 0)),
    }
    best = max(ratios, key=ratios.get)  # type: ignore[arg-type]
    if ratios[best] < 0.08:
        return "unknown"
    return best


def load_rois(path: Optional[Path]) -> List[RoiRule]:
    if not path:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rules: List[RoiRule] = []
    for item in data:
        rules.append(
            RoiRule(
                kind=item["kind"],
                polygon=[tuple(p) for p in item["polygon"]],
                normalized=bool(item.get("normalized", False)),
            )
        )
    return rules


def parse_video_source(source: str):
    s = source.strip()
    if s.isdigit():
        return int(s)
    return s


def is_network_stream(source: str | int) -> bool:
    return isinstance(source, str) and source.startswith(("rtsp://", "http://", "https://"))


def open_capture(source: str | int) -> cv2.VideoCapture:
    if is_network_stream(source):
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap
    return cv2.VideoCapture(source)


def mini_ad_predict_fn(model: YOLO):
    def _predict(crop: np.ndarray, conf: float) -> list[tuple[tuple[float, float, float, float], float]]:
        res = model.predict(crop, conf=conf, verbose=False)[0]
        if res.boxes is None:
            return []
        out: list[tuple[tuple[float, float, float, float], float]] = []
        for b in res.boxes:
            xyxy = tuple(float(x) for x in b.xyxy[0].tolist())
            out.append((xyxy, float(b.conf[0])))
        return out

    return _predict


def emit_mini_ad(
    frame: np.ndarray,
    mini_ad_model: YOLO,
    conf: float,
    ad_rois: List[RoiRule] | None = None,
) -> None:
    """小广告：有 ad ROI 则裁剪推理，否则整帧。"""
    ads, _crops = detect_mini_ads_in_rois(
        frame, ad_rois or [], mini_ad_predict_fn(mini_ad_model), conf
    )
    for xyxy, score, reason in mini_ad_alerts(ads):
        print(
            json.dumps(
                {
                    "event": "mini_ad",
                    "reason": reason,
                    "bbox": list(xyxy),
                    "confidence": score,
                },
                ensure_ascii=False,
            )
        )


def plate_color_on_patch(patch: np.ndarray, model: YOLO, conf: float) -> Optional[str]:
    if patch.size == 0:
        return None
    res = model.predict(patch, conf=conf, verbose=False)[0]
    if res.boxes is None or len(res.boxes) == 0:
        return None
    best = max(res.boxes, key=lambda b: float(b.conf[0]))
    cls_id = int(best.cls[0])
    names = res.names or {}
    return str(names.get(cls_id, cls_id))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="0", help="摄像头索引、mp4 路径或 rtsp://")
    parser.add_argument("--camera", type=int, default=None)
    parser.add_argument("--weights", default="yolov8n.pt", help="车辆 COCO 检测权重")
    parser.add_argument(
        "--mini-ad-weights",
        type=str,
        default="mini_ad.pt",
        help="小广告 YOLO 权重（.pt）",
    )
    parser.add_argument("--gun-weights", type=str, default="", help="已弃用，请用 --mini-ad-weights")
    parser.add_argument("--mini-ad-conf", type=float, default=0.25)
    parser.add_argument("--gun-conf", type=float, default=None, help="已弃用，请用 --mini-ad-conf")
    parser.add_argument(
        "--plate-color-weights",
        type=str,
        default="",
        help="可选：plate_blue/plate_green YOLO 权重（默认 weights/plate_color.pt）",
    )
    parser.add_argument("--plate-conf", type=float, default=0.25)
    parser.add_argument("--reconnect-sec", type=float, default=5.0, help="RTSP 断线重连间隔（秒）")
    parser.add_argument("--rois", type=Path, help="ROI JSON（kind=ad 为小广告裁剪区）")
    parser.add_argument(
        "--park-align",
        type=Path,
        default=None,
        help="停正标定 JSON（默认 weights/park_align.json）",
    )
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-lpr", action="store_true", help="禁用 HyperLPR3，仅用 HSV 回退")
    parser.add_argument(
        "--lpr-high",
        action="store_true",
        help="HyperLPR3 使用高分辨率检测（更准更慢）",
    )
    parser.add_argument(
        "--hsv-fallback",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="LPR 无结果时是否用 HSV 条带（默认开）",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    roi_path = args.rois if args.rois else script_dir / "sample_rois.json"
    rois = load_rois(roi_path if roi_path.exists() else None)
    ad_rois = [r for r in rois if r.kind in {"ad", "mini_ad", "detect"}]

    park_align_path = args.park_align or (script_dir / "weights" / "park_align.json")
    park_align = load_profile(park_align_path if park_align_path.is_file() else None)

    veh_weights = Path(args.weights)
    if not veh_weights.is_file():
        veh_weights = script_dir / args.weights
    veh_model = YOLO(str(veh_weights))

    mini_ad_weights = (args.gun_weights or args.mini_ad_weights).strip()
    mini_ad_conf = args.gun_conf if args.gun_conf is not None else args.mini_ad_conf
    mini_ad_model: Optional[YOLO] = None
    if mini_ad_weights:
        ad_path = Path(mini_ad_weights)
        if not ad_path.is_file():
            ad_path = script_dir / "weights" / mini_ad_weights
        if ad_path.is_file():
            mini_ad_model = YOLO(str(ad_path))
        else:
            print(json.dumps({"event": "mini_ad_weights_missing", "path": str(ad_path)}, ensure_ascii=False))

    plate_color_model: Optional[YOLO] = None
    pcw = args.plate_color_weights.strip()
    if pcw:
        pc_path = Path(pcw)
        if not pc_path.is_file():
            pc_path = script_dir / "weights" / pcw
        plate_color_model = YOLO(str(pc_path))
    elif (script_dir / "weights" / "plate_color.pt").is_file():
        plate_color_model = YOLO(str(script_dir / "weights" / "plate_color.pt"))

    lpr_catcher = None
    if not args.no_lpr:
        try:
            lpr_catcher = create_catcher(detect_high=bool(args.lpr_high))
            print(
                json.dumps(
                    {"event": "lpr_ready", "backend": "hyperlpr3", "high": bool(args.lpr_high)},
                    ensure_ascii=False,
                )
            )
        except Exception as e:  # noqa: BLE001 — 启动期收集任意错误利于 Win 权限/下载失败提示
            print(json.dumps({"event": "lpr_init_failed", "error": str(e)}, ensure_ascii=False))
            print(
                json.dumps(
                    {
                        "event": "hint",
                        "msg": "可尝试关闭占用 ~/.hyperlpr3 的进程、删除未完成 zip 后重试，或加 --no-lpr",
                    },
                    ensure_ascii=False,
                )
            )

    cap_src = args.camera if args.camera is not None else parse_video_source(args.source)
    stream = is_network_stream(cap_src) if isinstance(cap_src, str) else False

    while True:
        cap = open_capture(cap_src)
        if not cap.isOpened():
            if stream:
                time.sleep(args.reconnect_sec)
                continue
            raise SystemExit(f"无法打开视频源: {cap_src}")

        fail_reads = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                fail_reads += 1
                if stream and fail_reads >= 30:
                    cap.release()
                    time.sleep(args.reconnect_sec)
                    break
                if not stream:
                    cap.release()
                    if not args.headless:
                        cv2.destroyAllWindows()
                    return
                time.sleep(0.05)
                continue
            fail_reads = 0
            H, W = frame.shape[:2]

            results = veh_model.predict(frame, conf=args.conf, verbose=False)[0]
            boxes = results.boxes
            vehicle_boxes: List[Sequence[float]] = []

            if boxes is not None:
                for b in boxes:
                    cls_id = int(b.cls[0])
                    if cls_id in COCO_VEHICLE:
                        vehicle_boxes.append(b.xyxy[0].tolist())

            if mini_ad_model is not None:
                emit_mini_ad(frame, mini_ad_model, mini_ad_conf, ad_rois)

            if boxes is None:
                if not args.headless:
                    cv2.imshow("chepai-edge-poc", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        cap.release()
                        cv2.destroyAllWindows()
                        return
                continue

            for b in boxes:
                cls_id = int(b.cls[0])
                xyxy = b.xyxy[0].tolist()
                if cls_id not in COCO_VEHICLE:
                    continue

                vtype = COCO_VEHICLE[cls_id]
                if cls_id in {5, 7}:
                    print(
                        json.dumps(
                            {"event": "non_sedan", "coco_class": vtype, "bbox": xyxy},
                            ensure_ascii=False,
                        )
                    )

                crop_v = vehicle_crop(frame, xyxy)
                lpr_rows: List[Any] = []
                if lpr_catcher is not None and crop_v is not None:
                    lpr_rows = run_lpr_on_bgr(crop_v, lpr_catcher)

                if lpr_rows:
                    for pr in lpr_rows:
                        ptype = int(pr["plate_type"])
                        print(
                            json.dumps(
                                {
                                    "event": "lpr",
                                    "vehicle_class": vtype,
                                    "plate_code": pr["plate_code"],
                                    "plate_type": ptype,
                                    "plate_type_name": pr["plate_type_name"],
                                    "confidence": pr["confidence"],
                                    "bbox_vehicle": xyxy,
                                },
                                ensure_ascii=False,
                            )
                        )
                        if is_probable_ev_plate(ptype):
                            print(
                                json.dumps(
                                    {
                                        "event": "likely_ev_plate",
                                        "source": "hyperlpr3",
                                        "plate_code": pr["plate_code"],
                                        "bbox": xyxy,
                                    },
                                    ensure_ascii=False,
                                )
                            )
                        elif is_probable_fuel_plate(ptype):
                            print(
                                json.dumps(
                                    {
                                        "event": "possible_oil_block",
                                        "source": "hyperlpr3",
                                        "plate_code": pr["plate_code"],
                                        "plate_type_name": pr["plate_type_name"],
                                        "bbox": xyxy,
                                    },
                                    ensure_ascii=False,
                                )
                            )
                else:
                    px1, py1, px2, py2 = plate_roi_from_vehicle(xyxy, frame.shape)
                    plate_patch = frame[py1:py2, px1:px2]
                    plate_cls = (
                        plate_color_on_patch(plate_patch, plate_color_model, args.plate_conf)
                        if plate_color_model is not None
                        else None
                    )
                    if plate_cls == "plate_blue":
                        print(
                            json.dumps(
                                {
                                    "event": "possible_oil_block",
                                    "source": "plate_color",
                                    "plate_class": plate_cls,
                                    "bbox": xyxy,
                                },
                                ensure_ascii=False,
                            )
                        )
                    elif plate_cls == "plate_green":
                        print(
                            json.dumps(
                                {
                                    "event": "likely_ev_plate",
                                    "source": "plate_color",
                                    "plate_class": plate_cls,
                                    "bbox": xyxy,
                                },
                                ensure_ascii=False,
                            )
                        )
                    elif args.hsv_fallback:
                        hint = classify_plate_color_hint(plate_patch)
                        if hint in {"blue_plate", "yellow_plate"}:
                            print(
                                json.dumps(
                                    {
                                        "event": "possible_oil_block",
                                        "source": "hsv",
                                        "plate_hint": hint,
                                        "bbox": xyxy,
                                    },
                                    ensure_ascii=False,
                                )
                            )
                        elif hint == "green_plate":
                            print(
                                json.dumps(
                                    {
                                        "event": "likely_ev_plate",
                                        "source": "hsv",
                                        "plate_hint": hint,
                                        "bbox": xyxy,
                                    },
                                    ensure_ascii=False,
                                )
                            )

                    # 停正：需要 plate_color 检出框时才可算偏移；PoC 简化：有 plate 模型时再跑一次取框
                    if park_align is not None and park_align.is_ready() and plate_color_model is not None:
                        res = plate_color_model.predict(plate_patch, conf=args.plate_conf, verbose=False)[0]
                        if res.boxes is not None and len(res.boxes) > 0:
                            best = max(res.boxes, key=lambda b: float(b.conf[0]))
                            pxy = best.xyxy[0].tolist()
                            plate_xyxy = (
                                px1 + float(pxy[0]),
                                py1 + float(pxy[1]),
                                px1 + float(pxy[2]),
                                py1 + float(pxy[3]),
                            )
                            ok_align, detail = eval_alignment(park_align, xyxy, plate_xyxy, W)
                            if not ok_align:
                                print(
                                    json.dumps(
                                        {
                                            "event": "bad_park",
                                            "reason": "plate_align",
                                            "bbox": xyxy,
                                            **{k: detail[k] for k in ("dx", "dx0", "ddx", "x_norm") if k in detail},
                                        },
                                        ensure_ascii=False,
                                    )
                                )

            if not args.headless:
                cv2.imshow("chepai-edge-poc", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    cap.release()
                    cv2.destroyAllWindows()
                    return

        cap.release()
        if not stream:
            break


if __name__ == "__main__":
    main()
