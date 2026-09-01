"""HTTP client for Spring Boot backend."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from edge.shared.roi_rules import Point, RoiRule

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CameraConfig:
    camera_id: int
    name: str
    rtsp_url: str
    rois: list[RoiRule] = field(default_factory=list)
    rules: dict[str, str] = field(default_factory=dict)
    channel_no: int | None = None


@dataclass
class EdgeConfig:
    edge_box_id: str
    cameras: list[CameraConfig]
    rules: dict[str, str]


def _parse_polygon(polygon_json: str) -> tuple[list[Point], bool] | None:
    try:
        data = json.loads(polygon_json)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("invalid polygon JSON: %s", exc)
        return None
    if isinstance(data, dict):
        poly = data.get("polygon") or data.get("points") or []
        normalized = bool(data.get("normalized", True))
    else:
        poly = data
        normalized = True
    try:
        points: list[Point] = [(float(p[0]), float(p[1])) for p in poly]
    except (TypeError, ValueError, IndexError) as exc:
        logger.warning("invalid polygon points: %s", exc)
        return None
    if len(points) < 3:
        logger.warning("polygon needs at least 3 points, got %s", len(points))
        return None
    return points, normalized


def parse_edge_config(payload: dict[str, Any]) -> EdgeConfig:
    cameras: list[CameraConfig] = []
    for cam in payload.get("cameras") or []:
        rois: list[RoiRule] = []
        for roi in cam.get("rois") or []:
            raw_poly = roi.get("polygonJson")
            if not raw_poly:
                logger.warning("camera %s roi %s missing polygonJson", cam.get("id"), roi.get("id"))
                continue
            parsed = _parse_polygon(str(raw_poly))
            if parsed is None:
                continue
            poly, normalized = parsed
            rois.append(
                RoiRule(
                    kind=roi.get("regionType", "parking"),
                    polygon=poly,
                    normalized=normalized,
                    name=roi.get("name") or "",
                    roi_id=int(roi.get("id", 0)),
                )
            )
        rtsp = cam.get("rtspUrl") or ""
        if not rtsp:
            logger.warning("camera %s has empty rtspUrl", cam.get("id"))
        cam_rules = {str(k): str(v) for k, v in (cam.get("rules") or {}).items()}
        channel_raw = cam.get("channelNo")
        channel_no: int | None
        try:
            channel_no = int(channel_raw) if channel_raw is not None else None
        except (TypeError, ValueError):
            channel_no = None
        cameras.append(
            CameraConfig(
                camera_id=int(cam["id"]),
                name=str(cam.get("name") or ""),
                rtsp_url=rtsp,
                rois=rois,
                rules=cam_rules,
                channel_no=channel_no,
            )
        )
    rules = {str(k): str(v) for k, v in (payload.get("rules") or {}).items()}
    return EdgeConfig(
        edge_box_id=str(payload.get("edgeBoxId") or ""),
        cameras=cameras,
        rules=rules,
    )


class BackendClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 15.0,
        edge_token: str = "",
        max_retries: int = 3,
        retry_base_sec: float = 0.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.edge_token = edge_token.strip()
        self.max_retries = max(1, max_retries)
        self.retry_base_sec = max(0.1, retry_base_sec)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.edge_token:
            h["X-Chepai-Edge-Token"] = self.edge_token
        if extra:
            h.update(extra)
        return h

    def _retry(self, op_name: str, fn: Callable[[], T]) -> T:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            if attempt > 0:
                delay = self.retry_base_sec * (2 ** (attempt - 1))
                time.sleep(delay)
            try:
                return fn()
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_exc = exc
                logger.warning("%s attempt %s/%s failed: %s", op_name, attempt + 1, self.max_retries, exc)
        assert last_exc is not None
        raise last_exc

    def _get_json(self, path: str) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            req = Request(f"{self.base_url}{path}", method="GET", headers=self._headers())
            with urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))

        return self._retry(f"GET {path}", _do)

    def _post_json(self, path: str, body: dict[str, Any], extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)

        def _do() -> dict[str, Any]:
            req = Request(
                f"{self.base_url}{path}",
                data=data,
                method="POST",
                headers=self._headers(headers),
            )
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}

        return self._retry(f"POST {path}", _do)

    def _put_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")

        def _do() -> dict[str, Any]:
            req = Request(
                f"{self.base_url}{path}",
                data=data,
                method="PUT",
                headers=self._headers({"Content-Type": "application/json"}),
            )
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}

        return self._retry(f"PUT {path}", _do)

    def upload_snapshot(self, filename: str, jpeg_bytes: bytes) -> str:
        boundary = uuid.uuid4().hex
        parts: list[bytes] = []
        disposition = (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        )
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(disposition.encode())
        parts.append(jpeg_bytes)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(parts)

        def _do() -> str:
            req = Request(
                f"{self.base_url}/api/snapshots",
                data=body,
                method="POST",
                headers=self._headers(
                    {"Content-Type": f"multipart/form-data; boundary={boundary}"}
                ),
            )
            with urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            path = payload.get("snapshotPath") or payload.get("path")
            if not path:
                raise ValueError("upload_snapshot: missing snapshotPath in response")
            return str(path)

        return self._retry("upload_snapshot", _do)

    def fetch_config(self, edge_box_id: str) -> EdgeConfig:
        payload = self._get_json(f"/api/edge/config?edgeBoxId={edge_box_id}")
        return parse_edge_config(payload)

    def post_alert(
        self,
        camera_id: int,
        alert_type: str,
        score: float | None,
        snapshot_path: str | None,
        raw: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> int | None:
        body: dict[str, Any] = {
            "cameraId": camera_id,
            "alertType": alert_type,
            "rawJson": raw,
        }
        if score is not None:
            body["score"] = score
        if snapshot_path:
            body["snapshotPath"] = snapshot_path
        extra_headers: dict[str, str] = {}
        if idempotency_key:
            body["idempotencyKey"] = idempotency_key
            extra_headers["X-Idempotency-Key"] = idempotency_key
        result = self._post_json("/api/alerts", body, extra_headers=extra_headers)
        alert_id = result.get("id")
        return int(alert_id) if alert_id is not None else None

    def fetch_voice_manifest(self, edge_box_id: str) -> dict[str, Any]:
        return self._get_json(f"/api/edge/voice?edgeBoxId={edge_box_id}")

    def post_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/api/edge/heartbeat", payload)

    def post_logs(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/api/edge/logs", payload)

    def download_bytes(self, path: str) -> bytes:
        url = path if path.startswith("http") else f"{self.base_url}{path}"

        def _do() -> bytes:
            req = Request(url, method="GET", headers=self._headers())
            with urlopen(req, timeout=self.timeout) as resp:
                return resp.read()

        return self._retry(f"GET {path}", _do)

    def health(self) -> bool:
        try:
            payload = self._get_json("/api/health")
            return payload.get("status") == "UP"
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return False

    def _delete(self, path: str) -> None:
        def _do() -> None:
            req = Request(f"{self.base_url}{path}", method="DELETE", headers=self._headers())
            with urlopen(req, timeout=self.timeout) as resp:
                resp.read()

        self._retry(f"DELETE {path}", _do)

    def delete_roi(self, roi_id: int) -> None:
        self._delete(f"/api/rois/{roi_id}")

    def create_roi(
        self,
        camera_id: int,
        region_type: str,
        polygon_json: str,
        name: str | None = None,
    ) -> int:
        body: dict[str, Any] = {
            "cameraId": camera_id,
            "regionType": region_type,
            "polygonJson": polygon_json,
        }
        if name:
            body["name"] = name
        result = self._post_json("/api/rois", body)
        roi_id = result.get("id")
        if roi_id is None:
            raise ValueError("create_roi: missing id in response")
        return int(roi_id)

    def update_camera(
        self,
        camera_id: int,
        *,
        name: str,
        rtsp_url: str | None,
        channel_no: int | None,
        edge_box_id: str | None,
    ) -> None:
        body: dict[str, Any] = {
            "name": name,
            "rtspUrl": rtsp_url,
            "channelNo": channel_no,
            "edgeBoxId": edge_box_id,
        }
        self._put_json(f"/api/cameras/{camera_id}", body)
