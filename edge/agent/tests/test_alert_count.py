"""Occupancy baseline gate: stable ≤3 voices, held +1 → another ≤3; held -1 lowers baseline."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.alert_count import AlertLevelGate, robust_count


def _drive(gate: AlertLevelGate, camera: int, counts: dict[str, int], t0: float, seconds: float, step: float = 0.5):
    last = {}
    t = t0
    end = t0 + seconds
    while t <= end + 1e-9:
        last = gate.tick(camera, counts, t)
        t += step
    return last


def test_robust_count_ignores_minority_jitter() -> None:
    assert robust_count([2, 2, 1, 2, 2, 2, 2, 2], 0.75) == 2
    assert robust_count([1, 1, 1, 2, 1, 1, 1, 1], 0.75) == 1
    assert robust_count([0, 0, 0, 0], 0.75) == 0


def test_stable_one_confirms_after_10s() -> None:
    gate = AlertLevelGate(confirm_sec=10.0, duty=0.75, voice_max=3)
    last = gate.tick(1, {"oil_car": 1}, 0.0)
    assert last["oil_car"].plus_one is False
    last = _drive(gate, 1, {"oil_car": 1}, 0.5, 9.0)
    assert last["oil_car"].plus_one is False
    last = gate.tick(1, {"oil_car": 1}, 10.0)
    assert last["oil_car"].plus_one is True
    assert last["oil_car"].baseline == 1
    assert last["oil_car"].plays_left == 3
    last = gate.tick(1, {"oil_car": 1}, 10.5)
    assert last["oil_car"].plus_one is False
    assert last["oil_car"].want_voice is True


def test_zero_to_two_is_one_episode() -> None:
    gate = AlertLevelGate(confirm_sec=10.0, voice_max=3)
    last = _drive(gate, 1, {"oil_car": 2}, 0.0, 10.0)
    assert last["oil_car"].plus_one is True
    assert last["oil_car"].baseline == 2
    last = gate.tick(1, {"oil_car": 2}, 10.5)
    assert last["oil_car"].plus_one is False


def test_plus_one_after_held_increase() -> None:
    gate = AlertLevelGate(confirm_sec=10.0, voice_max=3)
    first = _drive(gate, 1, {"oil_car": 1}, 0.0, 10.0)
    assert first["oil_car"].plus_one is True
    plus = 0
    t = 10.5
    last = {}
    while t <= 21.0:
        last = gate.tick(1, {"oil_car": 2}, t)
        if last["oil_car"].plus_one:
            plus += 1
        t += 0.5
    assert plus == 1
    assert last["oil_car"].baseline == 2
    assert last["oil_car"].plus_one is False


def test_minus_one_lowers_baseline_then_return_retriggers() -> None:
    gate = AlertLevelGate(confirm_sec=10.0, voice_max=3)
    _drive(gate, 1, {"oil_car": 2}, 0.0, 10.0)
    assert gate.tick(1, {"oil_car": 2}, 10.0)["oil_car"].baseline == 2
    plus = 0
    t = 10.5
    last = {}
    while t <= 21.0:
        last = gate.tick(1, {"oil_car": 1}, t)
        if last["oil_car"].plus_one:
            plus += 1
        t += 0.5
    assert plus == 0
    assert last["oil_car"].baseline == 1
    plus = 0
    while t <= 32.0:
        last = gate.tick(1, {"oil_car": 2}, t)
        if last["oil_car"].plus_one:
            plus += 1
        t += 0.5
    assert plus == 1
    assert last["oil_car"].baseline == 2


def test_jitter_down_does_not_lower_baseline() -> None:
    gate = AlertLevelGate(confirm_sec=10.0, duty=0.75, voice_max=3)
    _drive(gate, 1, {"oil_car": 2}, 0.0, 10.0)
    t = 10.5
    last = {}
    while t <= 22.0:
        n = 1 if int(round(t * 2)) % 6 == 0 else 2
        last = gate.tick(1, {"oil_car": n}, t)
        t += 0.5
    assert last["oil_car"].plus_one is False
    assert last["oil_car"].baseline == 2


def test_jitter_down_still_confirms_two() -> None:
    gate = AlertLevelGate(confirm_sec=10.0, duty=0.75, voice_max=3)
    t = 0.0
    last = {}
    while t <= 10.0:
        n = 1 if int(round(t * 2)) % 6 == 0 else 2
        last = gate.tick(1, {"oil_car": n}, t)
        t += 0.5
    assert last["oil_car"].plus_one is True
    assert last["oil_car"].baseline == 2


def test_all_clear_resets_for_new_car() -> None:
    gate = AlertLevelGate(confirm_sec=10.0, voice_max=3)
    _drive(gate, 1, {"oil_car": 1}, 0.0, 10.0)
    last_seen = {}
    t = 10.5
    while t <= 21.0:
        last = gate.tick(1, {"oil_car": 0}, t)
        if "oil_car" in last:
            last_seen = last
        t += 0.5
    assert last_seen["oil_car"].baseline == 0
    plus = 0
    last = {}
    while t <= 32.0:
        last = gate.tick(1, {"oil_car": 1}, t)
        if last["oil_car"].plus_one:
            plus += 1
        t += 0.5
    assert plus == 1
    assert last["oil_car"].baseline == 1


def test_types_do_not_affect_each_other() -> None:
    gate = AlertLevelGate(confirm_sec=10.0, voice_max=3)
    last = _drive(gate, 1, {"oil_car": 1, "mini_ad": 1}, 0.0, 10.0)
    assert last["oil_car"].plus_one is True
    assert last["mini_ad"].plus_one is True
    oil_plus = 0
    ad_plus = 0
    t = 10.5
    last = {}
    while t <= 21.0:
        last = gate.tick(1, {"oil_car": 1, "mini_ad": 2}, t)
        if last["oil_car"].plus_one:
            oil_plus += 1
        if last["mini_ad"].plus_one:
            ad_plus += 1
        t += 0.5
    assert oil_plus == 0
    assert ad_plus == 1
    assert last["oil_car"].baseline == 1
    assert last["mini_ad"].baseline == 2


def test_voice_budget_three() -> None:
    gate = AlertLevelGate(confirm_sec=0.0, voice_max=3)
    tick = gate.tick(1, {"oil_car": 1}, 0.0)
    assert tick["oil_car"].plus_one is True
    assert tick["oil_car"].plays_left == 3
    for left in (2, 1, 0):
        gate.mark_played(1, "oil_car")
        tick = gate.tick(1, {"oil_car": 1}, float(4 - left))
        assert tick["oil_car"].plus_one is False
        assert tick["oil_car"].plays_left == left
        assert tick["oil_car"].want_voice is (left > 0)


def test_slow_infer_3s_confirms_after_10s() -> None:
    """RK3588 ~3s/frame must still confirm; old window-edge test never reached 10s."""
    gate = AlertLevelGate(confirm_sec=10.0, duty=0.75, voice_max=3)
    last = {}
    plus = 0
    t = 0.0
    while t <= 12.0 + 1e-9:
        last = gate.tick(1, {"dual_slot": 1}, t)
        if last["dual_slot"].plus_one:
            plus += 1
        t += 3.0
    assert plus == 1
    assert last["dual_slot"].baseline == 1
    assert last["dual_slot"].plus_one is True


def test_slow_infer_8s_confirms_on_third_tick() -> None:
    gate = AlertLevelGate(confirm_sec=10.0, voice_max=3)
    assert gate.tick(1, {"dual_slot": 1}, 0.0)["dual_slot"].plus_one is False
    assert gate.tick(1, {"dual_slot": 1}, 8.0)["dual_slot"].plus_one is False
    third = gate.tick(1, {"dual_slot": 1}, 16.0)
    assert third["dual_slot"].plus_one is True
    assert third["dual_slot"].baseline == 1


def test_slow_infer_does_not_confirm_before_10s() -> None:
    gate = AlertLevelGate(confirm_sec=10.0, voice_max=3)
    last = _drive(gate, 1, {"dual_slot": 1}, 0.0, 9.0, step=3.0)
    assert last["dual_slot"].plus_one is False
    assert last["dual_slot"].baseline == 0


def test_cameras_isolated() -> None:
    gate = AlertLevelGate(confirm_sec=10.0, voice_max=3)
    _drive(gate, 1, {"oil_car": 1}, 0.0, 10.0)
    last = _drive(gate, 2, {"oil_car": 1}, 0.0, 9.0)
    assert last["oil_car"].plus_one is False
    last = gate.tick(2, {"oil_car": 1}, 10.0)
    assert last["oil_car"].plus_one is True


def test_process_frame_uses_gate() -> None:
    import tempfile

    from chepai_edge.alerts import AlertEmitter
    from chepai_edge.backend import BackendClient
    from chepai_edge.voice import VoiceAnnouncer

    spoken: list[str] = []

    class _Silent(VoiceAnnouncer):
        def __init__(self) -> None:  # type: ignore[no-untyped-def]
            VoiceAnnouncer.__init__(self, enabled=True, engine="log", cooldown_sec=30.0)

        def announce(self, alert_type, *, camera_id=0, text=None, ignore_cooldown=False):  # type: ignore[no-untyped-def]
            spoken.append(alert_type)
            return True

    with tempfile.TemporaryDirectory() as tmp:
        em = AlertEmitter(
            BackendClient("http://127.0.0.1:9", timeout=0.2, max_retries=1),
            Path(tmp),
            confirm_sec=10.0,
            voice=_Silent(),  # type: ignore[arg-type]
        )
        uploaded: list[str] = []
        em._worker.enqueue = lambda job: uploaded.append(job.alert_type) or True  # type: ignore[method-assign]
        cand = SimpleNamespace(alert_type="oil_car", score=0.9, raw={})
        try:
            for i in range(50):
                em.process_frame_alerts(1, [cand], None, now=i * 0.5)
            assert uploaded == ["oil_car"]
            assert spoken.count("oil_car") == 3
        finally:
            em.shutdown(drain_sec=0.2)


if __name__ == "__main__":
    test_robust_count_ignores_minority_jitter()
    test_stable_one_confirms_after_10s()
    test_zero_to_two_is_one_episode()
    test_plus_one_after_held_increase()
    test_minus_one_lowers_baseline_then_return_retriggers()
    test_jitter_down_still_confirms_two()
    test_jitter_down_does_not_lower_baseline()
    test_all_clear_resets_for_new_car()
    test_types_do_not_affect_each_other()
    test_voice_budget_three()
    test_slow_infer_3s_confirms_after_10s()
    test_slow_infer_8s_confirms_on_third_tick()
    test_slow_infer_does_not_confirm_before_10s()
    test_cameras_isolated()
    test_process_frame_uses_gate()
    print("ok")
