"""Bus charging bay: sedan (car) inside a bus-only parking ROI → alert."""

from __future__ import annotations

from typing import Any, Sequence

from edge.shared.dual_slot import DEFAULT_MIN_VEHICLE_RATIO, vehicle_in_slot_ratio
from edge.shared.roi_rules import RoiRule, iou_xyxy

# Manual ROI kinds for bus-only charging / parking bays.
BUS_SLOT_ROI_KINDS = frozenset({"bus", "bus_slot", "bus_parking", "bus_bay"})

# COCO: car=2 is 轿车; bus/truck are allowed in bus bays.
SEDAN_CLASS_IDS = frozenset({2})
BUS_CLASS_IDS = frozenset({5})


def eval_sedan_in_bus_slot(
    vehicle_xyxy: Sequence[float],
    class_id: int,
    class_name: str,
    bus_rois: list[RoiRule],
    frame_w: int,
    frame_h: int,
    *,
    min_ratio: float = DEFAULT_MIN_VEHICLE_RATIO,
) -> tuple[bool, dict[str, Any]]:
    """True when a sedan overlaps a bus bay with coverage >= min_ratio."""
    detail: dict[str, Any] = {
        "reason": "ok",
        "min_ratio": min_ratio,
        "bbox": [float(x) for x in vehicle_xyxy],
        "coco_class": class_name,
        "class_id": int(class_id),
        "bus_slots": [],
    }
    if class_id not in SEDAN_CLASS_IDS:
        return False, detail
    if not bus_rois:
        return False, detail

    hits: list[dict[str, Any]] = []
    for slot in bus_rois:
        if slot.kind not in BUS_SLOT_ROI_KINDS:
            continue
        ratio, slot_box = vehicle_in_slot_ratio(vehicle_xyxy, slot, frame_w, frame_h)
        if ratio >= min_ratio:
            hits.append(
                {
                    "roi_id": slot.roi_id,
                    "name": slot.name or f"bus_{slot.roi_id}",
                    "ratio": round(float(ratio), 4),
                    "slot_box": [float(x) for x in slot_box],
                    "iou": round(float(iou_xyxy(vehicle_xyxy, slot_box)), 4),
                }
            )
    hits.sort(key=lambda h: h["ratio"], reverse=True)
    detail["bus_slots"] = hits
    if hits:
        detail["reason"] = "car_in_bus_slot"
        return True, detail
    return False, detail


def car_in_bus_slot_alerts(
    vehicles: Sequence[tuple[Sequence[float], int, str, float]],
    bus_rois: list[RoiRule],
    frame_w: int,
    frame_h: int,
    *,
    min_ratio: float = DEFAULT_MIN_VEHICLE_RATIO,
) -> list[tuple[Sequence[float], float, dict[str, Any]]]:
    """
    vehicles: sequence of (xyxy, class_id, class_name, score).
    Returns (xyxy, score, detail) for sedans occupying a bus bay.
    """
    out: list[tuple[Sequence[float], float, dict[str, Any]]] = []
    if not bus_rois:
        return out
    for xyxy, class_id, class_name, score in vehicles:
        ok, detail = eval_sedan_in_bus_slot(
            xyxy,
            class_id,
            class_name,
            bus_rois,
            frame_w,
            frame_h,
            min_ratio=min_ratio,
        )
        if ok:
            out.append((xyxy, float(score), detail))
    return out


def eval_bus_in_restricted_slot(
    vehicle_xyxy: Sequence[float],
    class_id: int,
    class_name: str,
    parking_rois: list[RoiRule],
    frame_w: int,
    frame_h: int,
    *,
    min_ratio: float = DEFAULT_MIN_VEHICLE_RATIO,
) -> tuple[bool, dict[str, Any]]:
    """True when a bus overlaps a parking (restricted) slot with coverage >= min_ratio."""
    from edge.shared.dual_slot import PARKING_ROI_KINDS

    detail: dict[str, Any] = {
        "reason": "ok",
        "min_ratio": min_ratio,
        "bbox": [float(x) for x in vehicle_xyxy],
        "coco_class": class_name,
        "class_id": int(class_id),
        "restricted_slots": [],
    }
    if class_id not in BUS_CLASS_IDS:
        return False, detail
    if not parking_rois:
        return False, detail

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
    detail["restricted_slots"] = hits
    if hits:
        detail["reason"] = "bus_in_restricted"
        return True, detail
    return False, detail


def bus_in_restricted_alerts(
    vehicles: Sequence[tuple[Sequence[float], int, str, float]],
    parking_rois: list[RoiRule],
    frame_w: int,
    frame_h: int,
    *,
    min_ratio: float = DEFAULT_MIN_VEHICLE_RATIO,
) -> list[tuple[Sequence[float], float, dict[str, Any]]]:
    """Bus (COCO class 5) inside a drawn parking/restricted ROI."""
    out: list[tuple[Sequence[float], float, dict[str, Any]]] = []
    if not parking_rois:
        return out
    for xyxy, class_id, class_name, score in vehicles:
        ok, detail = eval_bus_in_restricted_slot(
            xyxy,
            class_id,
            class_name,
            parking_rois,
            frame_w,
            frame_h,
            min_ratio=min_ratio,
        )
        if ok:
            out.append((xyxy, float(score), detail))
    return out
