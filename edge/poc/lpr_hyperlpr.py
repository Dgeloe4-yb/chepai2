"""
HyperLPR3 封装：返回结构化结果。若未安装或初始化失败，由调用方回退到 HSV 启发式。
plate_type 数值见 hyperlpr3.common.typedef（BLUE=0, GREEN=3, ...）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# 与 hyperlpr3.common.typedef 同步
PLATE_TYPE_NAMES = {
    -1: "unknown",
    0: "blue",
    1: "yellow_single",
    2: "white_single",
    3: "green_ev",
    4: "black_hk_macao",
    5: "hk_single",
    6: "hk_double",
    7: "macao_single",
    8: "macao_double",
    9: "yellow_double",
}


def plate_type_label(t: int) -> str:
    return PLATE_TYPE_NAMES.get(int(t), f"type_{t}")


def create_catcher(detect_high: bool):
    """首次会下载 onnx 模型到用户目录 ~/.hyperlpr3（需联网）。"""
    import hyperlpr3 as lpr3  # noqa: WPS433 — 运行时依赖，允许 Win/Jetson
    from hyperlpr3 import DETECT_LEVEL_HIGH, DETECT_LEVEL_LOW

    level = DETECT_LEVEL_HIGH if detect_high else DETECT_LEVEL_LOW
    return lpr3.LicensePlateCatcher(detect_level=level)


def run_lpr_on_bgr(bgr, catcher) -> List[Dict[str, Any]]:
    """
    catcher(image) -> list of [plate_code, rec_confidence, plate_type, det_bound_box]
    """
    if catcher is None or bgr is None or bgr.size == 0:
        return []
    raw = catcher(bgr)
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not item or len(item) < 4:
            continue
        code, conf, ptype, box = item[0], float(item[1]), int(item[2]), item[3]
        out.append(
            {
                "plate_code": str(code),
                "confidence": conf,
                "plate_type": ptype,
                "plate_type_name": plate_type_label(ptype),
                "det_box": box,
            }
        )
    return out


def is_probable_ev_plate(ptype: int) -> bool:
    return int(ptype) == 3  # GREEN


def is_probable_fuel_plate(ptype: int) -> bool:
    """业务上可再把白牌警牌等并入需人工复核集合。"""
    return int(ptype) in {0, 1, 9}  # blue, yellow_single, yellow_double
