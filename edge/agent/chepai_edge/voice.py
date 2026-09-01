"""Sequential voice announcements for edge alerts (no overlapping playback)."""

from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 告警类型 → 播报文案（可按现场改）
ALERT_PHRASES: dict[str, str] = {
    "dual_slot": "请注意，车辆占用两个车位，请规范停放",
    "car_in_bus_slot": "请注意，轿车停入公交车位，请立即驶离",
    "bad_park": "请注意，车辆未停正，请调整车位",
    "mini_ad": "请注意，检测到违规小广告",
    "bus_in_restricted": "请注意，公交车进入限制区域",
    "non_sedan": "请注意，公交车进入限制区域",
    "oil_car": "请注意，燃油车进入新能源区域",
}


@dataclass(frozen=True)
class VoiceJob:
    alert_type: str
    text: str
    camera_id: int = 0


class VoiceAnnouncer:
    """
    单线程顺序播报：队列里一条接一条，当前未播完不会开下一条。
    同一 alert_type 若已在队列中或正在播，不再重复入队，避免堆积吵闹。
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        voice_dir: Path | None = None,
        custom_dir: Path | None = None,
        queue_max: int = 32,
        cooldown_sec: float = 20.0,
        engine: str = "auto",  # auto | wav | espeak | log
    ) -> None:
        self.enabled = enabled
        self.voice_dir = voice_dir
        self.custom_dir = custom_dir
        self.cooldown_sec = max(0.0, cooldown_sec)
        self.engine = engine
        self._q: queue.Queue[VoiceJob | None] = queue.Queue(maxsize=max(4, queue_max))
        self._pending_types: set[str] = set()
        self._lock = threading.Lock()
        self._last_spoken: dict[str, float] = {}
        self._speaking_type: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if self.enabled:
            self._thread = threading.Thread(target=self._loop, name="voice-announce", daemon=True)
            self._thread.start()
            logger.info(
                "voice announcer started engine=%s dir=%s custom=%s cooldown=%.1fs",
                self._resolve_engine(),
                self.voice_dir,
                self.custom_dir,
                self.cooldown_sec,
            )

    @classmethod
    def from_env(cls) -> VoiceAnnouncer:
        enabled = os.environ.get("CHEPAI_VOICE_ENABLE", "1").lower() not in ("0", "false", "no")
        home = Path(os.environ.get("CHEPAI_EDGE_HOME", "/opt/chepai-edge"))
        voice_dir = Path(os.environ.get("CHEPAI_VOICE_DIR", str(home / "voice")))
        custom_dir = Path(os.environ.get("CHEPAI_VOICE_CUSTOM_DIR", str(voice_dir / "custom")))
        cooldown = float(os.environ.get("CHEPAI_VOICE_COOLDOWN_SEC", "20"))
        engine = os.environ.get("CHEPAI_VOICE_ENGINE", "auto")
        return cls(
            enabled=enabled,
            voice_dir=voice_dir,
            custom_dir=custom_dir,
            cooldown_sec=cooldown,
            engine=engine,
        )

    def shutdown(self, timeout: float = 3.0) -> None:
        if not self.enabled or self._thread is None:
            return
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=timeout)
        self._thread = None

    def announce(
        self,
        alert_type: str,
        *,
        camera_id: int = 0,
        text: str | None = None,
        ignore_cooldown: bool = False,
    ) -> bool:
        """Enqueue a phrase. Returns False if skipped (disabled / cooldown / already queued)."""
        if not self.enabled or self._stop.is_set():
            return False
        phrase = (text or ALERT_PHRASES.get(alert_type) or f"请注意，检测到{alert_type}告警").strip()
        if not phrase:
            return False

        now = time.monotonic()
        with self._lock:
            last = self._last_spoken.get(alert_type, 0.0)
            if (
                not ignore_cooldown
                and self.cooldown_sec > 0
                and now - last < self.cooldown_sec
            ):
                return False
            if alert_type in self._pending_types or self._speaking_type == alert_type:
                return False
            self._pending_types.add(alert_type)

        job = VoiceJob(alert_type=alert_type, text=phrase, camera_id=camera_id)
        try:
            self._q.put_nowait(job)
            return True
        except queue.Full:
            with self._lock:
                self._pending_types.discard(alert_type)
            logger.warning("voice queue full, drop type=%s", alert_type)
            return False

    def _resolve_engine(self) -> str:
        if self.engine != "auto":
            return self.engine
        if self.voice_dir and self.voice_dir.is_dir():
            return "wav"
        if shutil.which("espeak-ng") or shutil.which("espeak"):
            return "espeak"
        return "log"

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:
                break
            with self._lock:
                self._pending_types.discard(job.alert_type)
                self._speaking_type = job.alert_type
            try:
                self._play(job)
                with self._lock:
                    self._last_spoken[job.alert_type] = time.monotonic()
            except Exception as exc:  # noqa: BLE001
                logger.exception("voice play failed type=%s: %s", job.alert_type, exc)
            finally:
                with self._lock:
                    self._speaking_type = None
                self._q.task_done()

    def _play(self, job: VoiceJob) -> None:
        engine = self._resolve_engine()
        logger.info(
            "voice speak camera=%s type=%s engine=%s text=%s",
            job.camera_id,
            job.alert_type,
            engine,
            job.text,
        )
        if engine == "wav":
            if self._play_wav(job.alert_type):
                return
            # wav 缺失则降级
            engine = "espeak" if (shutil.which("espeak-ng") or shutil.which("espeak")) else "log"
        if engine == "espeak":
            self._play_espeak(job.text)
            return
        # log-only：无声卡/未装 TTS 时仍保持顺序节奏，避免 silently 瞬间清空队列
        time.sleep(min(4.0, 0.35 * max(1, len(job.text) // 2)))

    def _play_wav(self, alert_type: str) -> bool:
        path = self._wav_path(alert_type)
        if path is None:
            logger.warning("voice wav missing: type=%s", alert_type)
            return False
        player = shutil.which("aplay") or shutil.which("paplay") or shutil.which("ffplay")
        if not player:
            return False
        cmd = [player, str(path)]
        if player.endswith("aplay"):
            # Prefer USB/explicit device: CHEPAI_VOICE_ALSA_DEVICE=plughw:Device,0
            alsa_dev = os.environ.get("CHEPAI_VOICE_ALSA_DEVICE", "").strip()
            if alsa_dev:
                cmd = [player, "-D", alsa_dev, "-q", str(path)]
            else:
                cmd = [player, "-q", str(path)]
        elif player.endswith("ffplay"):
            cmd = [player, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
        ret = subprocess.run(cmd, check=False, timeout=60, capture_output=True)
        if ret.returncode != 0:
            logger.warning(
                "voice aplay failed code=%s stderr=%s",
                ret.returncode,
                (ret.stderr or b"")[:300].decode("utf-8", "replace"),
            )
            return False
        return True

    def _wav_path(self, alert_type: str) -> Path | None:
        names = [f"{alert_type}.wav"]
        if alert_type == "bus_in_restricted":
            names.append("non_sedan.wav")
        for directory in (self.custom_dir, self.voice_dir):
            if directory is None:
                continue
            for name in names:
                candidate = directory / name
                if candidate.is_file():
                    return candidate
        return None

    def _play_espeak(self, text: str) -> None:
        bin_name = shutil.which("espeak-ng") or shutil.which("espeak")
        if not bin_name:
            time.sleep(2.0)
            return
        # cmn/zh 视板端音色包而定；失败也不抛到上层打断队列
        for voice in ("cmn", "zh", "zh-cn", "Mandarin"):
            ret = subprocess.run(
                [bin_name, "-v", voice, "-s", "160", text],
                check=False,
                timeout=60,
                capture_output=True,
            )
            if ret.returncode == 0:
                return
        subprocess.run([bin_name, "-s", "160", text], check=False, timeout=60)
