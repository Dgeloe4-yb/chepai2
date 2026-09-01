"""Mini-ad (小广告) detection helpers shared by PoC and edge agent."""

from __future__ import annotations

from typing import Callable, List, Sequence, Tuple

import numpy as np

from edge.shared.roi_rules import Point, RoiRule, polygon_to_pixel

PredictFn = Callable[
    [np.ndarray, float],
    List[Tuple[Tuple[float, float, float, float], float]],
]


def polygon_aabb(poly: Sequence[Point], w: int, h: int) -> tuple[int, int, int, int]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (
        int(max(0, min(xs))),
        int(max(0, min(ys))),
        int(min(w, max(xs))),
        int(min(h, max(ys))),
    )


def detect_mini_ads_in_rois(
    frame: np.ndarray,
    ad_rois: list[RoiRule],
    predict: PredictFn,
    conf: float,
) -> tuple[list[tuple[tuple[float, float, float, float], float]], list[tuple[int, int, int, int]]]:
    """
    Run mini-ad model on each ad ROI crop; return full-frame boxes + crop rects.
    If ad_rois is empty, run on full frame (debug / fallback).
    """
    h, w = frame.shape[:2]
    if not ad_rois:
        boxes = list(predict(frame, conf))
        return boxes, [(0, 0, w, h)]

    out: list[tuple[tuple[float, float, float, float], float]] = []
    crops: list[tuple[int, int, int, int]] = []
    for roi in ad_rois:
        poly_px = polygon_to_pixel(roi.polygon, w, h, roi.normalized)
        x1, y1, x2, y2 = polygon_aabb(poly_px, w, h)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        crops.append((x1, y1, x2, y2))
        for xyxy, score in predict(crop, conf):
            fx1, fy1, fx2, fy2 = xyxy
            out.append(((fx1 + x1, fy1 + y1, fx2 + x1, fy2 + y1), score))
    return out, crops


def mini_ad_alerts(
    detections: list[tuple[tuple[float, float, float, float], float]],
) -> list[tuple[tuple[float, float, float, float], float, str]]:
    """Each detection becomes a mini_ad alert."""
    return [(xyxy, score, "detected") for xyxy, score in detections]
