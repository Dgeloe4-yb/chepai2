"""Regression: RKNN contexts are persistent (no per-frame load_rknn/init_runtime)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent.parent
for p in (_AGENT_ROOT, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)


class _FakeRKNNLite:
    NPU_CORE_AUTO = 0
    NPU_CORE_0 = 1
    NPU_CORE_1 = 2
    NPU_CORE_2 = 4

    load_calls = 0
    init_calls = 0
    init_core_masks: list[int] = []

    def load_rknn(self, path: str) -> int:
        type(self).load_calls += 1
        return 0

    def init_runtime(self, core_mask: int = 0, **_: object) -> int:
        type(self).init_calls += 1
        type(self).init_core_masks.append(core_mask)
        return 0

    def inference(self, inputs, data_format="nhwc"):  # noqa: ANN001
        return [np.zeros((1, 6, 10), dtype=np.float32)]

    def release(self) -> int:
        return 0


def _install_fake_rknnlite() -> None:
    pkg = types.ModuleType("rknnlite")
    api = types.ModuleType("rknnlite.api")
    api.RKNNLite = _FakeRKNNLite
    pkg.api = api  # type: ignore[attr-defined]
    sys.modules["rknnlite"] = pkg
    sys.modules["rknnlite.api"] = api


def test_persistent_contexts_no_reload(tmp_path) -> None:  # noqa: ANN001
    _FakeRKNNLite.load_calls = 0
    _FakeRKNNLite.init_calls = 0
    _FakeRKNNLite.init_core_masks = []
    _install_fake_rknnlite()

    from chepai_edge.inference import RknnEngine, _SharedRknnRuntime

    _SharedRknnRuntime.reset()
    try:
        paths = []
        for name in ("vehicle.rknn", "plate.rknn", "gun.rknn"):
            p = tmp_path / name
            p.write_bytes(b"stub")
            paths.append(p)

        veh = RknnEngine(paths[0], {2: "car"}, imgsz=(640, 640))
        plate = RknnEngine(paths[1], {0: "plate_blue"}, imgsz=(320, 320))
        gun = RknnEngine(paths[2], {0: "gun"}, imgsz=(640, 640))

        frame640 = np.zeros((480, 640, 3), dtype=np.uint8)
        frame320 = np.zeros((240, 320, 3), dtype=np.uint8)

        for _ in range(5):
            veh.predict(frame640, 0.25)
            plate.predict(frame320, 0.25)
            gun.predict(frame640, 0.25)

        # 3 distinct models -> exactly one load + one init each, never per-frame.
        assert _FakeRKNNLite.load_calls == 3
        assert _FakeRKNNLite.init_calls == 3
        # Pinned to CORE_0/1/2 in registration order.
        assert _FakeRKNNLite.init_core_masks == [
            _FakeRKNNLite.NPU_CORE_0,
            _FakeRKNNLite.NPU_CORE_1,
            _FakeRKNNLite.NPU_CORE_2,
        ]
    finally:
        _SharedRknnRuntime.reset()
        sys.modules.pop("rknnlite.api", None)
        sys.modules.pop("rknnlite", None)
