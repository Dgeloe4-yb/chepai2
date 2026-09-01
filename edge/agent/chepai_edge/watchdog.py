"""systemd sd_notify watchdog: READY / WATCHDOG / STOPPING.

The main loop pets the watchdog only when analysis is still making progress.
Grabber timestamps stay fresh during an NPU hang (FFmpeg keeps decoding);
analyze timestamps freeze. That is the hang signal. A dark RTSP stream
freezes the grabber too, so we keep petting — camera outage is not a
wedged process.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)

# Pet at least twice per WatchdogSec; skip-log is rate-limited separately.
_SKIP_LOG_SEC = 10.0


def watchdog_timeout_sec() -> float | None:
    """Interval systemd expects, from WATCHDOG_USEC. None if watchdog is off."""
    raw = os.environ.get("WATCHDOG_USEC", "").strip()
    if not raw:
        return None
    try:
        usec = int(raw)
    except ValueError:
        logger.warning("invalid WATCHDOG_USEC=%r", raw)
        return None
    if usec <= 0:
        return None
    return usec / 1_000_000.0


def notify(payload: str) -> bool:
    """Send an sd_notify datagram. No-op (False) when NOTIFY_SOCKET is unset."""
    path = os.environ.get("NOTIFY_SOCKET", "").strip()
    if not path:
        return False
    if not hasattr(socket, "AF_UNIX"):
        logger.debug("sd_notify skipped: AF_UNIX not available")
        return False
    data = payload.encode("utf-8")
    sock: socket.socket | None = None
    try:
        if path.startswith("@"):
            addr = "\0" + path[1:]
        else:
            addr = path
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(addr)
        sock.sendall(data)
        return True
    except OSError as exc:
        logger.warning("sd_notify failed: %s", exc)
        return False
    finally:
        if sock is not None:
            sock.close()


def notify_ready() -> bool:
    return notify("READY=1\nWATCHDOG=1")


def notify_pet() -> bool:
    return notify("WATCHDOG=1")


def notify_stopping() -> bool:
    return notify("STOPPING=1")


def analysis_healthy(
    samples: Sequence[tuple[int, float | None, float]],
    *,
    now: float,
    watchdog_sec: float,
    frame_fresh_sec: float,
) -> tuple[bool, str]:
    """Return (ok, reason).

    Each sample is (camera_id, last_grab_ok_at | None, last_analyze_ok_at).
    ``last_grab_ok_at is None`` means this worker is not currently pulling
    frames (no grabber, empty RTSP, reconnecting).
    """
    if watchdog_sec <= 0:
        return True, "watchdog-disabled"
    stale_after = max(1.0, watchdog_sec * 0.8)
    receiving: list[tuple[int, float]] = []
    for camera_id, grab_at, analyze_at in samples:
        if grab_at is None:
            continue
        if now - grab_at <= frame_fresh_sec:
            receiving.append((camera_id, analyze_at))
    if not receiving:
        return True, "idle-no-live-frames"
    fresh = [cid for cid, analyze_at in receiving if now - analyze_at <= stale_after]
    if fresh:
        return True, f"analyze-ok cameras={fresh}"
    stale = [cid for cid, _ in receiving]
    return False, (
        f"analyze stalled cameras={stale} "
        f"(no successful infer within {stale_after:.0f}s while frames still arrive)"
    )


def samples_from_workers(workers: Sequence[Any]) -> list[tuple[int, float | None, float]]:
    out: list[tuple[int, float | None, float]] = []
    for worker in workers:
        is_alive = getattr(worker, "is_alive", None)
        if callable(is_alive) and not is_alive():
            continue
        sample_fn = getattr(worker, "watchdog_sample", None)
        if not callable(sample_fn):
            continue
        grab_at, analyze_at = sample_fn()
        camera_id = int(getattr(worker, "camera_id", 0))
        out.append((camera_id, grab_at, analyze_at))
    return out


def frame_fresh_sec(watchdog_sec: float) -> float:
    """How recent a grabber frame must be to count as 'live video'."""
    return max(15.0, min(watchdog_sec * 0.4, 30.0))


class SystemdWatchdog:
    """Main-thread helper: READY once, then pet or skip each loop."""

    def __init__(self) -> None:
        self._last_skip_log = 0.0
        self._ready_sent = False

    def ready(self) -> None:
        timeout = watchdog_timeout_sec()
        sent = notify_ready()
        self._ready_sent = sent
        if sent:
            logger.info(
                "systemd notify READY=1 watchdog=%.0fs",
                timeout or 0.0,
            )
        elif timeout is not None:
            logger.warning(
                "WATCHDOG_USEC set but NOTIFY_SOCKET missing; systemd watchdog will kill us"
            )

    def stopping(self) -> None:
        notify_stopping()

    def beat(self, workers: Sequence[Any], *, now: float | None = None) -> bool:
        """Pet if healthy. Returns False when we intentionally skipped a pet."""
        timeout = watchdog_timeout_sec()
        if timeout is None:
            return True
        stamp = time.monotonic() if now is None else now
        ok, reason = analysis_healthy(
            samples_from_workers(workers),
            now=stamp,
            watchdog_sec=timeout,
            frame_fresh_sec=frame_fresh_sec(timeout),
        )
        if ok:
            notify_pet()
            return True
        if stamp - self._last_skip_log >= _SKIP_LOG_SEC:
            logger.error("systemd watchdog skip: %s", reason)
            self._last_skip_log = stamp
        return False
