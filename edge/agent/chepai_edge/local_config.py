"""Local edge config persisted on IPC; client writes via Local API."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from chepai_edge.backend import CameraConfig, EdgeConfig, parse_edge_config
from edge.shared.roi_rules import RoiRule

logger = logging.getLogger(__name__)


def edge_config_to_dict(cfg: EdgeConfig) -> dict[str, Any]:
    cameras: list[dict[str, Any]] = []
    for cam in cfg.cameras:
        rois: list[dict[str, Any]] = []
        for roi in cam.rois:
            rois.append(
                {
                    "id": roi.roi_id,
                    "regionType": roi.kind,
                    "name": roi.name or "",
                    "polygonJson": json.dumps(
                        {"polygon": list(roi.polygon), "normalized": roi.normalized},
                        ensure_ascii=False,
                    ),
                }
            )
        cameras.append(
            {
                "id": cam.camera_id,
                "name": cam.name,
                "rtspUrl": cam.rtsp_url,
                "channelNo": cam.channel_no,
                "rules": dict(cam.rules),
                "rois": rois,
            }
        )
    return {
        "edgeBoxId": cfg.edge_box_id,
        "rules": dict(cfg.rules),
        "cameras": cameras,
    }


def default_edge_config(edge_box_id: str) -> EdgeConfig:
    return EdgeConfig(
        edge_box_id=edge_box_id,
        cameras=[
            CameraConfig(
                camera_id=1,
                name="camera-1",
                rtsp_url="",
                channel_no=101,
            )
        ],
        rules={
            "alert_confirm_sec": "10",
            "enable_bad_park": "false",
        },
    )


class LocalConfigStore:
    def __init__(self, path: Path, edge_box_id: str) -> None:
        self.path = path
        self.edge_box_id = edge_box_id
        self._lock = threading.RLock()
        self._next_roi_id = 1

    def load(self) -> EdgeConfig:
        with self._lock:
            if not self.path.is_file():
                cfg = default_edge_config(self.edge_box_id)
                self._save_unlocked(cfg)
                logger.info("created default local config at %s", self.path)
                return cfg
            raw = self.path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            cfg = parse_edge_config(payload)
            if not cfg.edge_box_id:
                cfg = EdgeConfig(
                    edge_box_id=self.edge_box_id,
                    cameras=cfg.cameras,
                    rules=cfg.rules,
                )
            self._refresh_next_roi_id(cfg)
            return cfg

    def save(self, cfg: EdgeConfig) -> None:
        with self._lock:
            self._save_unlocked(cfg)

    def _save_unlocked(self, cfg: EdgeConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(edge_config_to_dict(cfg), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)
        self._refresh_next_roi_id(cfg)

    def _refresh_next_roi_id(self, cfg: EdgeConfig) -> None:
        max_id = 0
        for cam in cfg.cameras:
            for roi in cam.rois:
                if roi.roi_id > max_id:
                    max_id = roi.roi_id
        self._next_roi_id = max_id + 1

    def _camera_index(self, cfg: EdgeConfig, camera_id: int) -> int:
        for i, cam in enumerate(cfg.cameras):
            if cam.camera_id == camera_id:
                return i
        raise KeyError(f"camera {camera_id} not found")

    def add_roi(
        self,
        camera_id: int,
        region_type: str,
        polygon: list[list[float]],
        name: str | None = None,
    ) -> int:
        with self._lock:
            cfg = self.load()
            idx = self._camera_index(cfg, camera_id)
            cam = cfg.cameras[idx]
            roi_id = self._next_roi_id
            self._next_roi_id += 1
            points = [(float(p[0]), float(p[1])) for p in polygon]
            new_roi = RoiRule(
                kind=region_type,
                polygon=points,
                normalized=True,
                name=name or "",
                roi_id=roi_id,
            )
            cam.rois.append(new_roi)
            self._save_unlocked(cfg)
            return roi_id

    def delete_roi(self, roi_id: int) -> None:
        with self._lock:
            cfg = self.load()
            changed = False
            for cam in cfg.cameras:
                before = len(cam.rois)
                cam.rois = [r for r in cam.rois if r.roi_id != roi_id]
                if len(cam.rois) != before:
                    changed = True
            if not changed:
                raise KeyError(f"roi {roi_id} not found")
            self._save_unlocked(cfg)

    def update_camera(
        self,
        camera_id: int,
        *,
        name: str,
        rtsp_url: str | None,
        channel_no: int | None,
    ) -> None:
        with self._lock:
            cfg = self.load()
            idx = self._camera_index(cfg, camera_id)
            cam = cfg.cameras[idx]
            cfg.cameras[idx] = CameraConfig(
                camera_id=cam.camera_id,
                name=name,
                rtsp_url=rtsp_url or "",
                rois=list(cam.rois),
                rules=dict(cam.rules),
                channel_no=channel_no if channel_no is not None else cam.channel_no,
            )
            self._save_unlocked(cfg)
