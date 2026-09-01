"""Heartbeat auto-register + periodic journal upload to the cloud backend."""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from chepai_edge.backend import BackendClient

logger = logging.getLogger(__name__)

AGENT_VERSION = "1.2.0"


class EdgeTelemetry(threading.Thread):
    daemon = True

    def __init__(
        self,
        backend: BackendClient,
        edge_box_id: str,
        snapshot_fn: Callable[[], dict[str, Any]],
        *,
        heartbeat_sec: float = 30.0,
        log_sec: float = 300.0,
        journal_unit: str = "chepai-edge.service",
        journal_lines: int = 400,
        on_heartbeat: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        super().__init__(name="edge-telemetry")
        # Dedicated short-timeout client: never inherit the alert client's 15s×3 retries.
        self.backend = BackendClient(
            backend.base_url,
            timeout=float(os.environ.get("CHEPAI_TELEMETRY_TIMEOUT", "8")),
            edge_token=backend.edge_token,
            max_retries=int(os.environ.get("CHEPAI_TELEMETRY_RETRIES", "1")),
            retry_base_sec=0.3,
        )
        self.edge_box_id = edge_box_id
        self.snapshot_fn = snapshot_fn
        self.heartbeat_sec = max(10.0, float(heartbeat_sec))
        self.log_sec = max(60.0, float(log_sec))
        self.journal_unit = journal_unit
        self.journal_lines = max(50, journal_lines)
        self.on_heartbeat = on_heartbeat
        self._halt = threading.Event()
        self._last_journal_sha = ""

    @classmethod
    def from_env(
        cls,
        backend: BackendClient,
        edge_box_id: str,
        snapshot_fn: Callable[[], dict[str, Any]],
        on_heartbeat: Callable[[dict[str, Any]], None] | None = None,
    ) -> EdgeTelemetry | None:
        enabled = os.environ.get("CHEPAI_TELEMETRY", "1").lower() not in {"0", "false", "no"}
        if not enabled:
            return None
        return cls(
            backend,
            edge_box_id,
            snapshot_fn,
            heartbeat_sec=float(os.environ.get("CHEPAI_HEARTBEAT_SEC", "30")),
            log_sec=float(os.environ.get("CHEPAI_LOG_UPLOAD_SEC", "300")),
            journal_unit=os.environ.get("CHEPAI_JOURNAL_UNIT", "chepai-edge.service"),
            journal_lines=int(os.environ.get("CHEPAI_JOURNAL_LINES", "400")),
            on_heartbeat=on_heartbeat,
        )

    def stop(self, timeout: float = 3.0) -> None:
        self._halt.set()
        self.join(timeout=timeout)

    def run(self) -> None:
        logger.info(
            "telemetry started box=%s heartbeat=%.0fs logs=%.0fs timeout=%.0fs retries=%s",
            self.edge_box_id,
            self.heartbeat_sec,
            self.log_sec,
            self.backend.timeout,
            self.backend.max_retries,
        )
        last_log = 0.0
        while not self._halt.is_set():
            try:
                self._heartbeat()
            except Exception as exc:  # noqa: BLE001
                logger.warning("heartbeat failed: %s", exc)
            now = time.monotonic()
            if now - last_log >= self.log_sec:
                try:
                    uploaded = self._upload_logs()
                    if uploaded:
                        last_log = now
                except Exception as exc:  # noqa: BLE001
                    logger.warning("log upload failed: %s", exc)
            if self._halt.wait(self.heartbeat_sec):
                break

    def _heartbeat(self) -> None:
        status = dict(self.snapshot_fn() or {})
        disk = _disk_status()
        if disk:
            status["disk"] = disk
        cameras = status.get("cameras") if isinstance(status.get("cameras"), list) else []
        payload: dict[str, Any] = {
            "edgeBoxId": self.edge_box_id,
            "hostname": socket.gethostname(),
            "agentVersion": os.environ.get("CHEPAI_AGENT_VERSION", AGENT_VERSION),
            "cameraCount": len(cameras),
            "status": status,
        }
        resp = self.backend.post_heartbeat(payload)
        if self.on_heartbeat is not None and isinstance(resp, dict):
            try:
                self.on_heartbeat(resp)
            except Exception as exc:  # noqa: BLE001
                logger.warning("heartbeat feature apply failed: %s", exc)

    def _upload_logs(self) -> bool:
        body = collect_journal(self.journal_unit, self.journal_lines)
        if not body.strip():
            logger.debug("log upload skipped: empty journal")
            return True
        sha = hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()
        if sha == self._last_journal_sha:
            logger.debug("log upload skipped: journal unchanged")
            return True
        self.backend.post_logs(
            {
                "edgeBoxId": self.edge_box_id,
                "source": "journal",
                "body": body,
                "collectedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            }
        )
        self._last_journal_sha = sha
        logger.info("log upload ok box=%s chars=%s", self.edge_box_id, len(body))
        return True


def collect_journal(unit: str, lines: int) -> str:
    journalctl = shutil.which("journalctl")
    if journalctl:
        try:
            ret = subprocess.run(
                [journalctl, "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"],
                check=False,
                timeout=20,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if ret.returncode == 0 and (ret.stdout or "").strip():
                return (ret.stdout or "")[-200_000:]
            logger.debug("journalctl rc=%s stderr=%s", ret.returncode, (ret.stderr or "")[:200])
        except Exception as exc:  # noqa: BLE001
            logger.debug("journalctl failed: %s", exc)
    return f"# journal unavailable host={platform.node()} time={datetime.now().isoformat(timespec='seconds')}\n"


def _disk_status() -> dict[str, Any] | None:
    try:
        usage = shutil.disk_usage("/")
    except OSError:
        return None
    return {
        "totalGb": round(usage.total / (1024**3), 1),
        "freeGb": round(usage.free / (1024**3), 1),
    }
