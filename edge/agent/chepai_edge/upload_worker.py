"""Background alert upload worker (HTTP off camera threads)."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from chepai_edge.backend import BackendClient

logger = logging.getLogger(__name__)


def make_idempotency_key(camera_id: int, alert_type: str, cooldown_sec: float) -> str:
    bucket = int(time.time() // max(1.0, cooldown_sec))
    return f"{camera_id}:{alert_type}:{bucket}"


@dataclass(frozen=True)
class PendingAlert:
    camera_id: int
    alert_type: str
    score: float | None
    jpeg: bytes | None
    fname: str
    raw: dict[str, Any]
    idempotency_key: str


class AlertUploadWorker(threading.Thread):
    daemon = False

    def __init__(
        self,
        backend: BackendClient,
        snapshot_dir: Path,
        max_local_snapshots: int,
        queue_max: int,
        upload_snapshots: bool,
        on_success: Callable[[int, str], None],
        on_failure: Callable[[int, str], None] | None = None,
    ) -> None:
        super().__init__(name="alert-upload")
        self.backend = backend
        self.snapshot_dir = snapshot_dir
        self.max_local_snapshots = max_local_snapshots
        self.upload_snapshots = upload_snapshots
        self.on_success = on_success
        self.on_failure = on_failure
        self._queue: queue.Queue[PendingAlert | None] = queue.Queue(maxsize=max(1, queue_max))
        self._halt = threading.Event()

    def enqueue(self, job: PendingAlert) -> bool:
        if self._halt.is_set():
            return False
        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            logger.warning(
                "alert queue full, dropping camera=%s type=%s",
                job.camera_id,
                job.alert_type,
            )
            return False

    def stop(self, drain_sec: float = 5.0) -> None:
        self._halt.set()
        deadline = time.monotonic() + max(0.0, drain_sec)
        while time.monotonic() < deadline:
            if self._queue.empty():
                break
            time.sleep(0.1)
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self.join(timeout=10.0)
        if self.is_alive():
            logger.warning("alert upload worker did not stop within 10s")

    def _prune_local_snapshots(self) -> None:
        if self.max_local_snapshots <= 0:
            return
        files = sorted(
            self.snapshot_dir.glob("cam*.jpg"),
            key=lambda p: p.stat().st_mtime,
        )
        while len(files) > self.max_local_snapshots:
            files.pop(0).unlink(missing_ok=True)

    def _save_local(self, fname: str, jpeg: bytes) -> str:
        out = self.snapshot_dir / fname
        out.write_bytes(jpeg)
        self._prune_local_snapshots()
        return str(out)

    def _upload(self, job: PendingAlert) -> None:
        snap_path: str | None = None
        if job.jpeg is not None:
            if self.upload_snapshots:
                try:
                    snap_path = self.backend.upload_snapshot(job.fname, job.jpeg)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("snapshot upload failed, keeping local copy: %s", exc)
            if snap_path is None:
                snap_path = self._save_local(job.fname, job.jpeg)

        alert_id = self.backend.post_alert(
            job.camera_id,
            job.alert_type,
            job.score,
            snap_path,
            job.raw,
            idempotency_key=job.idempotency_key,
        )
        self.on_success(job.camera_id, job.alert_type)
        logger.info(
            "alert camera=%s type=%s id=%s raw=%s",
            job.camera_id,
            job.alert_type,
            alert_id,
            json.dumps(job.raw, ensure_ascii=False),
        )

    def run(self) -> None:
        while True:
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                if self._halt.is_set() and self._queue.empty():
                    break
                continue
            if job is None:
                break
            try:
                self._upload(job)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "alert upload failed camera=%s type=%s: %s",
                    job.camera_id,
                    job.alert_type,
                    exc,
                )
                if self.on_failure is not None:
                    self.on_failure(job.camera_id, job.alert_type)
