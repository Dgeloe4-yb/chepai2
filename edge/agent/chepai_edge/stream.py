"""Single camera RTSP worker thread."""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Callable

import cv2
import numpy as np

from chepai_edge.alerts import AlertEmitter
from chepai_edge.backend import CameraConfig
from chepai_edge.pipeline import AlertCandidate, DebugFrameResult, FramePipeline, merge_rules

logger = logging.getLogger(__name__)

# Serialize OpenCV FFmpeg option env + open (process-global env otherwise races).
_OPEN_CAP_LOCK = threading.Lock()


def open_capture(
    rtsp_url: str,
    *,
    low_latency: bool = True,
    read_timeout_sec: float = 5.0,
) -> cv2.VideoCapture:
    """Open RTSP with minimal FFmpeg buffering (reduces preview lag)."""
    with _OPEN_CAP_LOCK:
        if low_latency:
            timeout_us = max(1, int(read_timeout_sec * 1_000_000))
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;tcp|"
                "fflags;nobuffer|"
                "flags;low_delay|"
                "max_delay;0|"
                "reorder_queue_size;0|"
                f"stimeout;{timeout_us}|"
                f"rw_timeout;{timeout_us}"
            )
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap


class TimedFrameGrabber:
    """Background reader so a stuck cap.read() does not stall the camera worker.

    stop() releases the capture (often unblocks FFmpeg read), then joins with a
    deadline. If the reader still does not exit, it is abandoned as a daemon
    orphan and must not touch this grabber's queue/cap again.
    """

    _orphan_count = 0
    _orphan_lock = threading.Lock()

    def __init__(self, cap: cv2.VideoCapture, read_timeout_sec: float = 5.0) -> None:
        self._cap_lock = threading.Lock()
        self._cap: cv2.VideoCapture | None = cap
        self._read_timeout_sec = max(0.5, float(read_timeout_sec))
        self._queue: queue.Queue[tuple[bool, np.ndarray | None]] = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="frame-grabber", daemon=True)
        self._started = False
        self._join_done = False
        # Updated on the grabber thread; watchdog reads it from the main thread.
        self.last_ok_at: float = 0.0

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def is_reader_alive(self) -> bool:
        return self._started and self._thread.is_alive() and not self._stop.is_set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._cap_lock:
                cap = self._cap
            if cap is None:
                break
            try:
                ok, frame = cap.read()
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                logger.warning("frame-grabber read raised: %s", exc)
                time.sleep(0.05)
                continue
            if self._stop.is_set():
                break
            if ok and frame is not None:
                self.last_ok_at = time.monotonic()
            item = (bool(ok), frame if ok else None)
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            try:
                self._queue.put(item, block=False)
            except queue.Full:
                pass
            if not ok:
                time.sleep(0.05)

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._stop.is_set():
            return False, None
        if self._started and not self._thread.is_alive():
            return False, None
        try:
            return self._queue.get(timeout=self._read_timeout_sec)
        except queue.Empty:
            return False, None

    def _release_cap_async(self) -> None:
        """Release capture on a helper thread so a stuck release cannot hang stop()."""

        def _do() -> None:
            with self._cap_lock:
                cap = self._cap
                self._cap = None
            if cap is None:
                return
            try:
                cap.release()
            except Exception as exc:  # noqa: BLE001
                logger.warning("frame-grabber cap.release failed: %s", exc)

        helper = threading.Thread(target=_do, name="frame-grabber-release", daemon=True)
        helper.start()
        helper.join(timeout=max(2.0, self._read_timeout_sec))
        if helper.is_alive():
            logger.error(
                "frame-grabber cap.release still blocked after %.1fs; abandoning release thread",
                max(2.0, self._read_timeout_sec),
            )

    def stop(self) -> None:
        if self._join_done:
            return
        self._stop.set()
        # Wake a blocked queue.get in CameraWorker.read path.
        try:
            self._queue.put_nowait((False, None))
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait((False, None))
            except queue.Full:
                pass

        self._release_cap_async()

        if not self._started:
            self._join_done = True
            return

        join_timeout = max(3.0, self._read_timeout_sec + 2.0)
        self._thread.join(timeout=join_timeout)
        self._join_done = True
        if self._thread.is_alive():
            with TimedFrameGrabber._orphan_lock:
                TimedFrameGrabber._orphan_count += 1
                orphan_n = TimedFrameGrabber._orphan_count
            logger.error(
                "frame-grabber did not exit within %.1fs after release "
                "(orphan#%s); abandoning daemon reader — reconnect continues",
                join_timeout,
                orphan_n,
            )


class CameraWorker(threading.Thread):
    daemon = False

    def __init__(
        self,
        camera_id: int,
        get_camera: Callable[[], CameraConfig],
        get_pipeline: Callable[[], FramePipeline],
        get_emitter: Callable[[], AlertEmitter],
        get_global_rules: Callable[[], dict[str, str]],
        get_analyze_fps: Callable[[], float],
        reconnect_sec: float,
        read_timeout_sec: float = 5.0,
        get_infer_lock: Callable[[], threading.Lock] | None = None,
    ) -> None:
        super().__init__(name=f"cam-{camera_id}")
        self.camera_id = camera_id
        self.get_camera = get_camera
        self.get_pipeline = get_pipeline
        self.get_emitter = get_emitter
        self.get_global_rules = get_global_rules
        self.get_analyze_fps = get_analyze_fps
        self.reconnect_sec = reconnect_sec
        self.read_timeout_sec = read_timeout_sec
        self.get_infer_lock = get_infer_lock
        self._stop_requested = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._latest_alerts: list[AlertCandidate] = []
        self._latest_dbg: DebugFrameResult | None = None
        # RTSP URL this worker last opened (used to detect config changes).
        self.bound_rtsp_url: str | None = None
        self._grabber: TimedFrameGrabber | None = None
        now = time.monotonic()
        self.last_analyze_at: float = now

    def stop(self) -> None:
        self._stop_requested.set()

    def get_latest_frame(self, *, copy: bool = True) -> np.ndarray | None:
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy() if copy else self._latest_frame

    def get_latest_debug(self) -> tuple[list[AlertCandidate], DebugFrameResult | None]:
        with self._frame_lock:
            return list(self._latest_alerts), self._latest_dbg

    def watchdog_sample(self) -> tuple[float | None, float]:
        """(last grabber-ok time or None, last successful analyze time)."""
        grabber = self._grabber
        if grabber is None or not grabber.is_reader_alive():
            return None, self.last_analyze_at
        last_ok = grabber.last_ok_at
        if last_ok <= 0.0:
            return None, self.last_analyze_at
        return last_ok, self.last_analyze_at

    def _frame_interval(self) -> float:
        return 1.0 / max(1.0, self.get_analyze_fps())

    def run(self) -> None:
        logger.info("worker start camera=%s", self.camera_id)
        while not self._stop_requested.is_set():
            try:
                self._run_until_reconnect()
            except Exception as exc:  # noqa: BLE001
                logger.exception("worker loop failed camera=%s: %s", self.camera_id, exc)
            if not self._stop_requested.is_set():
                time.sleep(self.reconnect_sec)
        logger.info("worker stop camera=%s", self.camera_id)

    def _run_until_reconnect(self) -> None:
        cam = self.get_camera()
        if not cam.rtsp_url:
            logger.warning("camera %s has empty rtsp url", cam.camera_id)
            self.bound_rtsp_url = None
            return

        self.bound_rtsp_url = cam.rtsp_url
        cap = open_capture(cam.rtsp_url, read_timeout_sec=self.read_timeout_sec)
        if not cap.isOpened():
            logger.warning(
                "camera %s open failed, retry in %ss", cam.camera_id, self.reconnect_sec
            )
            cap.release()
            return

        logger.info("camera %s rtsp opened", cam.camera_id)
        grabber = TimedFrameGrabber(cap, self.read_timeout_sec)
        self.last_analyze_at = time.monotonic()
        self._grabber = grabber
        grabber.start()
        last_analyze = 0.0
        last_good = time.monotonic()
        fail_reads = 0
        stale_sec = max(30.0, self.read_timeout_sec * 6)
        try:
            cam = self.get_camera()
            while not self._stop_requested.is_set():
                if not grabber.is_reader_alive():
                    logger.warning(
                        "camera %s frame-grabber died unexpectedly, reconnect",
                        cam.camera_id,
                    )
                    break
                ok, frame = grabber.read()
                if not ok or frame is None:
                    fail_reads += 1
                    if fail_reads >= 30:
                        logger.warning(
                            "camera %s too many read failures, reconnect", cam.camera_id
                        )
                        break
                    if time.monotonic() - last_good >= stale_sec:
                        logger.warning(
                            "camera %s no frame for %.0fs, reconnect", cam.camera_id, stale_sec
                        )
                        break
                    continue
                fail_reads = 0
                last_good = time.monotonic()
                with self._frame_lock:
                    self._latest_frame = frame
                now = time.monotonic()
                if now - last_analyze < self._frame_interval():
                    continue
                last_analyze = now
                cam = self.get_camera()
                self._process_frame(frame, cam)
        finally:
            grabber.stop()
            self._grabber = None

    def _process_frame(self, frame: np.ndarray, cam: CameraConfig) -> None:
        try:
            rules = merge_rules(self.get_global_rules(), cam.rules)
            lock = self.get_infer_lock() if self.get_infer_lock else None
            pipeline = self.get_pipeline()
            if lock is not None:
                with lock:
                    alerts, dbg = pipeline.analyze_debug(frame, cam.rois, rules)
            else:
                alerts, dbg = pipeline.analyze_debug(frame, cam.rois, rules)
        except Exception as exc:  # noqa: BLE001
            logger.exception("analyze failed camera=%s: %s", cam.camera_id, exc)
            return
        self.last_analyze_at = time.monotonic()
        with self._frame_lock:
            self._latest_alerts = list(alerts)
            self._latest_dbg = dbg
        emitter = self.get_emitter()
        emitter.process_frame_alerts(cam.camera_id, alerts, frame)
