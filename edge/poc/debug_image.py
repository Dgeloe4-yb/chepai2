"""
Windows 本地图片调试：三模型（车辆 / 车牌色 / 小广告）+ 停正标定 + 车位双占 + 公交位轿车告警。

用法：
  python debug_image.py                          # 选图 → 画车位 → 画公交位 → 画小广告 → 推理
  python debug_image.py --calib full_row.jpg     # 用满排正停图生成 park_align.json
  python debug_image.py photo.jpg --park-align weights/park_align.json
  python debug_image.py photo.jpg --save-dir out

车位 / 公交车位（多边形点选，可多个）：
  鼠标左键依次点顶点 → Enter 闭合追加 → n 结束 → f 跳过
  z/Backspace 撤销上一点  r 清空当前草稿
小广告区：
  鼠标拖动画矩形 → Enter 确认 → 仅在框内跑小广告
  f 整帧广告检测    r 重画    Esc 取消

快捷键（结果窗口）：
  n/→ 下一张  p/← 上一张  d 重画广告区  b 重画车位  u 重画公交位  s 保存  q 退出
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

_POC_DIR = Path(__file__).resolve().parent
_AGENT_DIR = _POC_DIR.parent / "agent"
_REPO_ROOT = _POC_DIR.parent.parent
for p in (_AGENT_DIR, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.debug_viz import debug_result_to_json, render_debug_frame
from chepai_edge.inference import create_engine
from chepai_edge.pipeline import FramePipeline, PipelineRules, rules_from_dict
from edge.shared.park_align import (
    ParkAlignProfile,
    build_profile_from_pairs,
    load_profile,
    save_profile,
)
from edge.shared.roi_rules import RoiRule

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
DRAW_WIN = "chepai-draw-ad-roi"
DRAW_PARK_WIN = "chepai-draw-parking"
DRAW_BUS_WIN = "chepai-draw-bus"


def collect_images(sources: list[Path], directory: Path | None) -> list[Path]:
    paths: list[Path] = []
    if directory is not None:
        paths.extend(sorted(p for p in directory.rglob("*") if p.suffix.lower() in IMAGE_EXTS))
    for src in sources:
        src = src.resolve()
        if src.is_dir():
            paths.extend(sorted(p for p in src.rglob("*") if p.suffix.lower() in IMAGE_EXTS))
        elif src.is_file() and src.suffix.lower() in IMAGE_EXTS:
            paths.append(src)
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def pick_images_dialog(title: str = "选择图片（可多选）") -> list[Path]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    files = filedialog.askopenfilenames(
        title=title,
        filetypes=[
            ("Images", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"),
            ("All", "*.*"),
        ],
    )
    root.destroy()
    return [Path(f) for f in files if f]


def pick_one_image_dialog(title: str = "选择满排正停标定图") -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title=title,
        filetypes=[
            ("Images", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"),
            ("All", "*.*"),
        ],
    )
    root.destroy()
    return Path(path) if path else None


def resolve_weight(name: str, weights_dir: Path) -> Path:
    p = Path(name)
    if p.is_file():
        return p.resolve()
    for base in (weights_dir, _POC_DIR, _POC_DIR / "weights"):
        cand = (base / name).resolve()
        if cand.is_file():
            return cand
    return (_POC_DIR / "weights" / name).resolve()


def build_pipeline(
    weights_dir: Path,
    vehicle_weights: str,
    plate_weights: str,
    mini_ad_weights: str,
    rules: PipelineRules,
    park_align: ParkAlignProfile | None,
) -> FramePipeline:
    vehicle = create_engine("ultralytics", resolve_weight(vehicle_weights, weights_dir))
    plate = create_engine("ultralytics", resolve_weight(plate_weights, weights_dir))
    mini_ad = create_engine("ultralytics", resolve_weight(mini_ad_weights, weights_dir))
    return FramePipeline(vehicle, plate, mini_ad, rules, park_align=park_align)


def fit_display_scaled(image: np.ndarray, max_w: int, max_h: int) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    if scale >= 1.0:
        return image.copy(), 1.0
    return cv2.resize(
        image,
        (max(1, int(w * scale)), max(1, int(h * scale))),
        interpolation=cv2.INTER_AREA,
    ), scale


def fit_display(image: np.ndarray, max_w: int, max_h: int) -> np.ndarray:
    scaled, _ = fit_display_scaled(image, max_w, max_h)
    return scaled


def _display_to_image(x: int, y: int, scale: float) -> tuple[int, int]:
    inv = 1.0 / scale
    return int(x * inv), int(y * inv)


def rect_to_ad_roi(x1: int, y1: int, x2: int, y2: int, w: int, h: int) -> RoiRule:
    x_lo, x_hi = sorted((x1, x2))
    y_lo, y_hi = sorted((y1, y2))
    x_lo = max(0, min(w - 1, x_lo))
    x_hi = max(x_lo + 1, min(w, x_hi))
    y_lo = max(0, min(h - 1, y_lo))
    y_hi = max(y_lo + 1, min(h, y_hi))
    return RoiRule(
        kind="ad",
        polygon=[
            (x_lo / w, y_lo / h),
            (x_hi / w, y_lo / h),
            (x_hi / w, y_hi / h),
            (x_lo / w, y_hi / h),
        ],
        normalized=True,
        name="ad_zone",
        roi_id=1,
    )


def rect_to_parking_roi(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    w: int,
    h: int,
    *,
    roi_id: int,
    name: str | None = None,
) -> RoiRule:
    x_lo, x_hi = sorted((x1, x2))
    y_lo, y_hi = sorted((y1, y2))
    x_lo = max(0, min(w - 1, x_lo))
    x_hi = max(x_lo + 1, min(w, x_hi))
    y_lo = max(0, min(h - 1, y_lo))
    y_hi = max(y_lo + 1, min(h, y_hi))
    return poly_to_parking_roi(
        [(x_lo, y_lo), (x_hi, y_lo), (x_hi, y_hi), (x_lo, y_hi)],
        w,
        h,
        roi_id=roi_id,
        name=name,
    )


def poly_to_parking_roi(
    points_xy: list[tuple[int, int]],
    w: int,
    h: int,
    *,
    roi_id: int,
    name: str | None = None,
) -> RoiRule:
    return poly_to_roi(points_xy, w, h, kind="parking", roi_id=roi_id, name=name or f"slot_{roi_id}")


def poly_to_roi(
    points_xy: list[tuple[int, int]],
    w: int,
    h: int,
    *,
    kind: str,
    roi_id: int,
    name: str | None = None,
) -> RoiRule:
    poly = []
    for x, y in points_xy:
        px = max(0, min(w - 1, int(x)))
        py = max(0, min(h - 1, int(y)))
        poly.append((px / w, py / h))
    return RoiRule(
        kind=kind,
        polygon=poly,
        normalized=True,
        name=name or f"{kind}_{roi_id}",
        roi_id=roi_id,
    )


def draw_polygon_rois(
    frame: np.ndarray,
    *,
    kind: str,
    title: str,
    win_name: str,
    color: tuple[int, int, int] = (0, 200, 0),
    draft_color: tuple[int, int, int] = (0, 255, 0),
    name_prefix: str = "slot",
    status_hint: str = "",
    max_w: int = 1600,
    max_h: int = 960,
    existing: list[RoiRule] | None = None,
) -> list[RoiRule]:
    """Click vertices to form polygons. Enter=add, n=done, f=skip, z=undo point."""
    h, w = frame.shape[:2]
    slots: list[RoiRule] = list(existing or [])
    draft: list[tuple[int, int]] = []
    done = False
    status = status_hint or "左键点选顶点 → Enter闭合追加 → n结束 → f跳过"
    scale_holder = {"scale": 1.0}

    def _draw_poly(canvas: np.ndarray, pts: list[tuple[int, int]], c: tuple[int, int, int], label: str) -> None:
        if len(pts) >= 2:
            arr = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(canvas, [arr], len(pts) >= 3, c, 2, cv2.LINE_AA)
            if len(pts) >= 3:
                overlay = canvas.copy()
                cv2.fillPoly(overlay, [arr], c)
                cv2.addWeighted(overlay, 0.12, canvas, 0.88, 0, canvas)
        for i, (px, py) in enumerate(pts):
            cv2.circle(canvas, (px, py), 4, c, -1, cv2.LINE_AA)
            cv2.putText(canvas, str(i + 1), (px + 5, py - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, c, 1, cv2.LINE_AA)
        if pts and label:
            cv2.putText(
                canvas,
                label,
                (pts[0][0], max(18, pts[0][1] - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                c,
                2,
                cv2.LINE_AA,
            )

    def render() -> np.ndarray:
        canvas = frame.copy()
        for i, slot in enumerate(slots):
            pts = [(int(p[0] * w), int(p[1] * h)) for p in slot.polygon]
            _draw_poly(canvas, pts, color, slot.name or f"{name_prefix}_{i + 1}")
        _draw_poly(canvas, draft, draft_color, "draft" if draft else "")
        header = f"{title}  已画 {len(slots)} 个  当前点 {len(draft)}  [{w}x{h}]"
        cv2.putText(canvas, header, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        help1 = "左键=加点 | Enter闭合追加 | z撤销点 | r清空草稿 | n结束 | f跳过 | Esc取消"
        cv2.putText(canvas, help1, (12, h - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, status, (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2, cv2.LINE_AA)
        return canvas

    def on_mouse(event: int, x: int, y: int, _flags: int, _param: object) -> None:
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        ix, iy = _display_to_image(x, y, scale_holder["scale"])
        ix = max(0, min(w - 1, ix))
        iy = max(0, min(h - 1, iy))
        draft.append((ix, iy))

    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win_name, on_mouse)

    while not done:
        display, scale = fit_display_scaled(render(), max_w, max_h)
        scale_holder["scale"] = scale
        cv2.imshow(win_name, display)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10, ord(" ")):
            if len(draft) >= 3:
                rid = len(slots) + 1
                slots.append(
                    poly_to_roi(
                        draft,
                        w,
                        h,
                        kind=kind,
                        roi_id=rid,
                        name=f"{name_prefix}_{rid}",
                    )
                )
                draft.clear()
                status = f"已追加 {name_prefix}_{rid}，继续点选或按 n 结束"
            else:
                status = "至少需要 3 个点才能闭合多边形"
        elif key == ord("n"):
            if draft:
                status = "还有未闭合的点，先 Enter 追加或 r 清空后再结束"
            else:
                done = True
        elif key == ord("f"):
            slots = []
            done = True
        elif key in (ord("z"), 8):
            if draft:
                draft.pop()
                status = f"已撤销，当前 {len(draft)} 点"
            else:
                status = "没有可撤销的点"
        elif key == ord("r"):
            draft.clear()
            status = "草稿已清空"
        elif key in (27, ord("q")):
            cv2.destroyWindow(win_name)
            raise SystemExit("已取消")

    cv2.destroyWindow(win_name)
    return slots


def draw_parking_rois(
    frame: np.ndarray,
    *,
    title: str = "画车位（多边形点选，可多个）",
    max_w: int = 1600,
    max_h: int = 960,
    existing: list[RoiRule] | None = None,
) -> list[RoiRule]:
    return draw_polygon_rois(
        frame,
        kind="parking",
        title=title,
        win_name=DRAW_PARK_WIN,
        color=(0, 200, 0),
        draft_color=(0, 255, 0),
        name_prefix="slot",
        status_hint="左键点选顶点 → Enter闭合追加 → n结束（≥2个车位可判双占）→ f跳过",
        max_w=max_w,
        max_h=max_h,
        existing=existing,
    )


def draw_bus_rois(
    frame: np.ndarray,
    *,
    title: str = "画公交车位（多边形点选，可多个）",
    max_w: int = 1600,
    max_h: int = 960,
    existing: list[RoiRule] | None = None,
) -> list[RoiRule]:
    return draw_polygon_rois(
        frame,
        kind="bus",
        title=title,
        win_name=DRAW_BUS_WIN,
        color=(0, 140, 255),
        draft_color=(0, 180, 255),
        name_prefix="bus",
        status_hint="左键点选公交车位 → Enter闭合 → n结束；区内出现轿车将告警 → f跳过",
        max_w=max_w,
        max_h=max_h,
        existing=existing,
    )


def draw_ad_roi(
    frame: np.ndarray,
    *,
    title: str = "画小广告检测区",
    max_w: int = 1600,
    max_h: int = 960,
) -> list[RoiRule]:
    """Drag a rectangle for mini-ad crop inference. f = full frame (empty rois)."""
    h, w = frame.shape[:2]
    draft = [0, 0, 0, 0]
    dragging = False
    confirmed: list[RoiRule] | None | str = "pending"
    status = "拖动鼠标框选小广告检测区（仅在此框内跑广告模型）"

    def render() -> np.ndarray:
        canvas = frame.copy()
        if draft[2] > draft[0] and draft[3] > draft[1]:
            cv2.rectangle(canvas, (draft[0], draft[1]), (draft[2], draft[3]), (0, 220, 255), 2, cv2.LINE_AA)
            overlay = canvas.copy()
            cv2.rectangle(overlay, (draft[0], draft[1]), (draft[2], draft[3]), (0, 220, 255), -1)
            cv2.addWeighted(overlay, 0.15, canvas, 0.85, 0, canvas)
        header = f"{title}  [{w}x{h}]"
        cv2.putText(canvas, header, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, header, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 1, cv2.LINE_AA)
        help1 = "拖动=画框 | Enter确认 | f整帧广告 | r重画 | Esc取消"
        cv2.putText(canvas, help1, (12, h - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, help1, (12, h - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(canvas, status, (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2, cv2.LINE_AA)
        return canvas

    def on_mouse(event: int, x: int, y: int, _flags: int, _param: object) -> None:
        nonlocal dragging
        scale = draw_ad_roi._scale  # type: ignore[attr-defined]
        ix, iy = _display_to_image(x, y, scale)
        if event == cv2.EVENT_LBUTTONDOWN:
            dragging = True
            draft[:] = [ix, iy, ix, iy]
        elif event == cv2.EVENT_MOUSEMOVE and dragging:
            draft[2], draft[3] = ix, iy
        elif event == cv2.EVENT_LBUTTONUP and dragging:
            dragging = False
            draft[0], draft[2] = sorted((draft[0], draft[2]))
            draft[1], draft[3] = sorted((draft[1], draft[3]))

    cv2.namedWindow(DRAW_WIN, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(DRAW_WIN, on_mouse)

    while confirmed == "pending":
        display, scale = fit_display_scaled(render(), max_w, max_h)
        draw_ad_roi._scale = scale  # type: ignore[attr-defined]
        cv2.imshow(DRAW_WIN, display)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10, ord(" ")):
            if draft[2] - draft[0] >= 8 and draft[3] - draft[1] >= 8:
                confirmed = [rect_to_ad_roi(draft[0], draft[1], draft[2], draft[3], w, h)]
            else:
                status = "区域太小，请重画（或按 f 整帧）"
        elif key == ord("f"):
            confirmed = []
        elif key == ord("r"):
            draft[:] = [0, 0, 0, 0]
            status = "已清空，请重新拖动"
        elif key in (27, ord("q")):
            cv2.destroyWindow(DRAW_WIN)
            raise SystemExit("已取消")

    cv2.destroyWindow(DRAW_WIN)
    return confirmed if isinstance(confirmed, list) else []


def analyze_image(
    frame: np.ndarray,
    pipeline: FramePipeline,
    rois: list[RoiRule],
    rules: PipelineRules,
) -> tuple[list, object]:
    return pipeline.analyze_debug(frame, rois, rules)


def calibrate_park_align(
    frame: np.ndarray,
    pipeline: FramePipeline,
    rules: PipelineRules,
    *,
    dx_threshold: float,
) -> ParkAlignProfile:
    """Run vehicle+plate on a full-row straight-park image and build anchors."""
    # Temporarily disable align during calib collect
    old = pipeline.park_align
    pipeline.park_align = None
    try:
        _, debug = pipeline.analyze_debug(frame, [], rules)
    finally:
        pipeline.park_align = old

    # Match each vehicle to best overlapping plate
    pairs: list[tuple[tuple[float, float, float, float], tuple[float, float, float, float]]] = []
    for v in debug.vehicles:
        vx1, vy1, vx2, vy2 = v.xyxy
        best = None
        best_conf = -1.0
        for plate, _crop in debug.plates:
            pcx = (plate.xyxy[0] + plate.xyxy[2]) / 2
            pcy = (plate.xyxy[1] + plate.xyxy[3]) / 2
            if vx1 <= pcx <= vx2 and vy1 <= pcy <= vy2 and plate.confidence > best_conf:
                best = plate
                best_conf = plate.confidence
        if best is not None:
            pairs.append((v.xyxy, best.xyxy))

    if len(pairs) < 1:
        raise SystemExit("标定失败：未同时检出车辆与车牌，请换一张满排正停图")

    profile = build_profile_from_pairs(pairs, frame.shape[1], dx_threshold=dx_threshold)
    print(f"标定完成：{len(profile.anchors)} 个锚点（按水平位置）")
    for a in profile.anchors:
        print(f"  x_norm={a.x_norm:.3f}  dx0={a.dx0:.3f}  dy0={a.dy0:.3f}")
    return profile


def print_result(path: Path, alerts, debug) -> None:
    payload = {
        "image": str(path),
        **debug_result_to_json(debug, alerts),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run_interactive(
    images: list[Path],
    pipeline: FramePipeline,
    rules: PipelineRules,
    save_dir: Path | None,
    *,
    draw_ad_first: bool,
    draw_parking_first: bool,
    draw_bus_first: bool,
    initial_rois: list[RoiRule],
) -> None:
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    index = 0
    win = "chepai-debug-image"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    rois = list(initial_rois)

    def _split_rois(all_rois: list[RoiRule]) -> tuple[list[RoiRule], list[RoiRule], list[RoiRule]]:
        parking = [r for r in all_rois if r.kind in {"parking", "slot", "bay"}]
        bus = [r for r in all_rois if r.kind in {"bus", "bus_slot", "bus_parking", "bus_bay"}]
        ads = [r for r in all_rois if r.kind in {"ad", "mini_ad", "detect"}]
        return parking, bus, ads

    if draw_parking_first or draw_bus_first or draw_ad_first:
        first = cv2.imread(str(images[0]))
        if first is None:
            raise SystemExit(f"无法读取图片: {images[0]}")
        parking, bus, ads = _split_rois(rois)
        if draw_parking_first:
            print("请点选普通车位多边形（左键加点，Enter 闭合追加，n 结束）…")
            parking = draw_parking_rois(first, title=f"画车位 · {images[0].name}")
            print(f"车位：{len(parking)} 个")
        if draw_bus_first:
            print("请点选公交车位多边形（区内轿车将告警）…")
            bus = draw_bus_rois(first, title=f"画公交位 · {images[0].name}")
            print(f"公交车位：{len(bus)} 个")
        if draw_ad_first:
            print("请框选小广告检测区，Enter 确认后开始推理…")
            ads = draw_ad_roi(first, title=f"画小广告区 · {images[0].name}")
            print("小广告：" + ("整帧" if not ads else "裁剪区推理"))
        rois = parking + bus + ads

    while 0 <= index < len(images):
        path = images[index]
        frame = cv2.imread(str(path))
        if frame is None:
            print(f"skip unreadable: {path}", file=sys.stderr)
            index += 1
            continue

        alerts, debug = analyze_image(frame, pipeline, rois, rules)
        vis = render_debug_frame(frame, rois, debug, alerts)
        dual_n = sum(1 for a in alerts if a.alert_type == "dual_slot")
        bus_car_n = sum(1 for a in alerts if a.alert_type == "car_in_bus_slot")
        title = (
            f"[{index + 1}/{len(images)}] {path.name}  "
            f"veh={len(debug.vehicles)} plate={len(debug.plates)} ad={len(debug.mini_ads)} "
            f"dual={dual_n} busCar={bus_car_n} align={len(debug.align_debug)}"
        )
        cv2.setWindowTitle(win, title)
        cv2.imshow(win, fit_display(vis, 1600, 960))

        if save_dir:
            out_path = save_dir / f"{path.stem}_debug{path.suffix.lower()}"
            cv2.imwrite(str(out_path), vis)
            print(f"saved {out_path}")

        print_result(path, alerts, debug)

        if save_dir and index == len(images) - 1:
            break

        key = cv2.waitKey(0 if not save_dir else 1) & 0xFF
        if save_dir:
            index += 1
            continue
        if key in (ord("q"), 27):
            break
        if key in (ord("n"), 83, 3):
            index = min(index + 1, len(images) - 1)
        elif key in (ord("p"), 81, 2):
            index = max(index - 1, 0)
        elif key == ord("d"):
            print("重新画小广告检测区…")
            parking, bus, _ = _split_rois(rois)
            ads = draw_ad_roi(frame, title=f"画小广告区 · {path.name}")
            rois = parking + bus + ads
        elif key == ord("b"):
            print("重新画车位…")
            _, bus, ads = _split_rois(rois)
            parking = draw_parking_rois(frame, title=f"画车位 · {path.name}")
            rois = parking + bus + ads
        elif key == ord("u"):
            print("重新画公交车位…")
            parking, _, ads = _split_rois(rois)
            bus = draw_bus_rois(frame, title=f"画公交位 · {path.name}")
            rois = parking + bus + ads
        elif key == ord("s"):
            default = path.with_name(f"{path.stem}_debug{path.suffix.lower()}")
            cv2.imwrite(str(default), vis)
            print(f"saved {default}")

    cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description="本地调试：车辆+车牌(整帧) / 小广告(画框) / 停正标定")
    parser.add_argument("images", nargs="*", type=Path, help="图片路径（可多个）")
    parser.add_argument("--dir", type=Path, default=None, help="扫描目录下所有图片")
    parser.add_argument("--weights-dir", type=Path, default=_POC_DIR / "weights")
    parser.add_argument("--vehicle-weights", default="yolov8n.pt")
    parser.add_argument("--plate-weights", default="plate_color.pt")
    parser.add_argument("--mini-ad-weights", default="mini_ad.pt")
    parser.add_argument("--vehicle-conf", type=float, default=0.35)
    parser.add_argument("--plate-conf", type=float, default=0.25)
    parser.add_argument("--mini-ad-conf", type=float, default=0.25)
    parser.add_argument(
        "--park-align",
        type=Path,
        default=_POC_DIR / "weights" / "park_align.json",
        help="停正标定 JSON（满排正停图生成）",
    )
    parser.add_argument(
        "--calib",
        type=Path,
        default=None,
        help="用该满排正停图生成/覆盖 park_align.json 后退出（可再加推理图）",
    )
    parser.add_argument("--dx-threshold", type=float, default=0.15, help="停正 dx 偏差阈值")
    parser.add_argument("--save-dir", type=Path, default=None, help="保存标注图；批量跳过交互")
    parser.add_argument("--no-gui", action="store_true", help="仅打印 JSON")
    parser.add_argument(
        "--skip-draw-ad",
        action="store_true",
        help="跳过画小广告框，整帧跑广告模型",
    )
    parser.add_argument(
        "--skip-draw-parking",
        action="store_true",
        help="跳过画车位框（不判双占）",
    )
    parser.add_argument(
        "--skip-draw-bus",
        action="store_true",
        help="跳过画公交车位（不判轿车占公交位）",
    )
    parser.add_argument(
        "--dual-slot-ratio",
        type=float,
        default=0.15,
        help="一车占两车位：车框落入每个车位的面积占比阈值",
    )
    parser.add_argument(
        "--bus-slot-ratio",
        type=float,
        default=0.15,
        help="轿车占公交车位：车框落入公交位的面积占比阈值",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    images = collect_images(args.images, args.dir)
    if not images and not args.calib:
        picked = pick_images_dialog()
        images = collect_images(picked, None)

    for label, name in (
        ("vehicle", args.vehicle_weights),
        ("plate", args.plate_weights),
        ("mini_ad", args.mini_ad_weights),
    ):
        path = resolve_weight(name, args.weights_dir)
        if not path.is_file() and label != "vehicle":
            raise SystemExit(f"缺少权重 {label}: {path}")
        if not path.is_file() and label == "vehicle":
            logger.info("vehicle weights %s 不存在，Ultralytics 将自动下载", path)

    rules = rules_from_dict(
        {
            "vehicle_conf": str(args.vehicle_conf),
            "plate_conf": str(args.plate_conf),
            "mini_ad_conf": str(args.mini_ad_conf),
            "park_align_dx_threshold": str(args.dx_threshold),
            "dual_slot_min_ratio": str(args.dual_slot_ratio),
            "bus_slot_min_ratio": str(args.bus_slot_ratio),
        }
    )

    park_align = load_profile(args.park_align if args.park_align.is_file() else None)

    pipeline = build_pipeline(
        args.weights_dir,
        args.vehicle_weights,
        args.plate_weights,
        args.mini_ad_weights,
        rules,
        park_align,
    )

    try:
        calib_path = args.calib
        if calib_path is None and park_align is None and not args.no_gui and args.save_dir is None:
            # Offer interactive calib if missing
            print("未找到停正标定文件。可选：选择一张「满排且都停正」的照片进行标定。")
            picked = pick_one_image_dialog()
            if picked is not None:
                calib_path = picked

        if calib_path is not None:
            frame = cv2.imread(str(calib_path))
            if frame is None:
                raise SystemExit(f"无法读取标定图: {calib_path}")
            profile = calibrate_park_align(frame, pipeline, rules, dx_threshold=args.dx_threshold)
            save_profile(args.park_align, profile)
            pipeline.park_align = profile
            print(f"已写入 {args.park_align}")
            if not images:
                return

        if not images:
            raise SystemExit("未选择任何推理图片")

        interactive_gui = not args.no_gui and args.save_dir is None
        draw_ad_first = interactive_gui and not args.skip_draw_ad
        draw_parking_first = interactive_gui and not args.skip_draw_parking
        draw_bus_first = interactive_gui and not args.skip_draw_bus

        if args.no_gui or args.save_dir:
            out_dir = args.save_dir
            if out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
            rois: list[RoiRule] = []  # full-frame ad when no draw
            for path in images:
                frame = cv2.imread(str(path))
                if frame is None:
                    print(f"skip unreadable: {path}", file=sys.stderr)
                    continue
                alerts, debug = analyze_image(frame, pipeline, rois, rules)
                print_result(path, alerts, debug)
                if out_dir:
                    vis = render_debug_frame(frame, rois, debug, alerts)
                    out_path = out_dir / f"{path.stem}_debug{path.suffix.lower()}"
                    cv2.imwrite(str(out_path), vis)
                    print(f"saved {out_path}")
        else:
            run_interactive(
                images,
                pipeline,
                rules,
                args.save_dir,
                draw_ad_first=draw_ad_first,
                draw_parking_first=draw_parking_first,
                draw_bus_first=draw_bus_first,
                initial_rois=[],
            )
    finally:
        pipeline.close()


if __name__ == "__main__":
    main()
