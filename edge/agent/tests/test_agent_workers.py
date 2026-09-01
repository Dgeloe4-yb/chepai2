"""Unit tests for edge agent worker reconciliation."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.backend import CameraConfig, EdgeConfig
from chepai_edge.config import AgentConfig
from chepai_edge.main import EdgeAgent


class DummyWorker:
    def __init__(self, camera_id: int, alive: bool) -> None:
        self.camera_id = camera_id
        self._alive = alive
        self.stopped = False

    def is_alive(self) -> bool:
        return self._alive

    def stop(self) -> None:
        self.stopped = True

    def join(self, timeout: float | None = None) -> None:
        return None


def test_sync_workers_restarts_dead_desired_worker() -> None:
    agent = EdgeAgent(AgentConfig())
    agent.workers = [DummyWorker(1, alive=False)]  # type: ignore[list-item]
    spawned: list[int] = []

    def spawn_worker(camera_id: int) -> DummyWorker:
        spawned.append(camera_id)
        return DummyWorker(camera_id, alive=True)

    agent._spawn_worker = spawn_worker  # type: ignore[method-assign]
    edge_cfg = EdgeConfig(
        edge_box_id="box",
        cameras=[CameraConfig(1, "cam1", "rtsp://example")],
        rules={},
    )

    agent._sync_workers_locked(edge_cfg)

    assert spawned == [1]
    assert len(agent.workers) == 1
    assert agent.workers[0].camera_id == 1
    assert agent.workers[0].is_alive()
