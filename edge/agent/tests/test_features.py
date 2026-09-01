"""Feature flags from heartbeat: emit filter, skip mini_ad, journal SHA."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.alerts import AlertEmitter
from chepai_edge.backend import BackendClient
from chepai_edge.config import AgentConfig
from chepai_edge.features import parse_heartbeat_features
from chepai_edge.main import EdgeAgent
from chepai_edge.telemetry import EdgeTelemetry
from chepai_edge.voice import VoiceAnnouncer


def test_parse_heartbeat_features() -> None:
    assert parse_heartbeat_features(None) is None
    assert parse_heartbeat_features("oil_car") is None
    assert parse_heartbeat_features([]) == frozenset()
    assert parse_heartbeat_features(["oil_car", "non_sedan", "nope"]) == frozenset(
        {"oil_car", "bus_in_restricted"}
    )


def test_apply_features_sets_skip_mini_ad_without_rebuild() -> None:
    agent = EdgeAgent(AgentConfig())

    class DummyPipe:
        skip_mini_ad = False

    dummy = DummyPipe()
    agent._pipeline = dummy  # type: ignore[assignment]
    assert agent.feature_enabled("mini_ad")
    agent.apply_features(["oil_car"])
    assert agent.feature_enabled("oil_car")
    assert not agent.feature_enabled("mini_ad")
    assert not agent.feature_enabled("non_sedan")
    assert dummy.skip_mini_ad is True
    agent.apply_features(["oil_car", "mini_ad", "bus_in_restricted"])
    assert dummy.skip_mini_ad is False
    assert agent.feature_enabled("non_sedan")
    agent.apply_features(None)
    assert dummy.skip_mini_ad is False


def test_emit_drops_disabled_feature() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        em = AlertEmitter(
            BackendClient("http://127.0.0.1:9", timeout=0.2, max_retries=1),
            Path(tmp),
            cooldown_sec=0.0,
            confirm_sec=0.0,
            voice=VoiceAnnouncer(enabled=False),
            feature_ok=lambda t: t != "mini_ad",
        )
        try:
            em.emit(1, "mini_ad", 0.9, None, {})
            assert (1, "mini_ad") not in em._in_flight
            accepted: list[str] = []
            em._worker.enqueue = lambda job: accepted.append(job.alert_type) or True  # type: ignore[method-assign]
            em.emit(1, "oil_car", 0.9, None, {})
            assert accepted == ["oil_car"]
            assert (1, "oil_car") in em._in_flight
        finally:
            em.shutdown(drain_sec=0.5)


def test_journal_sha_skips_identical_body() -> None:
    posted: list[dict] = []

    tel = EdgeTelemetry(
        BackendClient("http://127.0.0.1:9", timeout=0.2, max_retries=1),
        "box",
        lambda: {},
        heartbeat_sec=10,
        log_sec=60,
    )
    tel.backend.post_logs = lambda payload: posted.append(payload) or {"status": "ok"}  # type: ignore[method-assign]

    import chepai_edge.telemetry as telmod

    orig = telmod.collect_journal
    telmod.collect_journal = lambda _unit, _lines: "same journal\n"  # type: ignore[assignment]
    try:
        assert tel._upload_logs() is True
        assert len(posted) == 1
        assert tel._upload_logs() is True
        assert len(posted) == 1
    finally:
        telmod.collect_journal = orig


if __name__ == "__main__":
    test_parse_heartbeat_features()
    test_apply_features_sets_skip_mini_ad_without_rebuild()
    test_emit_drops_disabled_feature()
    test_journal_sha_skips_identical_body()
    print("ok")
