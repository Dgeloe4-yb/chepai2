"""Unit tests for sequential Voice announcer."""

from __future__ import annotations

import sys
import time
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.voice import VoiceAnnouncer


def test_sequential_no_overlap() -> None:
    spoken: list[str] = []

    ann = VoiceAnnouncer(enabled=True, engine="log", cooldown_sec=0.0, queue_max=16)

    # monkeypatch play to record order and sleep briefly
    def _play(job):  # type: ignore[no-untyped-def]
        spoken.append(job.alert_type)
        time.sleep(0.05)

    ann._play = _play  # type: ignore[method-assign]
    assert ann.announce("dual_slot")
    assert ann.announce("car_in_bus_slot")
    # same type while pending/speaking should be skipped
    assert not ann.announce("dual_slot")
    time.sleep(0.35)
    assert spoken == ["dual_slot", "car_in_bus_slot"]
    ann.shutdown()


def test_cooldown_skips() -> None:
    ann = VoiceAnnouncer(enabled=True, engine="log", cooldown_sec=10.0)
    spoken: list[str] = []

    def _play(job):  # type: ignore[no-untyped-def]
        spoken.append(job.alert_type)

    ann._play = _play  # type: ignore[method-assign]
    assert ann.announce("mini_ad")
    time.sleep(0.15)
    assert not ann.announce("mini_ad")
    assert spoken == ["mini_ad"]
    ann.shutdown()


if __name__ == "__main__":
    test_sequential_no_overlap()
    test_cooldown_skips()
    print("ok")
