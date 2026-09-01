"""Unit tests for idempotency key generation."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from chepai_edge.upload_worker import make_idempotency_key


def test_idempotency_key_same_bucket() -> None:
    k1 = make_idempotency_key(1, "gun_misplace", 30.0)
    k2 = make_idempotency_key(1, "gun_misplace", 30.0)
    assert k1 == k2
    assert k1.startswith("1:gun_misplace:")


def test_idempotency_key_diff_camera() -> None:
    k1 = make_idempotency_key(1, "oil_car", 30.0)
    k2 = make_idempotency_key(2, "oil_car", 30.0)
    assert k1 != k2
