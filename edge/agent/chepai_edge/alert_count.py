"""Per-camera, per-type occupancy gate for voice / upload.

A lane tracks a confirmed occupancy baseline (not a one-frame count):

- Count stable at N for ``confirm_sec`` (clock from the lane's first tick,
  so a 3–8s infer interval still qualifies) → one episode,
  at most ``voice_max`` voice plays. Baseline becomes N.
  Duty-cycle is measured on samples inside the last ``confirm_sec``.
- Count held above baseline for ``confirm_sec`` → another episode.
- Count held below baseline for ``confirm_sec`` → baseline follows it down.
  No voice / upload on a decrease. A later held +1 is a new episode.
- Occasional dip or spike inside the duty window is jitter, not a change.

Bounded memory: one lane per (camera, type), sample deque time-capped.
No extra threads; callers tick from the existing camera loop.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

_WINDOW_SLACK_SEC = 2.0


def robust_count(values: list[int], duty: float) -> int:
    """Highest C that is present in at least ``duty`` of samples (count >= C)."""
    if not values:
        return 0
    hi = max(values)
    n = len(values)
    for c in range(hi, 0, -1):
        if sum(1 for v in values if v >= c) / n >= duty:
            return c
    return 0


@dataclass
class LaneTick:
    plus_one: bool
    want_voice: bool
    baseline: int
    robust: int
    plays_left: int


@dataclass
class _Lane:
    samples: deque[tuple[float, int]] = field(default_factory=deque)
    baseline: int = 0
    plays_left: int = 0
    # First tick on this lane. Spanned uses this, not "oldest sample inside
    # the last confirm_sec", so a 3–8s infer interval can still fill 10s.
    origin: float | None = None


class AlertLevelGate:
    def __init__(
        self,
        *,
        confirm_sec: float = 10.0,
        clear_sec: float | None = None,
        duty: float = 0.75,
        voice_max: int = 3,
    ) -> None:
        self.confirm_sec = max(0.0, float(confirm_sec))
        self.clear_sec = self.confirm_sec if clear_sec is None else max(0.0, float(clear_sec))
        self.duty = min(1.0, max(0.5, float(duty)))
        self.voice_max = max(1, int(voice_max))
        self._lanes: dict[tuple[int, str], _Lane] = {}

    def prune_cameras(self, active_camera_ids: set[int]) -> None:
        self._lanes = {k: v for k, v in self._lanes.items() if k[0] in active_camera_ids}

    def mark_played(self, camera_id: int, alert_type: str) -> None:
        lane = self._lanes.get((camera_id, alert_type))
        if lane is not None and lane.plays_left > 0:
            lane.plays_left -= 1

    def tick(
        self,
        camera_id: int,
        counts: dict[str, int],
        now: float,
    ) -> dict[str, LaneTick]:
        types = set(counts)
        types.update(t for (cid, t) in self._lanes if cid == camera_id)
        out: dict[str, LaneTick] = {}
        idle: list[tuple[int, str]] = []
        for alert_type in types:
            raw = int(counts.get(alert_type, 0))
            if raw < 0:
                raw = 0
            key = (camera_id, alert_type)
            lane = self._lanes.get(key)
            if lane is None:
                if raw == 0:
                    continue
                lane = _Lane()
                self._lanes[key] = lane
            out[alert_type] = self._tick_lane(lane, raw, now)
            if lane.baseline == 0 and lane.plays_left == 0 and raw == 0:
                idle.append(key)
        for key in idle:
            self._lanes.pop(key, None)
        return out

    def _tick_lane(self, lane: _Lane, raw: int, now: float) -> LaneTick:
        lane.samples.append((now, raw))
        horizon = max(self.confirm_sec, self.clear_sec) + _WINDOW_SLACK_SEC
        cutoff = now - horizon
        while lane.samples and lane.samples[0][0] < cutoff:
            lane.samples.popleft()
        # Hard cap so a high analyze_fps cannot grow the deque without bound.
        cap = max(64, int(horizon * 16) + 8)
        while len(lane.samples) > cap:
            lane.samples.popleft()

        if lane.origin is None:
            lane.origin = now

        plus_one = False
        if self.confirm_sec <= 0:
            robust = raw
            if robust > lane.baseline:
                lane.baseline = robust
                lane.plays_left = self.voice_max
                plus_one = True
            elif robust < lane.baseline:
                lane.baseline = robust
                lane.plays_left = 0
            return LaneTick(plus_one, lane.plays_left > 0, lane.baseline, robust, lane.plays_left)

        window = [(t, c) for t, c in lane.samples if t >= now - self.confirm_sec]
        values = [c for _, c in window]
        spanned = now - lane.origin >= self.confirm_sec
        robust = robust_count(values, self.duty) if spanned and values else lane.baseline

        if spanned and robust > lane.baseline:
            lane.baseline = robust
            lane.plays_left = self.voice_max
            plus_one = True
        elif spanned and robust < lane.baseline:
            # Real drop held for confirm_sec. Jitter never gets here (duty still high).
            lane.baseline = robust
            lane.plays_left = 0

        return LaneTick(plus_one, lane.plays_left > 0, lane.baseline, robust, lane.plays_left)
