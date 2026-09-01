"""
生产 agent 内嵌本地 API：Flutter 客户端对接用。

与生产同进程：共用海康 RTSP worker 帧、pipeline、park_align、ROI（本地 edge_config.json）。
默认端口 8765（CHEPAI_LOCAL_API_PORT）。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
import threading
import time
from cgi import FieldStorage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse, urlunparse

import cv2
import numpy as np

from chepai_edge.debug_viz import debug_result_to_json, render_debug_frame
from chepai_edge.pipeline import merge_rules
from edge.shared.park_align import (
    build_profile_from_pairs,
    load_profile,
    profile_to_dict,
    save_profile,
)
from edge.shared.roi_rules import filter_viz_rois

if TYPE_CHECKING:
    from chepai_edge.main import EdgeAgent

logger = logging.getLogger(__name__)

_HOST_RE = re.compile(
    r"^(?:"
    r"(?:\d{1,3}\.){3}\d{1,3}"  # IPv4
    r"|(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*)"  # hostname
    r")$"
)


def rewrite_rtsp_endpoint(
    rtsp_url: str,
    *,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    channel: int | None = None,
) -> str:
    """Rewrite host/port/user/pass/Hik channel while keeping the rest of the URL."""
    raw = (rtsp_url or "").strip()
    if not raw and host:
        user = username or "admin"
        pwd = password if password is not None else ""
        p = int(port) if port is not None else 554
        ch = int(channel) if channel is not None else 101
        auth = f"{quote(user, safe='')}:{quote(pwd, safe='')}@" if user else ""
        return f"rtsp://{auth}{host}:{p}/Streaming/Channels/{ch}"
    if not raw:
        raise ValueError("当前无 RTSP，请提供 host 以生成海康默认地址")

    u = urlparse(raw)
    scheme = u.scheme or "rtsp"
    user = username if username is not None else u.username
    pwd = password if password is not None else u.password
    hostname = (host or u.hostname or "").strip()
    if not hostname:
        raise ValueError("host required")
    if host is not None and not _HOST_RE.match(hostname):
        raise ValueError(f"非法主机地址: {hostname}")
    p = int(port) if port is not None else (u.port or 554)

    if user:
        auth = quote(user, safe="")
        if pwd is not None:
            auth += f":{quote(pwd, safe='')}"
        netloc = f"{auth}@{hostname}:{p}"
    else:
        netloc = f"{hostname}:{p}"

    path = u.path or ""
    if channel is not None:
        ch = int(channel)
        if re.search(r"/Streaming/Channels/\d+", path, flags=re.IGNORECASE):
            path = re.sub(
                r"/Streaming/Channels/\d+",
                f"/Streaming/Channels/{ch}",
                path,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            path = f"/Streaming/Channels/{ch}"

    return urlunparse((scheme, netloc, path, "", u.query, u.fragment))


def _encode_preview(frame: np.ndarray, max_width: int, quality: int) -> tuple[bytes | None, int, int]:
    h, w = frame.shape[:2]
    out_w, out_h = w, h
    if w > max_width:
        scale = max_width / w
        out_w = int(w * scale)
        out_h = int(h * scale)
        frame = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return None, out_w, out_h
    return buf.tobytes(), out_w, out_h


class LocalApiFacade:
    """Thin facade over EdgeAgent for client-compatible HTTP routes."""

    def __init__(self, agent: EdgeAgent) -> None:
        self.agent = agent
        self.preview_width = int(os.environ.get("CHEPAI_API_PREVIEW_WIDTH", "1280"))
        self.preview_quality = int(os.environ.get("CHEPAI_API_PREVIEW_QUALITY", "70"))
        self._infer_video_path: Path | None = None

    @property
    def cfg(self):
        return self.agent.cfg

    @property
    def config_store(self):
        return self.agent.config_store

    def infer_video_file(self) -> Path | None:
        return self._infer_video_path

    def park_align_summary(self) -> dict[str, Any]:
        path = self.cfg.resolve_park_align()
        profile = load_profile(path if path.is_file() else None)
        if profile is None:
            return {"ready": False, "path": str(path), "anchors": 0}
        return {
            "ready": True,
            "path": str(path),
            "anchors": len(profile.anchors),
            "dxThreshold": profile.dx_threshold,
            "profile": profile_to_dict(profile),
        }

    def rois_for_api(self, cam) -> list[dict[str, Any]]:
        return [
            {
                "kind": r.kind,
                "name": r.name or "",
                "roiId": r.roi_id,
                "polygon": list(r.polygon),
            }
            for r in filter_viz_rois(cam.rois)
        ]

    def select_camera(self, camera_id: int) -> None:
        self.agent.select_api_camera(camera_id)

    def reload_config(self) -> None:
        self.agent.reload_config()

    def get_preview_jpeg(self) -> bytes | None:
        frame = self.agent.get_api_frame()
        if frame is None:
            return None
        jpeg, _, _ = _encode_preview(frame, self.preview_width, self.preview_quality)
        return jpeg

    def get_state(self) -> dict[str, Any]:
        edge = self.agent.config
        cam = self.agent.get_api_camera()
        if edge is None or cam is None:
            return {"cameras": [], "detections": {}, "parkAlign": self.park_align_summary()}

        frame = self.agent.get_api_frame()
        alerts, dbg = self.agent.get_api_debug()
        if frame is not None:
            h, w = frame.shape[:2]
            if w > self.preview_width:
                scale = self.preview_width / w
                display_w = int(w * scale)
                display_h = int(h * scale)
            else:
                display_w, display_h = w, h
        else:
            w, h = 1280, 720
            display_w, display_h = w, h

        detections: dict[str, Any] = {}
        if dbg is not None:
            detections = debug_result_to_json(dbg, alerts)

        return {
            "cameraId": cam.camera_id,
            "frameW": w,
            "frameH": h,
            "displayFrameW": display_w,
            "displayFrameH": display_h,
            "cameras": [
                {
                    "id": c.camera_id,
                    "name": c.name,
                    "rtsp": bool(c.rtsp_url),
                    "rtspUrl": c.rtsp_url,
                    "host": (urlparse(c.rtsp_url).hostname if c.rtsp_url else None),
                    "port": (urlparse(c.rtsp_url).port if c.rtsp_url else None),
                    "channelNo": c.channel_no,
                }
                for c in edge.cameras
            ],
            "rois": self.rois_for_api(cam),
            "detections": detections,
            "parkAlign": self.park_align_summary(),
            "mode": "production",
        }

    def _analyze_frame(self, frame: np.ndarray, *, use_rois: bool = True):
        cam = self.agent.get_api_camera()
        edge = self.agent.config
        if cam is None or edge is None:
            raise RuntimeError("pipeline/camera not ready")
        rules = merge_rules(edge.rules, cam.rules)
        rois = cam.rois if use_rois else []
        with self.agent.infer_lock:
            pipeline = self.agent._get_pipeline()
            alerts, dbg = pipeline.analyze_debug(frame, rois, rules)
        vis = render_debug_frame(frame, rois, dbg, alerts)
        return alerts, dbg, vis, rois, rules

    def infer_frame(self, frame: np.ndarray, *, use_rois: bool = True) -> dict[str, Any]:
        alerts, dbg, vis, _rois, _rules = self._analyze_frame(frame, use_rois=use_rois)
        h, w = frame.shape[:2]
        jpeg, display_w, display_h = _encode_preview(vis, self.preview_width, self.preview_quality)
        return {
            "frameW": w,
            "frameH": h,
            "displayFrameW": display_w,
            "displayFrameH": display_h,
            "detections": debug_result_to_json(dbg, alerts),
            "imageBase64": base64.b64encode(jpeg).decode("ascii") if jpeg else None,
            "parkAlign": self.park_align_summary(),
        }

    def infer_image_bytes(self, raw: bytes, *, use_rois: bool = True) -> dict[str, Any]:
        arr = np.frombuffer(raw, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("无法解码图片")
        return self.infer_frame(frame, use_rois=use_rois)

    def infer_video_bytes(
        self,
        raw: bytes,
        *,
        max_frames: int = 300,
        every_n: int = 15,
        use_rois: bool = True,
    ) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(raw)
            in_path = tmp.name
        cap = cv2.VideoCapture(in_path)
        if not cap.isOpened():
            os.unlink(in_path)
            raise RuntimeError("无法打开视频文件")
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if width <= 0 or height <= 0:
            cap.release()
            os.unlink(in_path)
            raise RuntimeError("无法读取视频尺寸")

        out_path = (self.cfg.snapshot_dir / "infer_latest.mp4").resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        if not writer.isOpened():
            cap.release()
            os.unlink(in_path)
            raise RuntimeError("无法创建输出视频")

        processed = 0
        read_idx = 0
        written = 0
        timeline: list[dict[str, Any]] = []
        last_result: dict[str, Any] | None = None
        last_vis: np.ndarray | None = None
        try:
            while written < max_frames:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                read_idx += 1
                should_infer = every_n <= 1 or (read_idx - 1) % every_n == 0
                if should_infer:
                    processed += 1
                    alerts, dbg, vis, _rois, _rules = self._analyze_frame(frame, use_rois=use_rois)
                    last_vis = vis
                    h, w = frame.shape[:2]
                    jpeg, display_w, display_h = _encode_preview(
                        vis, self.preview_width, self.preview_quality
                    )
                    last_result = {
                        "frameW": w,
                        "frameH": h,
                        "displayFrameW": display_w,
                        "displayFrameH": display_h,
                        "detections": debug_result_to_json(dbg, alerts),
                        "imageBase64": base64.b64encode(jpeg).decode("ascii") if jpeg else None,
                        "parkAlign": self.park_align_summary(),
                    }
                    if alerts:
                        timeline.append(
                            {
                                "frame": read_idx,
                                "timeSec": round((read_idx - 1) / fps, 2),
                                "alerts": [
                                    {"type": a.alert_type, "score": a.score, "raw": a.raw}
                                    for a in alerts
                                ],
                            }
                        )
                    writer.write(vis)
                else:
                    writer.write(last_vis if last_vis is not None else frame)
                written += 1
        finally:
            writer.release()
            cap.release()
            os.unlink(in_path)

        if last_result is None:
            if out_path.is_file():
                out_path.unlink(missing_ok=True)
            raise RuntimeError("视频无有效帧")

        self._infer_video_path = out_path
        return {
            "ok": True,
            "totalFrames": total or read_idx,
            "processedFrames": processed,
            "writtenFrames": written,
            "fps": fps,
            "everyN": every_n,
            "timeline": timeline,
            "frameW": last_result["frameW"],
            "frameH": last_result["frameH"],
            "displayFrameW": last_result.get("displayFrameW"),
            "displayFrameH": last_result.get("displayFrameH"),
            "detections": last_result["detections"],
            "imageBase64": last_result.get("imageBase64"),
            "parkAlign": last_result.get("parkAlign"),
            "videoUrl": "/api/infer/video/result.mp4",
        }

    def calib_park_align_from_frame(
        self,
        frame: np.ndarray,
        *,
        dx_threshold: float = 0.15,
    ) -> dict[str, Any]:
        cam = self.agent.get_api_camera()
        edge = self.agent.config
        if cam is None or edge is None:
            raise RuntimeError("pipeline/camera not ready")
        rules = merge_rules(edge.rules, cam.rules)
        with self.agent.infer_lock:
            pipeline = self.agent._get_pipeline()
            old = pipeline.park_align
            pipeline.park_align = None
            try:
                _alerts, dbg = pipeline.analyze_debug(frame, [], rules)
            finally:
                pipeline.park_align = old

        pairs: list[tuple[tuple[float, float, float, float], tuple[float, float, float, float]]] = []
        for v in dbg.vehicles:
            vx1, vy1, vx2, vy2 = v.xyxy
            best = None
            best_conf = -1.0
            for plate, _crop in dbg.plates:
                pcx = (plate.xyxy[0] + plate.xyxy[2]) / 2
                pcy = (plate.xyxy[1] + plate.xyxy[3]) / 2
                if vx1 <= pcx <= vx2 and vy1 <= pcy <= vy2 and plate.confidence > best_conf:
                    best = plate
                    best_conf = plate.confidence
            if best is not None:
                pairs.append((v.xyxy, best.xyxy))
        if not pairs:
            raise RuntimeError("标定失败：未同时检出车辆与车牌")

        profile = build_profile_from_pairs(pairs, frame.shape[1], dx_threshold=dx_threshold)
        out = self.cfg.resolve_park_align()
        save_profile(out, profile)
        with self.agent.infer_lock:
            pipeline = self.agent._get_pipeline()
            pipeline.park_align = profile
        return {
            "ok": True,
            "path": str(out),
            "anchors": len(profile.anchors),
            "profile": profile_to_dict(profile),
        }

    def calib_park_align_latest(self, dx_threshold: float = 0.15) -> dict[str, Any]:
        frame = self.agent.get_api_frame()
        if frame is None:
            raise RuntimeError("暂无视频帧，请稍后再试")
        return self.calib_park_align_from_frame(frame, dx_threshold=dx_threshold)

    def calib_park_align_jpeg(self, jpeg_bytes: bytes, dx_threshold: float = 0.15) -> dict[str, Any]:
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("无法解码标定图片")
        return self.calib_park_align_from_frame(frame, dx_threshold=dx_threshold)

    def save_roi(
        self,
        camera_id: int,
        region_type: str,
        polygon: list[list[float]],
        name: str | None,
    ) -> int:
        roi_id = self.config_store.add_roi(camera_id, region_type, polygon, name)
        self.reload_config()
        return roi_id

    def delete_roi(self, roi_id: int) -> None:
        self.config_store.delete_roi(roi_id)
        self.reload_config()

    def update_camera_endpoint(
        self,
        camera_id: int,
        *,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        channel: int | None = None,
        rtsp_url: str | None = None,
    ) -> dict[str, Any]:
        cam = None
        with self.agent._lock:
            cam = self.agent._cameras.get(camera_id)
        if cam is None:
            raise KeyError(f"camera {camera_id} not found")

        if rtsp_url and rtsp_url.strip():
            new_url = rtsp_url.strip()
        else:
            if not host or not str(host).strip():
                raise ValueError("host 或 rtspUrl 至少提供一个")
            new_url = rewrite_rtsp_endpoint(
                cam.rtsp_url,
                host=str(host).strip(),
                port=port,
                username=username,
                password=password,
                channel=channel,
            )

        parsed = urlparse(new_url)
        if parsed.scheme not in {"rtsp", "rtsps"}:
            raise ValueError("仅支持 rtsp/rtsps 地址")
        if not parsed.hostname:
            raise ValueError("RTSP 缺少主机地址")

        self.config_store.update_camera(
            camera_id,
            name=cam.name or f"camera-{camera_id}",
            rtsp_url=new_url,
            channel_no=channel if channel is not None else cam.channel_no,
        )
        self.reload_config()
        return {
            "ok": True,
            "cameraId": camera_id,
            "rtspUrl": new_url,
            "host": parsed.hostname,
            "port": parsed.port or 554,
        }


def _make_handler(session: LocalApiFacade) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ChepaiLocalApi/1.0"

        def log_message(self, fmt: str, *args: object) -> None:
            logger.debug("http " + fmt, *args)

        def _send_json(self, code: int, obj: Any) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n) if n else b"{}"
            return json.loads(raw.decode("utf-8"))

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/state.json":
                self._send_json(200, session.get_state())
                return
            if path == "/api/park-align":
                self._send_json(200, session.park_align_summary())
                return
            if path in ("/api/preview.jpg", "/stream.mjpg"):
                jpeg = session.get_preview_jpeg()
                if not jpeg:
                    self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "no frame yet")
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(jpeg)
                return
            if path == "/api/infer/video/result.mp4":
                video_path = session.infer_video_file()
                if video_path is None or not video_path.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND, "no infer video yet")
                    return
                data = video_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
                return
            if path in ("/", "/index.html"):
                msg = b"Chepai edge production local API. Use Flutter client on :8765."
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/infer/video" and "multipart/form-data" in self.headers.get(
                "Content-Type", ""
            ):
                try:
                    ctype = self.headers.get("Content-Type", "")
                    n = int(self.headers.get("Content-Length", "0"))
                    form = FieldStorage(
                        fp=self.rfile,
                        headers=self.headers,
                        environ={
                            "REQUEST_METHOD": "POST",
                            "CONTENT_TYPE": ctype,
                            "CONTENT_LENGTH": str(n),
                        },
                    )
                    if "file" not in form or not getattr(form["file"], "file", None):
                        self._send_json(400, {"error": "missing file field"})
                        return
                    data = form["file"].file.read()
                    every_n = int(form.getvalue("everyN", "15") or 15)
                    max_frames = int(form.getvalue("maxFrames", "300") or 300)
                    use_rois_raw = form.getvalue("useRois", "true")
                    use_rois = str(use_rois_raw).lower() not in ("false", "0", "no")
                    result = session.infer_video_bytes(
                        data,
                        max_frames=max_frames,
                        every_n=every_n,
                        use_rois=use_rois,
                    )
                    self._send_json(200, result)
                except Exception as exc:
                    logger.exception("infer video failed")
                    self._send_json(500, {"error": str(exc)})
                return
            try:
                body = self._read_json()
            except json.JSONDecodeError:
                self.send_error(HTTPStatus.BAD_REQUEST, "invalid json")
                return
            if path == "/api/refresh-config":
                session.reload_config()
                self._send_json(200, {"ok": True})
                return
            if path == "/api/select-camera":
                session.select_camera(int(body["cameraId"]))
                self._send_json(200, {"ok": True})
                return
            if path in ("/api/camera-ip", "/api/cameras/endpoint"):
                try:
                    port_raw = body.get("port")
                    channel_raw = body.get("channel")
                    if channel_raw is None:
                        channel_raw = body.get("channelNo")
                    result = session.update_camera_endpoint(
                        int(body["cameraId"]),
                        host=body.get("host") or body.get("ip"),
                        port=int(port_raw) if port_raw not in (None, "") else None,
                        username=body.get("username") or body.get("user"),
                        password=body.get("password"),
                        channel=int(channel_raw) if channel_raw not in (None, "") else None,
                        rtsp_url=body.get("rtspUrl"),
                    )
                    self._send_json(200, result)
                except KeyError as exc:
                    self._send_json(404, {"error": str(exc)})
                except Exception as exc:
                    logger.exception("update camera endpoint failed")
                    self._send_json(400, {"error": str(exc)})
                return
            if path == "/api/rois":
                try:
                    rid = session.save_roi(
                        int(body["cameraId"]),
                        str(body.get("regionType", "ad")),
                        body["polygon"],
                        body.get("name"),
                    )
                    self._send_json(201, {"id": rid})
                except Exception as exc:
                    logger.exception("save roi failed")
                    self._send_json(500, {"error": str(exc)})
                return
            if path == "/api/park-align":
                self._send_json(200, session.park_align_summary())
                return
            if path == "/api/park-align/calib":
                try:
                    thr = float(body.get("dxThreshold", 0.15))
                    if body.get("imageBase64"):
                        raw = body["imageBase64"]
                        if "," in raw:
                            raw = raw.split(",", 1)[1]
                        jpeg = base64.b64decode(raw)
                        result = session.calib_park_align_jpeg(jpeg, dx_threshold=thr)
                    else:
                        result = session.calib_park_align_latest(dx_threshold=thr)
                    self._send_json(200, result)
                except Exception as exc:
                    logger.exception("park-align calib failed")
                    self._send_json(500, {"error": str(exc)})
                return
            if path == "/api/infer/image":
                try:
                    use_rois = bool(body.get("useRois", True))
                    if not body.get("imageBase64"):
                        self._send_json(400, {"error": "imageBase64 required"})
                        return
                    raw = body["imageBase64"]
                    if "," in raw:
                        raw = raw.split(",", 1)[1]
                    data = base64.b64decode(raw)
                    result = session.infer_image_bytes(data, use_rois=use_rois)
                    self._send_json(200, result)
                except Exception as exc:
                    logger.exception("infer image failed")
                    self._send_json(500, {"error": str(exc)})
                return
            if path == "/api/infer/video":
                try:
                    every_n = int(body.get("everyN", 15))
                    max_frames = int(body.get("maxFrames", 300))
                    use_rois = bool(body.get("useRois", True))
                    if not body.get("videoBase64"):
                        self._send_json(400, {"error": "videoBase64 or multipart file required"})
                        return
                    raw = body["videoBase64"]
                    if "," in raw:
                        raw = raw.split(",", 1)[1]
                    data = base64.b64decode(raw)
                    result = session.infer_video_bytes(
                        data,
                        max_frames=max_frames,
                        every_n=every_n,
                        use_rois=use_rois,
                    )
                    self._send_json(200, result)
                except Exception as exc:
                    logger.exception("infer video failed")
                    self._send_json(500, {"error": str(exc)})
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_DELETE(self) -> None:
            path = urlparse(self.path).path
            if path.startswith("/api/rois/"):
                try:
                    roi_id = int(path.rsplit("/", 1)[-1])
                    session.delete_roi(roi_id)
                    self.send_response(HTTPStatus.NO_CONTENT)
                    self.end_headers()
                except Exception as exc:
                    logger.exception("delete roi failed")
                    self._send_json(500, {"error": str(exc)})
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

    return Handler


def start_local_api(agent: EdgeAgent) -> ThreadingHTTPServer | None:
    enabled = os.environ.get("CHEPAI_LOCAL_API", "1").lower() not in {"0", "false", "no"}
    if not enabled:
        logger.info("local API disabled (CHEPAI_LOCAL_API=0)")
        return None

    bind = os.environ.get("CHEPAI_LOCAL_API_BIND", "0.0.0.0")
    port = int(os.environ.get("CHEPAI_LOCAL_API_PORT", "8765"))
    session = LocalApiFacade(agent)
    handler = _make_handler(session)
    httpd = ThreadingHTTPServer((bind, port), handler)
    thread = threading.Thread(target=httpd.serve_forever, name="local-api", daemon=True)
    thread.start()
    logger.info("local API http://%s:%s/ (production, Flutter client)", bind, port)
    return httpd
