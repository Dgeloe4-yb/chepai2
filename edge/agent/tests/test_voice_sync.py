"""Voice overlay: custom cloud WAV first, then local factory default."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.voice import VoiceAnnouncer
from chepai_edge.voice_sync import VoicePackSync


class _FakeBackend:
    def __init__(self) -> None:
        self.manifest: dict = {"clips": []}
        self.files: dict[str, bytes] = {}

    def fetch_voice_manifest(self, _edge_box_id: str) -> dict:
        return self.manifest

    def download_bytes(self, url: str) -> bytes:
        return self.files[url]


def test_wav_prefers_custom(tmp_path: Path) -> None:
    default_dir = tmp_path / "voice"
    custom_dir = default_dir / "custom"
    default_dir.mkdir()
    custom_dir.mkdir()
    (default_dir / "oil_car.wav").write_bytes(b"DEFAULT")
    (custom_dir / "oil_car.wav").write_bytes(b"CUSTOM")
    ann = VoiceAnnouncer(enabled=False, voice_dir=default_dir, custom_dir=custom_dir, engine="wav")
    assert ann._wav_path("oil_car") == custom_dir / "oil_car.wav"
    (custom_dir / "oil_car.wav").unlink()
    assert ann._wav_path("oil_car") == default_dir / "oil_car.wav"


def test_sync_writes_custom_and_restores_default(tmp_path: Path) -> None:
    custom_dir = tmp_path / "custom"
    backend = _FakeBackend()
    backend.files["/api/edge/voice/box/oil_car"] = b"RIFF....WAVE"
    backend.manifest = {
        "clips": [
            {
                "alertType": "oil_car",
                "sha256": "x",
                "url": "/api/edge/voice/box/oil_car",
            }
        ]
    }
    sync = VoicePackSync(backend, "box", custom_dir, interval_sec=30)
    sync.sync_once()
    dest = custom_dir / "oil_car.wav"
    assert dest.is_file()
    assert dest.read_bytes() == b"RIFF....WAVE"

    backend.manifest = {"clips": []}
    sync.sync_once()
    assert not dest.exists()
