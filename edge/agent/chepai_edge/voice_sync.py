"""Pull custom WAV clips from the cloud backend into a local overlay dir.

Factory WAVs stay in CHEPAI_VOICE_DIR. Custom uploads are written to
CHEPAI_VOICE_CUSTOM_DIR (default: <voice_dir>/custom). Missing cloud clips
are deleted from the overlay so the announcer falls back to the local default.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from chepai_edge.backend import BackendClient

logger = logging.getLogger(__name__)


class VoicePackSync(threading.Thread):
    daemon = True

    def __init__(
        self,
        backend: BackendClient,
        edge_box_id: str,
        custom_dir: Path,
        interval_sec: float = 300.0,
    ) -> None:
        super().__init__(name="voice-sync")
        self.backend = backend
        self.edge_box_id = edge_box_id
        self.custom_dir = custom_dir
        self.interval_sec = max(30.0, float(interval_sec))
        self._halt = threading.Event()

    @classmethod
    def from_env(
        cls,
        backend: BackendClient,
        edge_box_id: str,
        voice_dir: Path,
        custom_dir: Path | None = None,
    ) -> VoicePackSync | None:
        enabled = os.environ.get("CHEPAI_VOICE_SYNC", "1").lower() not in {"0", "false", "no"}
        if not enabled:
            return None
        interval = float(os.environ.get("CHEPAI_VOICE_SYNC_SEC", "300"))
        overlay = custom_dir or Path(os.environ.get("CHEPAI_VOICE_CUSTOM_DIR", str(voice_dir / "custom")))
        return cls(backend, edge_box_id, overlay, interval_sec=interval)

    def stop(self, timeout: float = 3.0) -> None:
        self._halt.set()
        self.join(timeout=timeout)

    def run(self) -> None:
        logger.info(
            "voice pack sync started box=%s custom=%s interval=%.0fs",
            self.edge_box_id,
            self.custom_dir,
            self.interval_sec,
        )
        while not self._halt.is_set():
            try:
                self.sync_once()
            except HTTPError as exc:
                if exc.code != 404:
                    logger.warning("voice pack sync http %s: %s", exc.code, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("voice pack sync failed: %s", exc)
            if self._halt.wait(self.interval_sec):
                break

    def sync_once(self) -> None:
        payload: dict[str, Any] = self.backend.fetch_voice_manifest(self.edge_box_id)
        clips = payload.get("clips") or []
        wanted: set[str] = set()
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        for clip in clips:
            alert_type = str(clip.get("alertType") or "")
            sha = str(clip.get("sha256") or "")
            url = str(clip.get("url") or "")
            if not alert_type or not url:
                continue
            dest = self.custom_dir / f"{alert_type}.wav"
            wanted.add(dest.name)
            if sha and dest.is_file() and _sha256(dest) == sha:
                continue
            data = self.backend.download_bytes(url)
            tmp = dest.with_suffix(".wav.tmp")
            tmp.write_bytes(data)
            tmp.replace(dest)
            logger.info("voice pack updated type=%s bytes=%s", alert_type, len(data))
        for path in self.custom_dir.glob("*.wav"):
            if path.name not in wanted:
                path.unlink(missing_ok=True)
                logger.info("voice pack removed custom type=%s (use local default)", path.stem)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()
