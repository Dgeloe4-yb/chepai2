"""In-memory feature flags from cloud heartbeat (no pipeline rebuild)."""

from __future__ import annotations

FEATURE_KEYS = frozenset(
    {
        "oil_car",
        "bad_park",
        "mini_ad",
        "dual_slot",
        "car_in_bus_slot",
        "bus_in_restricted",
    }
)

ALERT_ALIASES = {
    "non_sedan": "bus_in_restricted",
}


def canonical_feature(alert_type: str) -> str:
    return ALERT_ALIASES.get(alert_type, alert_type)


def parse_heartbeat_features(raw: object) -> frozenset[str] | None:
    """None means 'field missing / old backend' — keep previous flags."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        return None
    out: set[str] = set()
    for item in raw:
        key = str(item).strip()
        if not key:
            continue
        canon = canonical_feature(key)
        if canon in FEATURE_KEYS:
            out.add(canon)
    return frozenset(out)
