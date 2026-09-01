"""Per-frame detection logic."""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any

import numpy as np

from chepai_edge.inference import COCO_VEHICLE, Detection, DetectorEngine, PLATE_CLASSES
from edge.shared.bus_slot import BUS_SLOT_ROI_KINDS, bus_in_restricted_alerts, car_in_bus_slot_alerts
from edge.shared.dual_slot import PARKING_ROI_KINDS, dual_slot_alerts
from edge.shared.mini_ad_detect import detect_mini_ads_in_rois, mini_ad_alerts
from edge.shared.park_align import ParkAlignProfile, eval_alignment
from edge.shared.roi_rules import RoiRule

logger = logging.getLogger(__name__)

AD_ROI_KINDS = {"ad", "mini_ad", "detect"}


def _finite_box(xyxy: tuple[float, ...]) -> bool:
    try:
        return len(xyxy) >= 4 and all(math.isfinite(float(v)) for v in xyxy[:4])
    except (TypeError, ValueError):
        return False


def plate_roi_from_vehicle(
    xyxy: tuple[float, ...],
    h: int,
    w: int,
    margin: float = 0.05,
) -> tuple[int, int, int, int] | None:
    """Whole vehicle box (optional margin) for plate_color — no rear-strip heuristic."""
    if not _finite_box(xyxy):
        return None
    x1, y1, x2, y2 = (float(v) for v in xyxy[:4])
    bw, bh = x2 - x1, y2 - y1
    if bw < 2 or bh < 2:
        return int(x1), max(0, int(y2) - 10), int(x2), int(y2)
    dx, dy = margin * bw, margin * bh
    x_lo = max(0, int(x1 - dx))
    y_lo = max(0, int(y1 - dy))
    x_hi = min(w - 1, int(x2 + dx))
    y_hi = min(h - 1, int(y2 + dy))
    if x_hi <= x_lo or y_hi <= y_lo:
        return int(x1), int(y1), int(x2), int(y2)
    return x_lo, y_lo, x_hi, y_hi


@dataclass
class PipelineRules:
    vehicle_conf: float = 0.35
    mini_ad_conf: float = 0.25
    plate_conf: float = 0.25
    allow_green_only: bool = True
    mini_ad_timeout_sec: float = 5.0
    # park align (停正); falls back to profile.dx_threshold when unset via rules
    park_align_dx_threshold: float | None = None
    # 一车占两车位：车框落入每个车位的面积占比阈值
    dual_slot_min_ratio: float = 0.15
    # 轿车占用公交车位
    bus_slot_min_ratio: float = 0.15
    # 公交车进入限制车位（parking ROI）
    restricted_slot_min_ratio: float = 0.15
    enable_bad_park: bool = False


def _truthy(value: str | bool) -> bool:
    return str(value).lower() in {"1", "true", "yes"}


def rules_from_dict(d: dict[str, str]) -> PipelineRules:
    def _f(key: str, default: float) -> float:
        try:
            return float(d.get(key, default))
        except (TypeError, ValueError):
            return default

    mini_ad_conf = _f("mini_ad_conf", _f("gun_conf", 0.25))
    mini_ad_timeout = _f("mini_ad_timeout_sec", _f("gun_timeout_sec", 5.0))

    dx_thr: float | None = None
    if "park_align_dx_threshold" in d or "dx_threshold" in d:
        dx_thr = _f("park_align_dx_threshold", _f("dx_threshold", 0.15))

    return PipelineRules(
        vehicle_conf=_f("vehicle_conf", 0.35),
        mini_ad_conf=mini_ad_conf,
        plate_conf=_f("plate_conf", 0.25),
        allow_green_only=_truthy(d.get("allow_green_only", "true")),
        mini_ad_timeout_sec=mini_ad_timeout,
        park_align_dx_threshold=dx_thr,
        dual_slot_min_ratio=_f("dual_slot_min_ratio", 0.15),
        bus_slot_min_ratio=_f("bus_slot_min_ratio", 0.15),
        restricted_slot_min_ratio=_f("restricted_slot_min_ratio", 0.15),
        enable_bad_park=_truthy(d.get("enable_bad_park", "false")),
    )


def merge_rules(global_rules: dict[str, str], camera_rules: dict[str, str]) -> PipelineRules:
    merged = {**global_rules, **camera_rules}
    return rules_from_dict(merged)


@dataclass
class AlertCandidate:
    alert_type: str
    score: float | None
    raw: dict[str, Any]


@dataclass
class DebugFrameResult:
    vehicles: list[Detection]
    plates: list[tuple[Detection, tuple[int, int, int, int]]]
    mini_ads: list[tuple[tuple[float, float, float, float], float]]
    ad_crop_rects: list[tuple[int, int, int, int]]
    align_debug: list[dict[str, Any]]
    dual_slot_debug: list[dict[str, Any]]
    bus_slot_debug: list[dict[str, Any]]
    bus_restricted_debug: list[dict[str, Any]]


class FramePipeline:
    def __init__(
        self,
        vehicle: DetectorEngine,
        plate: DetectorEngine,
        mini_ad: DetectorEngine,
        rules: PipelineRules,
        park_align: ParkAlignProfile | None = None,
    ) -> None:
        self.vehicle = vehicle
        self.plate = plate
        self.mini_ad = mini_ad
        self.rules = rules
        self.park_align = park_align
        # mini_ad is independent of vehicle/plate; run it on its own core concurrently.
        self._mini_ad_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mini-ad-infer")
        # Cloud feature flag: skip NPU submit without unloading the engine.
        self.skip_mini_ad = False

    def close(self) -> None:
        self._mini_ad_pool.shutdown(wait=False, cancel_futures=True)

    def _mini_ad_predict(self, crop: np.ndarray, conf: float) -> list[tuple[tuple[float, float, float, float], float]]:
        return [(d.xyxy, d.confidence) for d in self.mini_ad.predict(crop, conf)]

    def _run_mini_ad(
        self,
        frame: np.ndarray,
        ad_rois: list[RoiRule],
        conf: float,
    ) -> tuple[list[tuple[tuple[float, float, float, float], float]], list[tuple[int, int, int, int]]]:
        return detect_mini_ads_in_rois(frame, ad_rois, self._mini_ad_predict, conf)

    def analyze(
        self,
        frame: np.ndarray,
        rois: list[RoiRule],
        rules: PipelineRules | None = None,
    ) -> list[AlertCandidate]:
        alerts, _ = self.analyze_debug(frame, rois, rules)
        return alerts

    def analyze_debug(
        self,
        frame: np.ndarray,
        rois: list[RoiRule],
        rules: PipelineRules | None = None,
    ) -> tuple[list[AlertCandidate], DebugFrameResult]:
        r = rules or self.rules
        h, w = frame.shape[:2]
        ad_rois = [roi for roi in rois if roi.kind in AD_ROI_KINDS]
        parking_rois = [roi for roi in rois if roi.kind in PARKING_ROI_KINDS]
        bus_rois = [roi for roi in rois if roi.kind in BUS_SLOT_ROI_KINDS]
        alerts: list[AlertCandidate] = []
        plate_debug: list[tuple[Detection, tuple[int, int, int, int]]] = []
        align_debug: list[dict[str, Any]] = []
        dual_slot_debug: list[dict[str, Any]] = []
        bus_slot_debug: list[dict[str, Any]] = []
        bus_restricted_debug: list[dict[str, Any]] = []

        # mini_ad NPU work is independent of vehicle/plate: run it on its own core
        # concurrently with the vehicle -> plate chain (data-dependent, stays serial).
        # Feature-off skips the submit so the dedicated thread stays idle (engine stays loaded).
        mini_ad_future = None
        if not self.skip_mini_ad:
            mini_ad_future = self._mini_ad_pool.submit(
                self._run_mini_ad, frame, ad_rois, r.mini_ad_conf
            )

        vehicles = [
            d
            for d in self.vehicle.predict(frame, r.vehicle_conf)
            if d.class_id in COCO_VEHICLE and _finite_box(d.xyxy)
        ]

        # 公交车进入限制车位（parking ROI；不再全画面判 non_sedan）
        veh_meta = [(v.xyxy, v.class_id, v.class_name or "", v.confidence) for v in vehicles]
        for xyxy, score, detail in bus_in_restricted_alerts(
            veh_meta,
            parking_rois,
            w,
            h,
            min_ratio=r.restricted_slot_min_ratio,
        ):
            bus_restricted_debug.append(detail)
            alerts.append(
                AlertCandidate(
                    "bus_in_restricted",
                    score,
                    detail,
                )
            )

        # 一车占两车位违停（需至少画出 2 个车位框）
        for xyxy, score, detail in dual_slot_alerts(
            [v.xyxy for v in vehicles],
            parking_rois,
            w,
            h,
            min_ratio=r.dual_slot_min_ratio,
            scores=[v.confidence for v in vehicles],
        ):
            dual_slot_debug.append(detail)
            alerts.append(
                AlertCandidate(
                    "dual_slot",
                    score,
                    detail,
                )
            )

        # 公交车位内出现轿车
        for xyxy, score, detail in car_in_bus_slot_alerts(
            veh_meta,
            bus_rois,
            w,
            h,
            min_ratio=r.bus_slot_min_ratio,
        ):
            bus_slot_debug.append(detail)
            alerts.append(
                AlertCandidate(
                    "car_in_bus_slot",
                    score,
                    detail,
                )
            )

        # Global plate: every vehicle (no parking-slot gate).
        for v in vehicles:
            roi = plate_roi_from_vehicle(v.xyxy, h, w)
            if roi is None:
                continue
            px1, py1, px2, py2 = roi
            patch = frame[py1:py2, px1:px2]
            if patch.size == 0:
                continue
            plate_dets = self.plate.predict(patch, r.plate_conf)
            best_plate: Detection | None = None
            for pd in plate_dets:
                fx1 = px1 + pd.xyxy[0]
                fy1 = py1 + pd.xyxy[1]
                fx2 = px1 + pd.xyxy[2]
                fy2 = py1 + pd.xyxy[3]
                det = Detection(
                    xyxy=(fx1, fy1, fx2, fy2),
                    confidence=pd.confidence,
                    class_id=pd.class_id,
                    class_name=pd.class_name,
                )
                plate_debug.append((det, (px1, py1, px2, py2)))
                if best_plate is None or det.confidence > best_plate.confidence:
                    best_plate = det

            if r.allow_green_only and best_plate is not None:
                blue_id = next(
                    (cid for cid, name in PLATE_CLASSES.items() if name == "plate_blue"),
                    0,
                )
                if best_plate.class_id == blue_id:
                    alerts.append(
                        AlertCandidate(
                            "oil_car",
                            best_plate.confidence,
                            {
                                "plate_class": best_plate.class_name,
                                "bbox_vehicle": list(v.xyxy),
                                "source": "plate_color",
                            },
                        )
                    )

            # 停正：车牌相对车框偏移 vs 标定锚点
            profile = self.park_align
            if (
                r.enable_bad_park
                and profile is not None
                and profile.is_ready()
                and best_plate is not None
            ):
                thr = r.park_align_dx_threshold
                if thr is not None and thr != profile.dx_threshold:
                    profile = ParkAlignProfile(
                        anchors=profile.anchors,
                        dx_threshold=thr,
                        dy_threshold=profile.dy_threshold,
                    )
                ok, detail = eval_alignment(profile, v.xyxy, best_plate.xyxy, w)
                detail = {
                    **detail,
                    "bbox": list(v.xyxy),
                    "plate_bbox": list(best_plate.xyxy),
                }
                align_debug.append(detail)
                if not ok:
                    alerts.append(
                        AlertCandidate(
                            "bad_park",
                            v.confidence,
                            {
                                "reason": "plate_align",
                                **detail,
                            },
                        )
                    )

        mini_ad_boxes: list[tuple[tuple[float, float, float, float], float]] = []
        ad_crop_rects: list[tuple[int, int, int, int]] = []
        if mini_ad_future is not None:
            try:
                mini_ad_boxes, ad_crop_rects = mini_ad_future.result(timeout=r.mini_ad_timeout_sec)
            except FuturesTimeout:
                mini_ad_future.cancel()
                logger.warning(
                    "mini_ad inference timed out after %.1fs, skipping frame",
                    r.mini_ad_timeout_sec,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("mini_ad inference failed: %s", exc)

        for xyxy, score, reason in mini_ad_alerts(mini_ad_boxes):
            alerts.append(
                AlertCandidate(
                    "mini_ad",
                    score,
                    {"bbox": list(xyxy), "reason": reason},
                )
            )

        debug = DebugFrameResult(
            vehicles=vehicles,
            plates=plate_debug,
            mini_ads=mini_ad_boxes,
            ad_crop_rects=ad_crop_rects,
            align_debug=align_debug,
            dual_slot_debug=dual_slot_debug,
            bus_slot_debug=bus_slot_debug,
            bus_restricted_debug=bus_restricted_debug,
        )
        return alerts, debug
