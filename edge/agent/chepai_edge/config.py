"""Edge agent configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# Fixed backend per deployment agreement
DEFAULT_BACKEND_URL = "http://38.207.179.218:18080"


@dataclass
class AgentConfig:
    backend_url: str = DEFAULT_BACKEND_URL
    edge_box_id: str = "rk3588-01"
    weights_dir: Path = field(default_factory=lambda: Path("/opt/chepai-edge/weights"))
    snapshot_dir: Path = field(default_factory=lambda: Path("/opt/chepai-edge/snapshots"))
    local_config_path: Path = field(
        default_factory=lambda: Path("/opt/chepai-edge/data/edge_config.json")
    )
    vehicle_weights: str = "yolov8n.pt"
    mini_ad_weights: str = "mini_ad.pt"
    plate_weights: str = "plate_color.pt"
    park_align_path: str = "park_align.json"
    inference_backend: str = "ultralytics"  # ultralytics | rknn
    config_refresh_sec: int = 300
    reconnect_sec: int = 5
    rtsp_read_timeout_sec: float = 5.0
    snapshot_max_files: int = 500
    alert_queue_max: int = 200
    http_max_retries: int = 3
    http_retry_base_sec: float = 0.5
    log_level: str = "INFO"
    edge_token: str = ""

    @classmethod
    def default_weight_names(self) -> tuple[str, str, str]:
        if self.inference_backend == "rknn":
            return ("yolov8n.rknn", "mini_ad.rknn", "plate_color.rknn")
        return (self.vehicle_weights, self.mini_ad_weights, self.plate_weights)

    @classmethod
    def from_env(cls) -> AgentConfig:
        base = Path(os.environ.get("CHEPAI_EDGE_HOME", "/opt/chepai-edge"))
        inference = os.environ.get("CHEPAI_INFERENCE", "ultralytics")
        if inference == "rknn":
            v_w, g_w, p_w = "yolov8n.rknn", "mini_ad.rknn", "plate_color.rknn"
        else:
            v_w = os.environ.get("CHEPAI_VEHICLE_WEIGHTS", "yolov8n.pt")
            g_w = os.environ.get(
                "CHEPAI_MINI_AD_WEIGHTS",
                os.environ.get("CHEPAI_GUN_WEIGHTS", "mini_ad.pt"),
            )
            p_w = os.environ.get("CHEPAI_PLATE_WEIGHTS", "plate_color.pt")
        local_cfg = os.environ.get("CHEPAI_LOCAL_CONFIG")
        return cls(
            backend_url=os.environ.get("CHEPAI_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/"),
            edge_box_id=os.environ.get("CHEPAI_EDGE_BOX_ID", "rk3588-01"),
            weights_dir=Path(os.environ.get("CHEPAI_WEIGHTS_DIR", str(base / "weights"))),
            snapshot_dir=Path(os.environ.get("CHEPAI_SNAPSHOT_DIR", str(base / "snapshots"))),
            local_config_path=Path(local_cfg) if local_cfg else base / "data" / "edge_config.json",
            vehicle_weights=os.environ.get("CHEPAI_VEHICLE_WEIGHTS", v_w),
            mini_ad_weights=os.environ.get(
                "CHEPAI_MINI_AD_WEIGHTS",
                os.environ.get("CHEPAI_GUN_WEIGHTS", g_w),
            ),
            plate_weights=os.environ.get("CHEPAI_PLATE_WEIGHTS", p_w),
            park_align_path=os.environ.get("CHEPAI_PARK_ALIGN", "park_align.json"),
            inference_backend=inference,
            config_refresh_sec=int(os.environ.get("CHEPAI_CONFIG_REFRESH_SEC", "300")),
            reconnect_sec=int(os.environ.get("CHEPAI_RECONNECT_SEC", "5")),
            rtsp_read_timeout_sec=float(os.environ.get("CHEPAI_RTSP_READ_TIMEOUT_SEC", "5")),
            snapshot_max_files=int(os.environ.get("CHEPAI_SNAPSHOT_MAX_FILES", "500")),
            alert_queue_max=int(os.environ.get("CHEPAI_ALERT_QUEUE_MAX", "200")),
            http_max_retries=int(os.environ.get("CHEPAI_HTTP_MAX_RETRIES", "3")),
            http_retry_base_sec=float(os.environ.get("CHEPAI_HTTP_RETRY_BASE_SEC", "0.5")),
            log_level=os.environ.get("CHEPAI_LOG_LEVEL", "INFO"),
            edge_token=os.environ.get("CHEPAI_EDGE_TOKEN", ""),
        )

    def weight_search_dirs(self) -> list[Path]:
        dirs = [self.weights_dir.resolve()]
        parent = self.weights_dir.parent.resolve()
        if parent not in dirs:
            dirs.append(parent)
        return dirs

    def resolve_weight(self, name: str) -> Path:
        p = Path(name)
        if p.is_file():
            return p.resolve()
        for base in self.weight_search_dirs():
            candidate = (base / name).resolve()
            if candidate.is_file():
                return candidate
        return (self.weights_dir / name).resolve()

    def resolve_park_align(self) -> Path:
        return self.resolve_weight(self.park_align_path)

    def required_weight_paths(self) -> list[tuple[str, Path]]:
        return [
            ("vehicle", self.resolve_weight(self.vehicle_weights)),
            ("mini_ad", self.resolve_weight(self.mini_ad_weights)),
            ("plate", self.resolve_weight(self.plate_weights)),
        ]

    def validate_weights(self) -> list[str]:
        from chepai_edge.inference import _resolve_rknn_path

        missing: list[str] = []
        for label, path in self.required_weight_paths():
            if self.inference_backend == "rknn":
                resolved = _resolve_rknn_path(path)
                if not resolved.is_file():
                    missing.append(f"{label}: {resolved}")
            elif not path.is_file():
                missing.append(f"{label}: {path}")
        return missing
