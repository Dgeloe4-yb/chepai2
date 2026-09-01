"""Inference backends: Ultralytics (dev/PC) and RKNN (RK3588)."""

from __future__ import annotations

import logging
import math
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from chepai_edge.yolo_rknn import decode_yolov8_output, letterbox, scale_boxes_back

logger = logging.getLogger(__name__)

RKNN_IMGSZ = (640, 640)
_PLATE_IMGSZ = (320, 320)

# Warn if a single NPU inference call blocks longer than this (stuck-core signal).
_SLOW_INFER_SEC = 2.0


@dataclass
class Detection:
    xyxy: tuple[float, float, float, float]
    confidence: float
    class_id: int
    class_name: str = ""


class DetectorEngine(ABC):
    @abstractmethod
    def predict(self, bgr: np.ndarray, conf: float) -> list[Detection]:
        raise NotImplementedError


class UltralyticsEngine(DetectorEngine):
    def __init__(self, weights: Path | str, class_names: dict[int, str] | None = None) -> None:
        from ultralytics import YOLO

        path = Path(weights)
        if not path.is_file():
            raise FileNotFoundError(f"weights not found: {path}")
        self._lock = threading.Lock()
        self.model = YOLO(str(path))
        self.class_names = class_names or {}

    def predict(self, bgr: np.ndarray, conf: float) -> list[Detection]:
        with self._lock:
            results = self.model.predict(bgr, conf=conf, verbose=False)[0]
        boxes = results.boxes
        if boxes is None:
            return []
        out: list[Detection] = []
        names = results.names or {}
        for b in boxes:
            cls_id = int(b.cls[0])
            out.append(
                Detection(
                    xyxy=tuple(float(x) for x in b.xyxy[0].tolist()),
                    confidence=float(b.conf[0]),
                    class_id=cls_id,
                    class_name=self.class_names.get(cls_id) or names.get(cls_id, str(cls_id)),
                )
            )
        return out


class _RknnContext:
    """One persistent RKNNLite context for a single .rknn file (loaded + init once)."""

    def __init__(self, rknn_cls: type, path: Path, core_mask: int, core_label: str) -> None:
        self.path = path
        self.core_label = core_label
        self._lock = threading.Lock()
        self._rknn = rknn_cls()

        ret = self._rknn.load_rknn(str(path))
        if ret != 0:
            raise RuntimeError(f"load_rknn failed code={ret} path={path}")

        ret = self._rknn.init_runtime(core_mask=core_mask)
        if ret != 0 and core_mask != rknn_cls.NPU_CORE_AUTO:
            logger.warning(
                "init_runtime core_mask=%s failed code=%s for %s, retrying NPU_CORE_AUTO",
                core_label,
                ret,
                path.name,
            )
            self._rknn.release()
            self._rknn = rknn_cls()
            ret = self._rknn.load_rknn(str(path))
            if ret != 0:
                raise RuntimeError(f"load_rknn failed code={ret} path={path}")
            ret = self._rknn.init_runtime(core_mask=rknn_cls.NPU_CORE_AUTO)
            self.core_label = "AUTO"
        if ret != 0:
            raise RuntimeError(f"RKNN init_runtime failed code={ret} path={path}")
        logger.info("rknn context ready model=%s core=%s", path.name, self.core_label)

    def inference(self, inp: np.ndarray) -> list[np.ndarray]:
        with self._lock:
            t0 = time.monotonic()
            outputs = self._rknn.inference(inputs=[inp], data_format="nhwc")
            elapsed = time.monotonic() - t0
        if elapsed > _SLOW_INFER_SEC:
            logger.warning(
                "slow NPU inference model=%s core=%s took=%.2fs",
                self.path.name,
                self.core_label,
                elapsed,
            )
        return outputs

    def release(self) -> None:
        with self._lock:
            try:
                self._rknn.release()
            except Exception as exc:  # noqa: BLE001
                logger.warning("rknn release failed model=%s: %s", self.path.name, exc)


class _SharedRknnRuntime:
    """Registry of persistent per-model RKNNLite contexts (no per-frame reload).

    Each distinct .rknn gets its own context, init'd once and pinned to a
    dedicated NPU core (CORE_0/1/2 in registration order, AUTO beyond 3 models).
    """

    _instance: _SharedRknnRuntime | None = None
    _inst_lock = threading.Lock()

    def __init__(self) -> None:
        from rknnlite.api import RKNNLite

        self._RKNNLite = RKNNLite
        self._reg_lock = threading.Lock()
        self._contexts: dict[Path, _RknnContext] = {}
        self._core_masks = [
            (RKNNLite.NPU_CORE_0, "CORE_0"),
            (RKNNLite.NPU_CORE_1, "CORE_1"),
            (RKNNLite.NPU_CORE_2, "CORE_2"),
        ]

    @classmethod
    def get(cls) -> _SharedRknnRuntime:
        with cls._inst_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Release all contexts and drop the singleton (used by tests/shutdown)."""
        with cls._inst_lock:
            if cls._instance is not None:
                for ctx in cls._instance._contexts.values():
                    ctx.release()
                cls._instance._contexts.clear()
            cls._instance = None

    def _context_for(self, path: Path) -> _RknnContext:
        ctx = self._contexts.get(path)
        if ctx is not None:
            return ctx
        with self._reg_lock:
            ctx = self._contexts.get(path)
            if ctx is not None:
                return ctx
            idx = len(self._contexts)
            if idx < len(self._core_masks):
                core_mask, core_label = self._core_masks[idx]
            else:
                core_mask, core_label = self._RKNNLite.NPU_CORE_AUTO, "AUTO"
            ctx = _RknnContext(self._RKNNLite, path, core_mask, core_label)
            self._contexts[path] = ctx
            return ctx

    def predict(
        self,
        path: Path,
        bgr: np.ndarray,
        conf: float,
        class_names: dict[int, str],
        imgsz: tuple[int, int],
    ) -> list[Detection]:
        h, w = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        lb, r, pad = letterbox(rgb, imgsz)
        inp = np.expand_dims(lb, axis=0)
        ctx = self._context_for(path)
        outputs = ctx.inference(inp)
        if not outputs:
            return []
        xyxy, scores, cls_ids = decode_yolov8_output(outputs, conf)
        if len(xyxy) == 0:
            return []
        xyxy = scale_boxes_back(xyxy, r, pad, (h, w))
        out: list[Detection] = []
        for i in range(len(xyxy)):
            box = tuple(float(x) for x in xyxy[i].tolist())
            if not all(math.isfinite(v) for v in box):
                continue
            cid = int(cls_ids[i])
            out.append(
                Detection(
                    xyxy=box,
                    confidence=float(scores[i]),
                    class_id=cid,
                    class_name=class_names.get(cid, str(cid)),
                )
            )
        return out


class RknnEngine(DetectorEngine):
    """RK3588 NPU engine; each model is a persistent core-pinned context."""

    def __init__(
        self,
        rknn_path: Path | str,
        class_names: dict[int, str] | None = None,
        imgsz: tuple[int, int] = RKNN_IMGSZ,
    ) -> None:
        path = Path(rknn_path)
        if not path.is_file():
            raise FileNotFoundError(f"rknn weights not found: {rknn_path}")
        self.rknn_path = path.resolve()
        self.class_names = class_names or {}
        self.imgsz = imgsz
        _SharedRknnRuntime.get()

    def predict(self, bgr: np.ndarray, conf: float) -> list[Detection]:
        return _SharedRknnRuntime.get().predict(
            self.rknn_path, bgr, conf, self.class_names, self.imgsz
        )


COCO_VEHICLE = {2: "car", 5: "bus", 7: "truck"}
PLATE_CLASSES = {0: "plate_blue", 1: "plate_green"}


def _resolve_rknn_path(weights: Path | str) -> Path:
    p = Path(weights)
    if p.suffix == ".rknn" and p.is_file():
        return p.resolve()
    if p.suffix == ".pt":
        rknn = p.with_suffix(".rknn")
        if rknn.is_file():
            return rknn.resolve()
    if p.is_file():
        return p.resolve()
    parent = p.parent if p.parent.exists() else Path(".")
    stem = p.stem.replace(".pt", "")
    for name in (f"{stem}.rknn", f"{stem}-rk3588.rknn"):
        cand = parent / name
        if cand.is_file():
            return cand.resolve()
    return Path(weights)


def create_engine(
    backend: str,
    weights: Path | str,
    class_names: dict[int, str] | None = None,
) -> DetectorEngine:
    if backend == "rknn":
        path = _resolve_rknn_path(weights)
        if not path.is_file():
            raise FileNotFoundError(f"RKNN model not found for {weights} -> {path}")
        imgsz = _PLATE_IMGSZ if "plate" in path.stem else RKNN_IMGSZ
        return RknnEngine(path, class_names, imgsz=imgsz)
    return UltralyticsEngine(weights, class_names)
