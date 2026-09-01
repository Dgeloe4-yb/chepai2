"""Gun detection helpers shared by PoC and edge agent."""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np

from edge.shared.roi_rules import Point, RoiRule, bbox_center_in_polygon, bbox_center_in_rect, polygon_to_pixel

PredictFn = Callable[[np.ndarray, float], list]


def polygon_aabb(poly: Sequence[Point], w: int, h: int) -> tuple[int, int, int, int]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (
        int(max(0, min(xs))),
        int(max(0, min(ys))),
        int(min(w, max(xs))),
        int(min(h, max(ys))),
    )


def detect_guns_in_pile_crops(
    frame: np.ndarray,
    pile_rois: list[RoiRule],
    predict: PredictFn,
    conf: float,
) -> list[tuple[tuple[float, float, float, float], float]]:
    """Run gun model on each pile ROI crop; return full-frame (xyxy, confidence) pairs."""
    h, w = frame.shape[:2]
    out: list[tuple[tuple[float, float, float, float], float]] = []
    for pile in pile_rois:
        poly_px = polygon_to_pixel(pile.polygon, w, h, pile.normalized)
        x1, y1, x2, y2 = polygon_aabb(poly_px, w, h)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        for xyxy, score in predict(crop, conf):
            fx1, fy1, fx2, fy2 = xyxy
            out.append(((fx1 + x1, fy1 + y1, fx2 + x1, fy2 + y1), score))
    return out


def gun_misplace_alerts(
    gun_boxes: list[tuple[tuple[float, float, float, float], float]],
    pile_rois: list[RoiRule],
    vehicle_boxes: list[tuple[float, float, float, float]],
    frame_w: int,
    frame_h: int,
) -> list[tuple[tuple[float, float, float, float], float, str]]:
    """Alarm when gun center is outside all pile polygons and all vehicle bboxes."""
    alerts: list[tuple[tuple[float, float, float, float], float, str]] = []
    for xyxy, score in gun_boxes:
        in_pile = False
        for pile in pile_rois:
            poly_px = polygon_to_pixel(pile.polygon, frame_w, frame_h, pile.normalized)
            if bbox_center_in_polygon(xyxy, poly_px):
                in_pile = True
                break
        in_vehicle = any(bbox_center_in_rect(xyxy, vb) for vb in vehicle_boxes)
        if not in_pile and not in_vehicle:
            alerts.append((xyxy, score, "outside_pile_and_vehicle"))
    return alerts
