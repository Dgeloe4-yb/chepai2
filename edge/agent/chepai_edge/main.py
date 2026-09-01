"""Chepai edge agent entrypoint."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

# Bootstrap: edge/agent (chepai_edge) + repo root (edge.shared)
_AGENT_ROOT = Path(__file__).resolve().parents[1]
_EDGE_ROOT = _AGENT_ROOT.parent
_REPO_ROOT = _EDGE_ROOT.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.alerts import AlertEmitter
from chepai_edge.backend import BackendClient, CameraConfig, EdgeConfig
from chepai_edge.config import AgentConfig
from chepai_edge.features import canonical_feature, parse_heartbeat_features
from chepai_edge.inference import create_engine
from chepai_edge.local_config import LocalConfigStore
from chepai_edge.pipeline import FramePipeline, rules_from_dict
from chepai_edge.stream import CameraWorker
from chepai_edge.watchdog import SystemdWatchdog
from edge.shared.park_align import load_profile

logger = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def weights_fingerprint(cfg: AgentConfig) -> tuple[str, ...]:
    return (
        cfg.inference_backend,
        str(cfg.resolve_weight(cfg.vehicle_weights)),
        str(cfg.resolve_weight(cfg.plate_weights)),
        str(cfg.resolve_weight(cfg.mini_ad_weights)),
        str(cfg.resolve_park_align()),
    )


def build_pipeline(cfg: AgentConfig, rules: dict[str, str]) -> FramePipeline:
    pr = rules_from_dict(rules)
    vehicle = create_engine(cfg.inference_backend, cfg.resolve_weight(cfg.vehicle_weights))
    plate = create_engine(
        cfg.inference_backend,
        cfg.resolve_weight(cfg.plate_weights),
    )
    mini_ad = create_engine(cfg.inference_backend, cfg.resolve_weight(cfg.mini_ad_weights))
    park_align = load_profile(cfg.resolve_park_align())
    if park_align is None:
        logger.warning("park_align not found at %s — bad_park(停正) disabled", cfg.resolve_park_align())
    return FramePipeline(vehicle, plate, mini_ad, pr, park_align=park_align)


class EdgeAgent:
    def __init__(self, cfg: AgentConfig) -> None:
        self.cfg = cfg
        self.backend = BackendClient(
            cfg.backend_url,
            edge_token=cfg.edge_token,
            max_retries=cfg.http_max_retries,
            retry_base_sec=cfg.http_retry_base_sec,
        )
        self.config_store = LocalConfigStore(cfg.local_config_path, cfg.edge_box_id)
        self.config: EdgeConfig | None = None
        self.workers: list[CameraWorker] = []
        self._cameras: dict[int, CameraConfig] = {}
        self._pipeline: FramePipeline | None = None
        self._emitter: AlertEmitter | None = None
        self._global_rules: dict[str, str] = {}
        self._analyze_fps: float = float(os.environ.get("CHEPAI_ANALYZE_FPS", "2"))
        self._weights_fp: tuple[str, ...] | None = None
        self._lock = threading.RLock()
        self._shutdown_requested = False
        self._infer_lock = threading.Lock()
        self._api_camera_id: int | None = None
        self._local_api = None
        self._voice_sync = None
        self._telemetry = None
        # None = all features (before first heartbeat / old backend omitting the field).
        self._enabled_features: frozenset[str] | None = None

    @property
    def infer_lock(self) -> threading.Lock:
        return self._infer_lock

    def select_api_camera(self, camera_id: int) -> None:
        with self._lock:
            self._api_camera_id = camera_id

    def get_api_camera(self) -> CameraConfig | None:
        with self._lock:
            if not self._cameras:
                return None
            cid = self._api_camera_id
            if cid is not None and cid in self._cameras:
                return self._cameras[cid]
            # default first camera
            first = next(iter(self._cameras.values()))
            self._api_camera_id = first.camera_id
            return first

    def _worker_for(self, camera_id: int) -> CameraWorker | None:
        for w in self.workers:
            if w.camera_id == camera_id:
                return w
        return None

    def get_api_frame(self):
        cam = self.get_api_camera()
        if cam is None:
            return None
        worker = self._worker_for(cam.camera_id)
        if worker is None:
            return None
        return worker.get_latest_frame(copy=True)

    def get_api_debug(self):
        cam = self.get_api_camera()
        if cam is None:
            return [], None
        worker = self._worker_for(cam.camera_id)
        if worker is None:
            return [], None
        return worker.get_latest_debug()

    def _get_pipeline(self) -> FramePipeline:
        with self._lock:
            if self._pipeline is None:
                raise RuntimeError("pipeline not initialized")
            return self._pipeline

    def _get_emitter(self) -> AlertEmitter:
        with self._lock:
            if self._emitter is None:
                raise RuntimeError("emitter not initialized")
            return self._emitter

    def _get_camera(self, camera_id: int) -> CameraConfig:
        with self._lock:
            cam = self._cameras.get(camera_id)
            if cam is None:
                raise KeyError(f"camera {camera_id} not in config")
            return cam

    def _get_global_rules(self) -> dict[str, str]:
        with self._lock:
            return dict(self._global_rules)

    def _get_analyze_fps(self) -> float:
        with self._lock:
            return self._analyze_fps

    def _ensure_pipeline(self, rules: dict[str, str]) -> None:
        fp = weights_fingerprint(self.cfg)
        if self._pipeline is not None and self._weights_fp == fp:
            return
        try:
            new_pipeline = build_pipeline(self.cfg, rules)
        except Exception as exc:
            logger.warning("pipeline rebuild failed, keeping previous models: %s", exc)
            if self._pipeline is None:
                raise
            return
        old_pipeline = self._pipeline
        self._pipeline = new_pipeline
        self._weights_fp = fp
        self._apply_skip_mini_ad_locked()
        if old_pipeline is not None:
            old_pipeline.close()
        logger.info("pipeline rebuilt weights_fp=%s", fp)

    def _ensure_emitter(
        self,
        cooldown_sec: float,
        active_camera_ids: set[int],
        confirm_sec: float = 10.0,
    ) -> None:
        if self._emitter is None:
            self._emitter = AlertEmitter(
                self.backend,
                self.cfg.snapshot_dir,
                cooldown_sec=cooldown_sec,
                confirm_sec=confirm_sec,
                max_local_snapshots=self.cfg.snapshot_max_files,
                alert_queue_max=self.cfg.alert_queue_max,
                feature_ok=self.feature_enabled,
            )
        else:
            self._emitter.cooldown_sec = cooldown_sec
            self._emitter.confirm_sec = confirm_sec
            self._emitter.max_local_snapshots = self.cfg.snapshot_max_files
            self._emitter.alert_queue_max = self.cfg.alert_queue_max
            self._emitter.feature_ok = self.feature_enabled
        self._emitter.prune_cameras(active_camera_ids)

    def reload_config(self) -> EdgeConfig:
        with self._lock:
            edge_cfg = self.config_store.load()
            self.config = edge_cfg
            self._cameras = {c.camera_id: c for c in edge_cfg.cameras}
            self._global_rules = dict(edge_cfg.rules)
            self._analyze_fps = float(
                edge_cfg.rules.get(
                    "analyze_fps",
                    os.environ.get("CHEPAI_ANALYZE_FPS", "2"),
                )
            )
            if self._api_camera_id is None and edge_cfg.cameras:
                self._api_camera_id = edge_cfg.cameras[0].camera_id
            elif self._api_camera_id is not None and self._api_camera_id not in self._cameras:
                self._api_camera_id = edge_cfg.cameras[0].camera_id if edge_cfg.cameras else None

            self._ensure_pipeline(edge_cfg.rules)

            cooldown = float(edge_cfg.rules.get("alert_cooldown_sec", "30"))
            confirm = float(
                edge_cfg.rules.get(
                    "alert_confirm_sec",
                    os.environ.get("CHEPAI_ALERT_CONFIRM_SEC", "10"),
                )
            )
            active_ids = {c.camera_id for c in edge_cfg.cameras}
            self._ensure_emitter(cooldown, active_ids, confirm_sec=confirm)

            self._sync_workers_locked(edge_cfg)
            return edge_cfg

    def feature_enabled(self, alert_type: str) -> bool:
        feats = self._enabled_features
        if feats is None:
            return True
        return canonical_feature(alert_type) in feats

    def apply_features(self, raw: object) -> None:
        parsed = parse_heartbeat_features(raw)
        if parsed is None:
            return
        with self._lock:
            if parsed == self._enabled_features:
                return
            self._enabled_features = parsed
            self._apply_skip_mini_ad_locked()
            logger.info(
                "features applied enabled=%s skip_mini_ad=%s",
                sorted(parsed),
                self._pipeline.skip_mini_ad if self._pipeline is not None else None,
            )

    def _on_heartbeat_ack(self, resp: dict) -> None:
        self.apply_features(resp.get("features") if isinstance(resp, dict) else None)

    def _apply_skip_mini_ad_locked(self) -> None:
        pipe = self._pipeline
        if pipe is None:
            return
        feats = self._enabled_features
        pipe.skip_mini_ad = feats is not None and "mini_ad" not in feats

    def _spawn_worker(self, camera_id: int) -> CameraWorker:
        worker = CameraWorker(
            camera_id,
            lambda cid=camera_id: self._get_camera(cid),
            self._get_pipeline,
            self._get_emitter,
            self._get_global_rules,
            self._get_analyze_fps,
            reconnect_sec=float(self.cfg.reconnect_sec),
            read_timeout_sec=float(self.cfg.rtsp_read_timeout_sec),
            get_infer_lock=lambda: self._infer_lock,
        )
        worker.start()
        return worker

    def _stop_worker(self, worker: CameraWorker, timeout: float = 10.0) -> None:
        worker.stop()
        worker.join(timeout=timeout)
        if worker.is_alive():
            logger.warning("worker camera=%s did not stop within %ss", worker.camera_id, timeout)

    def _sync_workers_locked(self, edge_cfg: EdgeConfig) -> None:
        desired_cams = {c.camera_id: c for c in edge_cfg.cameras}
        desired = set(desired_cams)
        active_before = {w.camera_id for w in self.workers}

        for w in list(self.workers):
            if w.camera_id not in desired:
                self._stop_worker(w)
                continue
            if not w.is_alive():
                logger.warning("worker camera=%s is not alive, restarting", w.camera_id)
                continue
            new_url = (desired_cams[w.camera_id].rtsp_url or "").strip()
            bound = (w.bound_rtsp_url or "").strip()
            # Force reconnect when RTSP target changed (e.g. client updated camera IP).
            if bound and new_url and bound != new_url:
                logger.info(
                    "camera %s rtsp changed, restarting worker (%s -> %s)",
                    w.camera_id,
                    bound,
                    new_url,
                )
                self._stop_worker(w)
        self.workers = [w for w in self.workers if w.is_alive() and w.camera_id in desired]
        alive = {w.camera_id for w in self.workers}

        for cam in edge_cfg.cameras:
            if cam.camera_id not in alive:
                self.workers.append(self._spawn_worker(cam.camera_id))
                logger.info("started worker for camera %s", cam.camera_id)

        stopped = active_before - desired
        if stopped:
            logger.info("stopped workers for cameras %s", sorted(stopped))

    def start(self) -> None:
        missing = self.cfg.validate_weights()
        if missing:
            raise SystemExit("Missing weight files:\n  " + "\n  ".join(missing))

        # Local API first; config lives on disk (client writes via :8765).
        from chepai_edge.local_api import start_local_api

        self._local_api = start_local_api(self)

        try:
            edge_cfg = self.reload_config()
        except Exception as exc:  # noqa: BLE001
            logger.warning("initial local config load failed: %s", exc)
            edge_cfg = EdgeConfig(
                edge_box_id=self.cfg.edge_box_id,
                cameras=[],
                rules={},
            )

        if not edge_cfg.cameras:
            logger.warning(
                "No cameras configured yet; use client on :8765 to set camera IP",
            )
        elif not any((c.rtsp_url or "").strip() for c in edge_cfg.cameras):
            logger.warning(
                "Camera(s) present but RTSP empty; use client to set camera IP on :8765",
            )
        else:
            logger.info(
                "edge agent running box=%s cameras=%s alerts=%s",
                self.cfg.edge_box_id,
                len(edge_cfg.cameras),
                self.cfg.backend_url,
            )

        from chepai_edge.voice_sync import VoicePackSync
        from chepai_edge.telemetry import EdgeTelemetry

        home = Path(os.environ.get("CHEPAI_EDGE_HOME", "/opt/chepai-edge"))
        voice_dir = Path(os.environ.get("CHEPAI_VOICE_DIR", str(home / "voice")))
        custom_dir = Path(os.environ.get("CHEPAI_VOICE_CUSTOM_DIR", str(voice_dir / "custom")))
        self._voice_sync = VoicePackSync.from_env(
            self.backend, self.cfg.edge_box_id, voice_dir, custom_dir=custom_dir
        )
        if self._voice_sync is not None:
            self._voice_sync.start()
        self._telemetry = EdgeTelemetry.from_env(
            self.backend,
            self.cfg.edge_box_id,
            self.telemetry_snapshot,
            on_heartbeat=self._on_heartbeat_ack,
        )
        if self._telemetry is not None:
            self._telemetry.start()

    def telemetry_snapshot(self) -> dict:
        now = time.monotonic()
        cameras: list[dict] = []
        with self._lock:
            workers = list(self.workers)
        for w in workers:
            grab, analyze = w.watchdog_sample()
            cameras.append(
                {
                    "id": w.camera_id,
                    "alive": w.is_alive(),
                    "grabAgeSec": None if grab is None else round(max(0.0, now - grab), 1),
                    "analyzeAgeSec": round(max(0.0, now - analyze), 1),
                }
            )
        loadavg = None
        try:
            loadavg = [round(x, 2) for x in os.getloadavg()]
        except OSError:
            loadavg = None
        return {"cameras": cameras, "loadavg": loadavg}

    def shutdown(self) -> None:
        if self._telemetry is not None:
            try:
                self._telemetry.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("telemetry stop failed: %s", exc)
            self._telemetry = None
        if self._voice_sync is not None:
            try:
                self._voice_sync.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("voice sync stop failed: %s", exc)
            self._voice_sync = None
        if self._local_api is not None:
            try:
                self._local_api.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.warning("local API shutdown failed: %s", exc)
            self._local_api = None
        with self._lock:
            for w in list(self.workers):
                self._stop_worker(w)
            self.workers.clear()
            if self._emitter is not None:
                self._emitter.shutdown()
            if self._pipeline is not None:
                self._pipeline.close()
            self._pipeline = None
            try:
                from chepai_edge.inference import _SharedRknnRuntime

                _SharedRknnRuntime.reset()
            except Exception as exc:  # noqa: BLE001
                logger.warning("rknn runtime reset failed: %s", exc)
        logger.info("edge agent shutdown complete")

    def run_forever(self) -> None:
        self.start()
        watchdog = SystemdWatchdog()
        watchdog.ready()

        def _handle(signum: int, _frame: object) -> None:
            logger.info("shutdown signal received: %s", signum)
            self._shutdown_requested = True

        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)

        while not self._shutdown_requested:
            with self._lock:
                workers = list(self.workers)
            watchdog.beat(workers)
            time.sleep(1)

        watchdog.stopping()
        self.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Chepai RK3588 edge agent")
    parser.add_argument("--edge-box-id", default=None, help="override CHEPAI_EDGE_BOX_ID")
    parser.add_argument(
        "--weights-dir",
        type=Path,
        default=None,
        help="override weights directory (dev: edge/poc/weights)",
    )
    args = parser.parse_args()

    cfg = AgentConfig.from_env()
    if args.edge_box_id:
        cfg.edge_box_id = args.edge_box_id
    if args.weights_dir:
        cfg.weights_dir = args.weights_dir.resolve()

    setup_logging(cfg.log_level)
    EdgeAgent(cfg).run_forever()


if __name__ == "__main__":
    main()
