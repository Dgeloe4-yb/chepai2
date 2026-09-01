"""Dual parking-slot occupancy: vehicle covers two slots above a ratio → 违停."""

from __future__ import annotations

from typing import Any, Sequence

from edge.shared.roi_rules import RoiRule, iou_xyxy, polygon_to_pixel

PARKING_ROI_KINDS = frozenset({"parking", "slot", "bay"})

# Fraction of the *vehicle* box that must fall inside a slot to count as occupying it.
DEFAULT_MIN_VEHICLE_RATIO = 0.15


def _aabb_from_polygon(poly: Sequence[tuple[float, float]]) -> list[float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def intersection_area(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return (ix2 - ix1) * (iy2 - iy1)


def vehicle_area(xyxy: Sequence[float]) -> float:
    x1, y1, x2, y2 = xyxy
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def vehicle_in_slot_ratio(
    vehicle_xyxy: Sequence[float],
    slot: RoiRule,
    frame_w: int,
    frame_h: int,
) -> tuple[float, list[float]]:
    """
    Return (coverage, slot_aabb_px).
    coverage = intersection(vehicle, slot_aabb) / area(vehicle).
    """
    poly_px = polygon_to_pixel(slot.polygon, frame_w, frame_h, slot.normalized)
    if len(poly_px) < 2:
        return 0.0, [0.0, 0.0, 0.0, 0.0]
    slot_box = _aabb_from_polygon(poly_px)
    area_v = vehicle_area(vehicle_xyxy)
    if area_v < 1.0:
        return 0.0, slot_box
    inter = intersection_area(vehicle_xyxy, slot_box)
    return inter / area_v, slot_box


def eval_dual_slot_occupy(
    vehicle_xyxy: Sequence[float],
    parking_rois: list[RoiRule],
    frame_w: int,
    frame_h: int,
    *,
    min_ratio: float = DEFAULT_MIN_VEHICLE_RATIO,
) -> tuple[bool, dict[str, Any]]:
    """
    True when the vehicle overlaps at least two parking slots, each with
    coverage >= min_ratio (share of vehicle area inside that slot AABB).
    """
    hits: list[dict[str, Any]] = []
    for slot in parking_rois:
        if slot.kind not in PARKING_ROI_KINDS:
            continue
        ratio, slot_box = vehicle_in_slot_ratio(vehicle_xyxy, slot, frame_w, frame_h)
        if ratio >= min_ratio:
            hits.append(
                {
                    "roi_id": slot.roi_id,
                    "name": slot.name or f"slot_{slot.roi_id}",
                    "ratio": round(float(ratio), 4),
                    "slot_box": [float(x) for x in slot_box],
                    "iou": round(float(iou_xyxy(vehicle_xyxy, slot_box)), 4),
                }
            )

    hits.sort(key=lambda h: h["ratio"], reverse=True)
    is_dual = len(hits) >= 2
    detail: dict[str, Any] = {
        "reason": "dual_slot" if is_dual else "ok",
        "min_ratio": min_ratio,
        "occupied_slots": hits,
        "slot_count": len(hits),
        "bbox": [float(x) for x in vehicle_xyxy],
    }
    return is_dual, detail


def dual_slot_alerts(
    vehicles_xyxy: Sequence[Sequence[float]],
    parking_rois: list[RoiRule],
    frame_w: int,
    frame_h: int,
    *,
    min_ratio: float = DEFAULT_MIN_VEHICLE_RATIO,
    scores: Sequence[float] | None = None,
) -> list[tuple[Sequence[float], float, dict[str, Any]]]:
    """Return list of (xyxy, score, detail) for vehicles occupying two+ slots."""
    out: list[tuple[Sequence[float], float, dict[str, Any]]] = []
    if len(parking_rois) < 2:
        return out
    for i, xyxy in enumerate(vehicles_xyxy):
        ok, detail = eval_dual_slot_occupy(
            xyxy, parking_rois, frame_w, frame_h, min_ratio=min_ratio
        )
        if not ok:
            continue
        score = float(scores[i]) if scores is not None and i < len(scores) else 1.0
        out.append((xyxy, score, detail))
    return out
