"""Unit tests for edge config parsing."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.backend import parse_edge_config


def test_parse_edge_config_merges_camera_rules() -> None:
    payload = {
        "edgeBoxId": "rk3588-01",
        "rules": {"vehicle_conf": "0.4"},
        "cameras": [
            {
                "id": 1,
                "name": "cam1",
                "rtspUrl": "rtsp://x",
                "rules": {"gun_conf": "0.5"},
                "rois": [
                    {
                        "id": 10,
                        "regionType": "pile",
                        "polygonJson": '{"polygon":[[0.1,0.1],[0.9,0.1],[0.9,0.9]],"normalized":true}',
                    }
                ],
            }
        ],
    }
    cfg = parse_edge_config(payload)
    assert cfg.cameras[0].rules["gun_conf"] == "0.5"
    assert len(cfg.cameras[0].rois) == 1


def test_parse_edge_config_skips_bad_polygon() -> None:
    payload = {
        "edgeBoxId": "box",
        "cameras": [
            {
                "id": 2,
                "rtspUrl": "rtsp://y",
                "rois": [{"id": 1, "polygonJson": "not-json"}],
            }
        ],
    }
    cfg = parse_edge_config(payload)
    assert cfg.cameras[0].rois == []
