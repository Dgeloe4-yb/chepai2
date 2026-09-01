"""YOLOv8 RKNN output decode (letterbox + NMS)."""

from __future__ import annotations

import cv2
import numpy as np


def letterbox(
    bgr: np.ndarray,
    new_shape: tuple[int, int] = (640, 640),
    color: tuple[int, int, int] = (114, 114, 114),
) -> tuple[np.ndarray, float, tuple[float, float]]:
    h, w = bgr.shape[:2]
    nh, nw = new_shape
    r = min(nh / h, nw / w)
    new_unpad = (int(round(w * r)), int(round(h * r)))
    dw, dh = (nw - new_unpad[0]) / 2, (nh - new_unpad[1]) / 2
    if (w, h) != new_unpad:
        bgr = cv2.resize(bgr, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    out = cv2.copyMakeBorder(bgr, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return out, r, (left, top)


def scale_boxes_back(
    boxes_xyxy: np.ndarray,
    r: float,
    pad: tuple[float, float],
    orig_shape: tuple[int, int],
) -> np.ndarray:
    boxes = boxes_xyxy.copy().astype(np.float32)
    boxes[:, [0, 2]] -= pad[0]
    boxes[:, [1, 3]] -= pad[1]
    boxes[:, :4] /= r
    h, w = orig_shape
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)
    return boxes


def nms_xyxy(boxes: np.ndarray, scores: np.ndarray, iou_thresh: float = 0.45) -> list[int]:
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        inds = np.where(iou <= iou_thresh)[0]
        order = order[inds + 1]
    return keep


def decode_yolov8_output(
    outputs: list[np.ndarray],
    conf_thresh: float,
    iou_thresh: float = 0.45,
    max_det: int = 300,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pred = outputs[0]
    if pred.ndim == 3:
        pred = pred[0]
    if pred.shape[0] < pred.shape[1]:
        pred = pred.T
    boxes = pred[:, :4]
    cls_scores = pred[:, 4:]
    cls_id = cls_scores.argmax(axis=1)
    conf = cls_scores[np.arange(len(cls_id)), cls_id]

    mask = (conf >= conf_thresh) & np.isfinite(conf) & np.isfinite(boxes).all(axis=1)
    boxes = boxes[mask]
    conf = conf[mask]
    cls_id = cls_id[mask]
    if len(boxes) == 0:
        return (
            np.zeros((0, 4), dtype=np.float32),
            np.zeros(0, dtype=np.float32),
            np.zeros(0, dtype=np.int32),
        )

    xyxy = np.zeros_like(boxes, dtype=np.float32)
    xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
    xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
    finite_xyxy = np.isfinite(xyxy).all(axis=1)
    xyxy = xyxy[finite_xyxy]
    conf = conf[finite_xyxy]
    cls_id = cls_id[finite_xyxy]
    if len(xyxy) == 0:
        return (
            np.zeros((0, 4), dtype=np.float32),
            np.zeros(0, dtype=np.float32),
            np.zeros(0, dtype=np.int32),
        )

    keep: list[int] = []
    for c in np.unique(cls_id):
        idx = np.where(cls_id == c)[0]
        k = nms_xyxy(xyxy[idx], conf[idx], iou_thresh)
        keep.extend(idx[k].tolist())
    keep = keep[:max_det]
    return xyxy[keep], conf[keep], cls_id[keep].astype(np.int32)
