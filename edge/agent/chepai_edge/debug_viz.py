"""Draw ROIs, detections and alerts on frames for debug web."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from chepai_edge.pipeline import AlertCandidate, DebugFrameResult
from edge.shared.roi_rules import RoiRule, filter_viz_rois, polygon_to_pixel

_COLORS = {
    "parking": (0, 200, 0),
    "bus": (0, 140, 255),
    "bus_slot": (0, 140, 255),
    "bus_parking": (0, 140, 255),
    "bus_bay": (0, 140, 255),
    "ad": (0, 220, 255),
    "mini_ad_roi": (0, 220, 255),
    "detect": (0, 220, 255),
    "vehicle": (255, 180, 0),
    "plate": (255, 0, 255),
    "plate_crop": (180, 0, 180),
    "mini_ad": (0, 0, 255),
    "alert": (0, 0, 255),
    "align": (0, 255, 255),
    "dual_slot": (0, 140, 255),
    "car_in_bus_slot": (0, 100, 255),
}


def _draw_polygon(img: np.ndarray, poly: list[tuple[float, float]], color: tuple[int, int, int], label: str) -> None:
    pts = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
    cv2.polylines(img, [pts], True, color, 2, cv2.LINE_AA)
    overlay = img.copy()
    cv2.fillPoly(overlay, [pts], color)
    cv2.addWeighted(overlay, 0.12, img, 0.88, 0, img)
    if poly:
        cv2.putText(
            img,
            label,
            (int(poly[0][0]), max(18, int(poly[0][1]) - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )


def _draw_box(
    img: np.ndarray,
    xyxy: tuple[float, ...],
    color: tuple[int, int, int],
    label: str,
    score: float | None = None
) -> None:
    x1, y1, x2, y2 = map(int, xyxy)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
    text = label if score is None else f"{label} {score:.2f}"
    cv2.putText(img, text, (x1, max(16, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def render_debug_frame(
    frame: np.ndarray,
    rois: list[RoiRule],
    debug: DebugFrameResult,
    alerts: list[AlertCandidate],
) -> np.ndarray:
    h, w = frame.shape[:2]
    out = frame.copy()

    for roi in filter_viz_rois(rois):
        poly_px = polygon_to_pixel(roi.polygon, w, h, roi.normalized)
        color = _COLORS.get(roi.kind, (200, 200, 200))
        label = f"{roi.kind}:{roi.name or roi.roi_id}"
        _draw_polygon(out, poly_px, color, label)

    for rect in debug.ad_crop_rects:
        x1, y1, x2, y2 = rect
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 220, 255), 1, cv2.LINE_AA)
        cv2.putText(out, "ad crop", (x1, max(14, y1 - 2)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 220, 255), 1)

    for det in debug.vehicles:
        _draw_box(out, det.xyxy, _COLORS["vehicle"], det.class_name or "vehicle", det.confidence)

    for det, crop in debug.plates:
        _draw_box(out, crop, _COLORS["plate_crop"], "plate_crop", None)
        _draw_box(out, det.xyxy, _COLORS["plate"], det.class_name or "plate", det.confidence)

    for xyxy, score in debug.mini_ads:
        _draw_box(out, xyxy, _COLORS["mini_ad"], "mini_ad", score)

    for detail in debug.align_debug:
        bbox = detail.get("bbox")
        plate_bbox = detail.get("plate_bbox")
        if bbox and len(bbox) >= 4 and plate_bbox and len(plate_bbox) >= 4:
            vcx = int((bbox[0] + bbox[2]) / 2)
            vcy = int((bbox[1] + bbox[3]) / 2)
            pcx = int((plate_bbox[0] + plate_bbox[2]) / 2)
            pcy = int((plate_bbox[1] + plate_bbox[3]) / 2)
            bad = float(detail.get("ddx", 0)) > float(detail.get("dx_threshold", 0.15))
            color = (0, 0, 255) if bad else _COLORS["align"]
            cv2.line(out, (vcx, vcy), (pcx, pcy), color, 2, cv2.LINE_AA)
            cv2.circle(out, (vcx, vcy), 4, color, -1)
            cv2.circle(out, (pcx, pcy), 4, color, -1)
            cv2.putText(
                out,
                f"dx={detail.get('dx', 0):.2f}/{detail.get('dx0', 0):.2f}",
                (vcx + 6, vcy - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv2.LINE_AA,
            )

    for detail in getattr(debug, "dual_slot_debug", []) or []:
        bbox = detail.get("bbox")
        if bbox and len(bbox) >= 4:
            slots = detail.get("occupied_slots") or []
            label = f"dual_slot x{len(slots)}"
            _draw_box(out, tuple(bbox[:4]), _COLORS["dual_slot"], label, None)
            for hit in slots:
                sb = hit.get("slot_box")
                if sb and len(sb) >= 4:
                    _draw_box(
                        out,
                        tuple(sb[:4]),
                        _COLORS["dual_slot"],
                        f"{hit.get('name', 'slot')} {hit.get('ratio', 0):.2f}",
                        None,
                    )

    for detail in getattr(debug, "bus_slot_debug", []) or []:
        bbox = detail.get("bbox")
        if bbox and len(bbox) >= 4:
            _draw_box(out, tuple(bbox[:4]), _COLORS["car_in_bus_slot"], "car@bus", None)
            for hit in detail.get("bus_slots") or []:
                sb = hit.get("slot_box")
                if sb and len(sb) >= 4:
                    _draw_box(
                        out,
                        tuple(sb[:4]),
                        _COLORS["car_in_bus_slot"],
                        f"{hit.get('name', 'bus')} {hit.get('ratio', 0):.2f}",
                        None,
                    )

    for a in alerts:
        bbox = a.raw.get("bbox") or a.raw.get("bbox_vehicle")
        if bbox and len(bbox) >= 4:
            _draw_box(out, tuple(bbox[:4]), _COLORS["alert"], a.alert_type, a.score)

    cv2.putText(
        out,
        f"veh={len(debug.vehicles)} plate={len(debug.plates)} ad={len(debug.mini_ads)} alert={len(alerts)}",
        (8, h - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (240, 240, 240),
        2,
        cv2.LINE_AA,
    )
    return out


def debug_result_to_json(debug: DebugFrameResult, alerts: list[AlertCandidate]) -> dict[str, Any]:
    return {
        "vehicles": [
            {"xyxy": list(d.xyxy), "conf": d.confidence, "class": d.class_name}
            for d in debug.vehicles
        ],
        "plates": [
            {
                "xyxy": list(d.xyxy),
                "conf": d.confidence,
                "class": d.class_name,
                "crop": list(crop),
            }
            for d, crop in debug.plates
        ],
        "mini_ads": [{"xyxy": list(b), "conf": s} for b, s in debug.mini_ads],
        "adCrops": [list(r) for r in debug.ad_crop_rects],
        "align": debug.align_debug,
        "dualSlot": getattr(debug, "dual_slot_debug", []) or [],
        "busSlot": getattr(debug, "bus_slot_debug", []) or [],
        "alerts": [
            {"type": a.alert_type, "score": a.score, "raw": a.raw}
            for a in alerts
        ],
    }
