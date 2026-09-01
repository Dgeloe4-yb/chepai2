#!/usr/bin/env python3
"""Convert ONNX to RKNN on RK3588 (run on board)."""
import sys
from pathlib import Path

def convert(onnx_path: str, out_path: str, imgsz: int = 640) -> None:
    from rknn.api import RKNN

    onnx = Path(onnx_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rknn = RKNN(verbose=True)
    rknn.config(mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]], target_platform="rk3588")
    rknn.load_onnx(model=str(onnx))
    rknn.build(do_quantization=False)
    tmp = out.with_suffix(".tmp.rknn")
    rknn.export_rknn(str(tmp))
    rknn.release()
    tmp.replace(out)
    print("Wrote", out)


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 640)
