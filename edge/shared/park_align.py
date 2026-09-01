"""Parking alignment (停正) via plate-center vs vehicle-center offset calibration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class AlignAnchor:
    """One calibration sample at horizontal position x_norm in the frame."""

    x_norm: float  # vehicle center x / frame_width, 0~1
    dx0: float  # (plate_cx - car_cx) / car_width
    dy0: float  # (plate_cy - car_cy) / car_height


@dataclass
class ParkAlignProfile:
    anchors: list[AlignAnchor]
    dx_threshold: float = 0.15
    dy_threshold: float = 0.35  # loose; primary signal is dx

    def is_ready(self) -> bool:
        return len(self.anchors) > 0


def bbox_center(xyxy: Sequence[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = map(float, xyxy)
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def plate_vehicle_offset(
    vehicle_xyxy: Sequence[float],
    plate_xyxy: Sequence[float],
) -> tuple[float, float]:
    """Return normalized (dx, dy) of plate center relative to vehicle center."""
    vx1, vy1, vx2, vy2 = map(float, vehicle_xyxy)
    vw = max(1.0, vx2 - vx1)
    vh = max(1.0, vy2 - vy1)
    vcx, vcy = bbox_center(vehicle_xyxy)
    pcx, pcy = bbox_center(plate_xyxy)
    return (pcx - vcx) / vw, (pcy - vcy) / vh


def build_profile_from_pairs(
    pairs: list[tuple[Sequence[float], Sequence[float]]],
    frame_w: int,
    *,
    dx_threshold: float = 0.15,
    dy_threshold: float = 0.35,
) -> ParkAlignProfile:
    """Build profile from (vehicle_xyxy, plate_xyxy) pairs on a calibration frame."""
    anchors: list[AlignAnchor] = []
    for vehicle_xyxy, plate_xyxy in pairs:
        vcx, _ = bbox_center(vehicle_xyxy)
        dx0, dy0 = plate_vehicle_offset(vehicle_xyxy, plate_xyxy)
        anchors.append(AlignAnchor(x_norm=vcx / max(1, frame_w), dx0=dx0, dy0=dy0))
    anchors.sort(key=lambda a: a.x_norm)
    return ParkAlignProfile(
        anchors=anchors,
        dx_threshold=dx_threshold,
        dy_threshold=dy_threshold,
    )


def nearest_anchor(profile: ParkAlignProfile, x_norm: float) -> AlignAnchor | None:
    if not profile.anchors:
        return None
    return min(profile.anchors, key=lambda a: abs(a.x_norm - x_norm))


def eval_alignment(
    profile: ParkAlignProfile,
    vehicle_xyxy: Sequence[float],
    plate_xyxy: Sequence[float],
    frame_w: int,
) -> tuple[bool, dict]:
    """
    Returns (ok, detail). ok=False means bad_park_angle.
    """
    dx, dy = plate_vehicle_offset(vehicle_xyxy, plate_xyxy)
    vcx, _ = bbox_center(vehicle_xyxy)
    x_norm = vcx / max(1, frame_w)
    anchor = nearest_anchor(profile, x_norm)
    if anchor is None:
        return True, {"skipped": True, "reason": "no_anchors", "dx": dx, "dy": dy}

    ddx = abs(dx - anchor.dx0)
    ddy = abs(dy - anchor.dy0)
    ok = ddx <= profile.dx_threshold  # dy is diagnostic only by default
    return ok, {
        "dx": dx,
        "dy": dy,
        "dx0": anchor.dx0,
        "dy0": anchor.dy0,
        "x_norm": x_norm,
        "anchor_x_norm": anchor.x_norm,
        "ddx": ddx,
        "ddy": ddy,
        "dx_threshold": profile.dx_threshold,
    }


def profile_to_dict(profile: ParkAlignProfile) -> dict:
    return {
        "version": 1,
        "dx_threshold": profile.dx_threshold,
        "dy_threshold": profile.dy_threshold,
        "anchors": [
            {"x_norm": a.x_norm, "dx0": a.dx0, "dy0": a.dy0} for a in profile.anchors
        ],
    }


def profile_from_dict(data: dict) -> ParkAlignProfile:
    anchors = [
        AlignAnchor(
            x_norm=float(a["x_norm"]),
            dx0=float(a["dx0"]),
            dy0=float(a["dy0"]),
        )
        for a in data.get("anchors", [])
    ]
    return ParkAlignProfile(
        anchors=anchors,
        dx_threshold=float(data.get("dx_threshold", 0.15)),
        dy_threshold=float(data.get("dy_threshold", 0.35)),
    )


def save_profile(path: Path, profile: ParkAlignProfile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(profile_to_dict(profile), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_profile(path: Path | None) -> ParkAlignProfile | None:
    if not path or not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    profile = profile_from_dict(data)
    return profile if profile.is_ready() else None
