"""
几何与 ROI 规则：多边形（归一化或像素坐标）内判断、轴对齐框 IoU。
边缘盒可与管理平台约定：polygon_json 使用与帧同尺寸的像素点，或 0~1 归一化坐标。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

Point = Tuple[float, float]


def point_in_polygon(x: float, y: float, polygon: Sequence[Point]) -> bool:
    """射线法，polygon 顶点顺序不限（不自交多边形）。"""
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        intersects = ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-9) + x1)
        if intersects:
            inside = not inside
    return inside


def bbox_center_in_polygon(bbox_xyxy: Sequence[float], polygon: Sequence[Point]) -> bool:
    x1, y1, x2, y2 = bbox_xyxy
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    return point_in_polygon(cx, cy, polygon)


def bbox_center_in_rect(bbox_xyxy: Sequence[float], rect_xyxy: Sequence[float]) -> bool:
    x1, y1, x2, y2 = bbox_xyxy
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    rx1, ry1, rx2, ry2 = rect_xyxy
    return rx1 <= cx <= rx2 and ry1 <= cy <= ry2


def iou_xyxy(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter + 1e-9
    return inter / union


def polygon_to_pixel(polygon: Sequence[Point], width: int, height: int, normalized: bool) -> List[Point]:
    if not normalized:
        return [(float(px), float(py)) for px, py in polygon]
    return [(float(px) * width, float(py) * height) for px, py in polygon]


@dataclass
class RoiRule:
    kind: str
    polygon: List[Point]
    normalized: bool = False


def eval_vehicle_in_parking_slot(
    vehicle_xyxy: Sequence[float],
    slot_polygon: Sequence[Point],
    frame_w: int,
    frame_h: int,
    normalized: bool,
    min_iou: float = 0.2,
) -> Tuple[bool, float]:
    """
    简单“是否停在车位内”：车辆框与车位多边形外包矩形近似 IoU + 中心在多边形内。
    生产环境可替换为旋转框或分割 mask。
    """
    poly_px = polygon_to_pixel(slot_polygon, frame_w, frame_h, normalized)
    xs = [p[0] for p in poly_px]
    ys = [p[1] for p in poly_px]
    slot_box = [min(xs), min(ys), max(xs), max(ys)]
    overlap = iou_xyxy(vehicle_xyxy, slot_box)
    center_in = bbox_center_in_polygon(vehicle_xyxy, poly_px)
    ok = center_in and overlap >= min_iou
    return ok, overlap
