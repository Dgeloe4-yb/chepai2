"""Mini-ad inference runs concurrently (own thread) with the vehicle->plate chain."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.inference import Detection, DetectorEngine
from chepai_edge.pipeline import FramePipeline, PipelineRules, plate_roi_from_vehicle
from edge.shared.park_align import AlignAnchor, ParkAlignProfile
from edge.shared.roi_rules import RoiRule


class _RecordingEngine(DetectorEngine):
    def __init__(self, dets: list[Detection], delay: float = 0.0) -> None:
        self._dets = dets
        self._delay = delay
        self.thread_name: str | None = None

    def predict(self, bgr: np.ndarray, conf: float) -> list[Detection]:
        self.thread_name = threading.current_thread().name
        if self._delay:
            time.sleep(self._delay)
        return list(self._dets)


def test_mini_ad_runs_on_separate_thread() -> None:
    vehicle = _RecordingEngine([Detection((10, 10, 50, 50), 0.9, 2, "car")], delay=0.05)
    plate = _RecordingEngine([])
    mini_ad = _RecordingEngine([], delay=0.05)

    rules = PipelineRules()
    pipe = FramePipeline(vehicle, plate, mini_ad, rules)
    try:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        alerts, debug = pipe.analyze_debug(frame, [], rules)
    finally:
        pipe.close()

    assert mini_ad.thread_name is not None
    assert mini_ad.thread_name.startswith("mini-ad-infer")
    assert vehicle.thread_name != mini_ad.thread_name
    assert debug.mini_ads == []
    assert alerts == []


def test_mini_ad_alert_on_detection() -> None:
    vehicle = _RecordingEngine([])
    plate = _RecordingEngine([])
    mini_ad = _RecordingEngine([Detection((0, 0, 5, 5), 0.9, 0, "guang_gao")])

    rules = PipelineRules(mini_ad_conf=0.35)
    pipe = FramePipeline(vehicle, plate, mini_ad, rules)
    try:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        alerts, debug = pipe.analyze_debug(frame, [], rules)
    finally:
        pipe.close()

    assert len(debug.mini_ads) == 1
    assert any(a.alert_type == "mini_ad" for a in alerts)


def test_mini_ad_runs_on_ad_roi_crop() -> None:
    vehicle = _RecordingEngine([])
    plate = _RecordingEngine([])
    # If predict is called on crop, return one box in crop coords
    mini_ad = _RecordingEngine([Detection((1, 1, 4, 4), 0.9, 0, "guang_gao")])

    rois = [
        RoiRule(
            kind="ad",
            polygon=[(0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)],
            normalized=True,
            name="ad_zone",
            roi_id=1,
        )
    ]
    rules = PipelineRules()
    pipe = FramePipeline(vehicle, plate, mini_ad, rules)
    try:
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        alerts, debug = pipe.analyze_debug(frame, rois, rules)
    finally:
        pipe.close()

    assert mini_ad.thread_name is not None
    assert len(debug.ad_crop_rects) == 1
    assert len(debug.mini_ads) == 1
    # box offset into full frame: crop starts at (10,10)
    x1, y1, x2, y2 = debug.mini_ads[0][0]
    assert abs(x1 - 11) < 1 and abs(y1 - 11) < 1


def test_bad_park_from_plate_align() -> None:
    # Vehicle center ~50, plate far left → large |dx|
    vehicle = _RecordingEngine([Detection((0, 0, 100, 100), 0.9, 2, "car")])
    plate = _RecordingEngine([Detection((0, 70, 20, 90), 0.9, 0, "plate_blue")])
    mini_ad = _RecordingEngine([])

    profile = ParkAlignProfile(
        anchors=[AlignAnchor(x_norm=0.5, dx0=0.0, dy0=0.3)],
        dx_threshold=0.12,
    )
    rules = PipelineRules(enable_bad_park=True)
    pipe = FramePipeline(vehicle, plate, mini_ad, rules, park_align=profile)
    try:
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        alerts, debug = pipe.analyze_debug(frame, [], rules)
    finally:
        pipe.close()

    assert any(a.alert_type == "bad_park" for a in alerts)
    assert len(debug.align_debug) == 1


def test_dual_slot_occupy_alert() -> None:
    # Vehicle 0..100 spans two half-frame slots
    vehicle = _RecordingEngine([Detection((5, 10, 95, 90), 0.88, 2, "car")])
    plate = _RecordingEngine([])
    mini_ad = _RecordingEngine([])
    parking = [
        RoiRule(
            kind="parking",
            polygon=[(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)],
            normalized=True,
            name="slot_a",
            roi_id=1,
        ),
        RoiRule(
            kind="parking",
            polygon=[(0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)],
            normalized=True,
            name="slot_b",
            roi_id=2,
        ),
    ]
    rules = PipelineRules(dual_slot_min_ratio=0.15)
    pipe = FramePipeline(vehicle, plate, mini_ad, rules)
    try:
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        alerts, debug = pipe.analyze_debug(frame, parking, rules)
    finally:
        pipe.close()

    dual = [a for a in alerts if a.alert_type == "dual_slot"]
    assert len(dual) == 1
    assert dual[0].raw.get("slot_count") == 2
    assert len(debug.dual_slot_debug) == 1


def test_dual_slot_not_triggered_single_slot() -> None:
    vehicle = _RecordingEngine([Detection((10, 10, 40, 80), 0.9, 2, "car")])
    plate = _RecordingEngine([])
    mini_ad = _RecordingEngine([])
    parking = [
        RoiRule(
            kind="parking",
            polygon=[(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)],
            normalized=True,
            name="slot_a",
            roi_id=1,
        ),
        RoiRule(
            kind="parking",
            polygon=[(0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)],
            normalized=True,
            name="slot_b",
            roi_id=2,
        ),
    ]
    pipe = FramePipeline(vehicle, plate, mini_ad, PipelineRules(dual_slot_min_ratio=0.15))
    try:
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        alerts, _ = pipe.analyze_debug(frame, parking, PipelineRules(dual_slot_min_ratio=0.15))
    finally:
        pipe.close()
    assert not any(a.alert_type == "dual_slot" for a in alerts)


def test_car_in_bus_slot_alert() -> None:
    vehicle = _RecordingEngine([Detection((10, 10, 80, 80), 0.91, 2, "car")])
    plate = _RecordingEngine([])
    mini_ad = _RecordingEngine([])
    bus = [
        RoiRule(
            kind="bus",
            polygon=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            normalized=True,
            name="bus_bay_1",
            roi_id=10,
        )
    ]
    pipe = FramePipeline(vehicle, plate, mini_ad, PipelineRules(bus_slot_min_ratio=0.15))
    try:
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        alerts, debug = pipe.analyze_debug(frame, bus, PipelineRules(bus_slot_min_ratio=0.15))
    finally:
        pipe.close()
    assert any(a.alert_type == "car_in_bus_slot" for a in alerts)
    assert len(debug.bus_slot_debug) == 1


def test_bus_in_bus_slot_no_alert() -> None:
    vehicle = _RecordingEngine([Detection((10, 10, 80, 80), 0.9, 5, "bus")])
    plate = _RecordingEngine([])
    mini_ad = _RecordingEngine([])
    bus = [
        RoiRule(
            kind="bus",
            polygon=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            normalized=True,
            name="bus_bay_1",
            roi_id=10,
        )
    ]
    pipe = FramePipeline(vehicle, plate, mini_ad, PipelineRules())
    try:
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        alerts, _ = pipe.analyze_debug(frame, bus, PipelineRules())
    finally:
        pipe.close()
    assert not any(a.alert_type == "car_in_bus_slot" for a in alerts)
    assert not any(a.alert_type == "non_sedan" for a in alerts)
    assert not any(a.alert_type == "bus_in_restricted" for a in alerts)


def test_bus_in_restricted_alert() -> None:
    vehicle = _RecordingEngine([Detection((10, 10, 80, 80), 0.9, 5, "bus")])
    plate = _RecordingEngine([])
    mini_ad = _RecordingEngine([])
    parking = [
        RoiRule(
            kind="parking",
            polygon=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            normalized=True,
            name="slot_1",
            roi_id=1,
        ),
    ]
    pipe = FramePipeline(vehicle, plate, mini_ad, PipelineRules(restricted_slot_min_ratio=0.15))
    try:
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        alerts, debug = pipe.analyze_debug(frame, parking, PipelineRules(restricted_slot_min_ratio=0.15))
    finally:
        pipe.close()
    assert any(a.alert_type == "bus_in_restricted" for a in alerts)
    assert len(debug.bus_restricted_debug) == 1


def test_bad_park_disabled_by_default() -> None:
    vehicle = _RecordingEngine([Detection((0, 0, 100, 100), 0.9, 2, "car")])
    plate = _RecordingEngine([Detection((0, 70, 20, 90), 0.9, 0, "plate_blue")])
    mini_ad = _RecordingEngine([])
    profile = ParkAlignProfile(
        anchors=[AlignAnchor(x_norm=0.5, dx0=0.0, dy0=0.3)],
        dx_threshold=0.12,
    )
    pipe = FramePipeline(vehicle, plate, mini_ad, PipelineRules(), park_align=profile)
    try:
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        alerts, _ = pipe.analyze_debug(frame, [], PipelineRules())
    finally:
        pipe.close()
    assert not any(a.alert_type == "bad_park" for a in alerts)


def test_skip_mini_ad_does_not_infer() -> None:
    vehicle = _RecordingEngine([])
    plate = _RecordingEngine([])
    mini_ad = _RecordingEngine([Detection((0, 0, 5, 5), 0.9, 0, "guang_gao")])
    pipe = FramePipeline(vehicle, plate, mini_ad, PipelineRules())
    pipe.skip_mini_ad = True
    try:
        frame = np.zeros((80, 80, 3), dtype=np.uint8)
        alerts, debug = pipe.analyze_debug(frame, [], PipelineRules())
    finally:
        pipe.close()
    assert mini_ad.thread_name is None
    assert debug.mini_ads == []
    assert not any(a.alert_type == "mini_ad" for a in alerts)


def test_plate_roi_skips_nan() -> None:
    assert plate_roi_from_vehicle((float("nan"), 1, 10, 20), 100, 100) is None
    assert plate_roi_from_vehicle((1, 1, float("inf"), 20), 100, 100) is None
    roi = plate_roi_from_vehicle((10, 10, 50, 50), 100, 100)
    assert roi is not None
    assert roi[2] > roi[0] and roi[3] > roi[1]


def test_nan_vehicle_does_not_abort_analyze() -> None:
    vehicle = _RecordingEngine(
        [
            Detection((float("nan"), 10, 50, 50), 0.9, 2, "car"),
            Detection((10, 10, 50, 50), 0.8, 2, "car"),
        ]
    )
    plate = _RecordingEngine([])
    mini_ad = _RecordingEngine([])
    pipe = FramePipeline(vehicle, plate, mini_ad, PipelineRules())
    try:
        frame = np.zeros((80, 80, 3), dtype=np.uint8)
        alerts, debug = pipe.analyze_debug(frame, [], PipelineRules())
    finally:
        pipe.close()
    assert len(debug.vehicles) == 1
    assert debug.vehicles[0].xyxy == (10, 10, 50, 50)
    assert alerts == [] or all(a.alert_type != "oil_car" for a in alerts)


if __name__ == "__main__":
    test_mini_ad_runs_on_separate_thread()
    test_mini_ad_alert_on_detection()
    test_mini_ad_runs_on_ad_roi_crop()
    test_bad_park_from_plate_align()
    test_dual_slot_occupy_alert()
    test_dual_slot_not_triggered_single_slot()
    test_car_in_bus_slot_alert()
    test_bus_in_bus_slot_no_alert()
    test_bus_in_restricted_alert()
    test_bad_park_disabled_by_default()
    test_skip_mini_ad_does_not_infer()
    test_plate_roi_skips_nan()
    test_nan_vehicle_does_not_abort_analyze()
    print("ok")
