"""systemd watchdog heartbeat: pet while infer progresses, skip on NPU hang."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.watchdog import (
    SystemdWatchdog,
    analysis_healthy,
    notify,
    notify_ready,
    samples_from_workers,
    watchdog_timeout_sec,
)


def test_timeout_from_watchdog_usec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")
    assert watchdog_timeout_sec() == 60.0
    monkeypatch.setenv("WATCHDOG_USEC", "0")
    assert watchdog_timeout_sec() is None
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    assert watchdog_timeout_sec() is None


def test_healthy_idle_no_workers() -> None:
    ok, reason = analysis_healthy([], now=100.0, watchdog_sec=60.0, frame_fresh_sec=15.0)
    assert ok
    assert "idle" in reason


def test_healthy_dark_camera_does_not_trip() -> None:
    # Grabber gone / no recent frames: RTSP down, keep petting.
    ok, _ = analysis_healthy(
        [(1, None, 1.0)],
        now=100.0,
        watchdog_sec=60.0,
        frame_fresh_sec=15.0,
    )
    assert ok
    ok, _ = analysis_healthy(
        [(1, 10.0, 10.0)],
        now=100.0,
        watchdog_sec=60.0,
        frame_fresh_sec=15.0,
    )
    assert ok


def test_healthy_live_stream_recent_analyze() -> None:
    ok, reason = analysis_healthy(
        [(1, 99.0, 95.0)],
        now=100.0,
        watchdog_sec=60.0,
        frame_fresh_sec=15.0,
    )
    assert ok
    assert "analyze-ok" in reason


def test_unhealthy_frames_without_analyze() -> None:
    # Frames still arriving, last successful infer 50s ago (> 0.8 * 60).
    ok, reason = analysis_healthy(
        [(1, 99.0, 50.0)],
        now=100.0,
        watchdog_sec=60.0,
        frame_fresh_sec=15.0,
    )
    assert not ok
    assert "stalled" in reason
    assert "1" in reason


def test_one_healthy_camera_covers_the_box() -> None:
    ok, _ = analysis_healthy(
        [(1, 99.0, 50.0), (2, 99.0, 98.0)],
        now=100.0,
        watchdog_sec=60.0,
        frame_fresh_sec=15.0,
    )
    assert ok


def test_hung_camera_plus_dark_camera_trips() -> None:
    ok, _ = analysis_healthy(
        [(1, 99.0, 10.0), (2, None, 10.0)],
        now=100.0,
        watchdog_sec=60.0,
        frame_fresh_sec=15.0,
    )
    assert not ok


class _Worker:
    def __init__(self, camera_id: int, alive: bool, sample: tuple[float | None, float]) -> None:
        self.camera_id = camera_id
        self._alive = alive
        self._sample = sample

    def is_alive(self) -> bool:
        return self._alive

    def watchdog_sample(self) -> tuple[float | None, float]:
        return self._sample


def test_samples_skips_dead_and_dumb_workers() -> None:
    class Dummy:
        camera_id = 9

        def is_alive(self) -> bool:
            return True

    workers = [
        _Worker(1, True, (10.0, 9.0)),
        _Worker(2, False, (10.0, 9.0)),
        Dummy(),
    ]
    samples = samples_from_workers(workers)
    assert samples == [(1, 10.0, 9.0)]


def test_notify_noop_without_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert notify("READY=1") is False
    assert notify_ready() is False


def test_notify_abstract_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class FakeSock:
        def connect(self, addr: str) -> None:
            seen["addr"] = addr

        def sendall(self, data: bytes) -> None:
            seen["data"] = data

        def close(self) -> None:
            seen["closed"] = True

    monkeypatch.setenv("NOTIFY_SOCKET", "@/run/systemd/notify")
    monkeypatch.setattr(socket, "AF_UNIX", getattr(socket, "AF_UNIX", 1), raising=False)
    monkeypatch.setattr(socket, "socket", lambda *_a, **_k: FakeSock())
    assert notify("WATCHDOG=1") is True
    assert seen["addr"] == "\0/run/systemd/notify"
    assert seen["data"] == b"WATCHDOG=1"
    assert seen["closed"] is True


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="AF_UNIX required")
def test_notify_sends_datagram(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sock_path = str(tmp_path / "notify.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        server.bind(sock_path)
        server.settimeout(2.0)
        monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
        assert notify("READY=1\nWATCHDOG=1") is True
        data, _ = server.recvfrom(256)
        assert data == b"READY=1\nWATCHDOG=1"
    except OSError as exc:
        pytest.skip(f"unix dgram notify not usable here: {exc}")
    finally:
        server.close()


def test_beat_skips_pet_when_stalled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")
    pets: list[str] = []
    monkeypatch.setattr(
        "chepai_edge.watchdog.notify", lambda payload: pets.append(payload) or True
    )
    wd = SystemdWatchdog()
    workers = [_Worker(1, True, (100.0, 10.0))]
    assert wd.beat(workers, now=100.0) is False
    assert pets == []
    workers = [_Worker(1, True, (100.0, 99.0))]
    assert wd.beat(workers, now=100.0) is True
    assert pets == ["WATCHDOG=1"]


def test_beat_always_ok_without_watchdog_usec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    called: list[str] = []
    monkeypatch.setattr(
        "chepai_edge.watchdog.notify", lambda payload: called.append(payload) or True
    )
    wd = SystemdWatchdog()
    assert wd.beat([_Worker(1, True, (100.0, 1.0))], now=100.0) is True
    assert called == []
