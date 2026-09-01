"""Unit tests for local edge config store."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.local_config import LocalConfigStore, default_edge_config


def test_default_config_creates_camera() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "edge_config.json"
        store = LocalConfigStore(path, "rk3588-01")
        cfg = store.load()
        assert cfg.edge_box_id == "rk3588-01"
        assert len(cfg.cameras) == 1
        assert cfg.cameras[0].camera_id == 1
        assert path.is_file()


def test_roi_crud_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "edge_config.json"
        store = LocalConfigStore(path, "rk3588-01")
        store.load()
        rid = store.add_roi(1, "ad", [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]], name="ad_zone")
        assert rid == 1
        cfg = store.load()
        assert len(cfg.cameras[0].rois) == 1
        assert cfg.cameras[0].rois[0].kind == "ad"
        store.delete_roi(rid)
        cfg = store.load()
        assert cfg.cameras[0].rois == []


def test_update_camera_persists_rtsp() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "edge_config.json"
        store = LocalConfigStore(path, "rk3588-01")
        store.load()
        store.update_camera(
            1,
            name="cam-front",
            rtsp_url="rtsp://admin:pass@192.168.1.64:554/Streaming/Channels/101",
            channel_no=101,
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["cameras"][0]["rtspUrl"].startswith("rtsp://admin")
