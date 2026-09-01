"""Alert occupancy gate, snapshot upload, and sequential voice announce."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from chepai_edge.alert_count import AlertLevelGate
from chepai_edge.backend import BackendClient
from chepai_edge.upload_worker import AlertUploadWorker, PendingAlert, make_idempotency_key
from chepai_edge.voice import VoiceAnnouncer

logger = logging.getLogger(__name__)


@dataclass
class AlertEmitter:
    backend: BackendClient
    snapshot_dir: Path
    cooldown_sec: float = 30.0
    confirm_sec: float = 10.0
    upload_snapshots: bool = True
    max_local_snapshots: int = 500
    alert_queue_max: int = 200
    voice: VoiceAnnouncer | None = None
    feature_ok: Callable[[str], bool] | None = None
    _last_sent: dict[tuple[int, str], float] = field(default_factory=dict)
    _in_flight: set[tuple[int, str]] = field(default_factory=set)
    _worker: AlertUploadWorker | None = field(default=None, init=False, repr=False)
    _gate: AlertLevelGate | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if self.voice is None:
            self.voice = VoiceAnnouncer.from_env()
        self._gate = AlertLevelGate(
            confirm_sec=self.confirm_sec,
            duty=float(os.environ.get("CHEPAI_ALERT_STABLE_DUTY", "0.75")),
            voice_max=int(os.environ.get("CHEPAI_ALERT_VOICE_MAX", "3")),
        )
        self._worker = AlertUploadWorker(
            self.backend,
            self.snapshot_dir,
            self.max_local_snapshots,
            self.alert_queue_max,
            self.upload_snapshots,
            on_success=self._on_upload_success,
            on_failure=self._on_upload_failure,
        )
        self._worker.start()

    def shutdown(self, drain_sec: float = 5.0) -> None:
        if self._worker is not None:
            self._worker.stop(drain_sec=drain_sec)
            self._worker = None
        if self.voice is not None:
            self.voice.shutdown()
            self.voice = None
        self._in_flight.clear()
        self._last_sent.clear()
        if self._gate is not None:
            self._gate.prune_cameras(set())

    def prune_cameras(self, active_camera_ids: set[int]) -> None:
        stale = [key for key in self._last_sent if key[0] not in active_camera_ids]
        for key in stale:
            del self._last_sent[key]
        self._in_flight = {key for key in self._in_flight if key[0] in active_camera_ids}
        if self._gate is not None:
            self._gate.prune_cameras(active_camera_ids)

    def process_frame_alerts(
        self,
        camera_id: int,
        candidates: list[Any],
        frame: np.ndarray | None,
        now: float | None = None,
    ) -> None:
        """Voice ≤3 per stable occupancy; another ≤3 after a held +1. Cloud once per +1."""
        ts = time.monotonic() if now is None else now
        if self._gate is None:
            return
        self._gate.confirm_sec = self.confirm_sec
        self._gate.clear_sec = self.confirm_sec

        counts: dict[str, int] = {}
        best: dict[str, Any] = {}
        for candidate in candidates:
            alert_type = candidate.alert_type
            counts[alert_type] = counts.get(alert_type, 0) + 1
            prev = best.get(alert_type)
            if prev is None or (candidate.score or 0) >= (prev.score or 0):
                best[alert_type] = candidate

        ticks = self._gate.tick(camera_id, counts, ts)
        for alert_type, tick in ticks.items():
            if self.feature_ok is not None and not self.feature_ok(alert_type):
                continue
            cand = best.get(alert_type)
            if tick.plus_one and cand is not None:
                logger.info(
                    "alert plus_one camera=%s type=%s baseline=%s robust=%s voice_left=%s",
                    camera_id,
                    alert_type,
                    tick.baseline,
                    tick.robust,
                    tick.plays_left,
                )
                self.emit(
                    camera_id,
                    alert_type,
                    cand.score,
                    frame,
                    cand.raw,
                )
            if tick.want_voice and self.voice is not None:
                if self.voice.announce(alert_type, camera_id=camera_id, ignore_cooldown=True):
                    self._gate.mark_played(camera_id, alert_type)

    def _on_upload_success(self, camera_id: int, alert_type: str) -> None:
        key = (camera_id, alert_type)
        self._in_flight.discard(key)
        self._last_sent[key] = time.monotonic()

    def _on_upload_failure(self, camera_id: int, alert_type: str) -> None:
        self._in_flight.discard((camera_id, alert_type))

    def emit(
        self,
        camera_id: int,
        alert_type: str,
        score: float | None,
        frame: np.ndarray | None,
        raw: dict[str, Any],
    ) -> None:
        key = (camera_id, alert_type)
        if self.feature_ok is not None and not self.feature_ok(alert_type):
            return
        if key in self._in_flight:
            return
        if self._worker is None:
            logger.warning("alert worker stopped, dropping camera=%s type=%s", camera_id, alert_type)
            return

        jpeg: bytes | None = None
        fname = f"cam{camera_id}_{alert_type}_{int(time.time() * 1000)}.jpg"
        if frame is not None:
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if ok:
                jpeg = buf.tobytes()

        job = PendingAlert(
            camera_id=camera_id,
            alert_type=alert_type,
            score=score,
            jpeg=jpeg,
            fname=fname,
            raw=raw,
            idempotency_key=make_idempotency_key(camera_id, alert_type, max(1.0, self.confirm_sec)),
        )
        if not self._worker.enqueue(job):
            return
        self._in_flight.add(key)
