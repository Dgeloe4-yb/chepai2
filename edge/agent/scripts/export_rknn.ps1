# Export ONNX on PC, convert to RKNN on cloud server (x86 + rknn-toolkit2), download to edge/poc/weights/rknn.
# Requires deploy.env.local (DEPLOY_* for server). Upload .rknn to board: python scripts/sync_edge_board.py (weights separately).
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$Poc = Join-Path $Root "edge\poc"
$Out = Join-Path $Poc "weights\rknn"
$Py = Join-Path $Poc ".venv\Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

$models = @(
    @{ Pt = "yolov8n.pt"; Dir = $Poc; Imgsz = 640 },
    @{ Pt = "weights\mini_ad.pt"; Dir = $Poc; Imgsz = 640 },
    @{ Pt = "weights\plate_color.pt"; Dir = $Poc; Imgsz = 320 }
)

foreach ($m in $models) {
    $ptPath = Join-Path $m.Dir $m.Pt
    $stem = [IO.Path]::GetFileNameWithoutExtension($m.Pt)
    Write-Host "ONNX export $stem"
    & $Py -c "from ultralytics import YOLO; from pathlib import Path; m=YOLO(r'$ptPath'); m.export(format='onnx',opset=17,simplify=True,imgsz=$($m.Imgsz))"
    $onnx = Join-Path $m.Dir "$stem.onnx"
    if ($m.Pt -like "weights\*") { $onnx = Join-Path $m.Dir "weights\$stem.onnx" }
    python (Join-Path $Root "scripts\ssh_run.py") server "true" | Out-Null
    python -c "
import scripts.ssh_run as s
from pathlib import Path
c=s.connect('server')
sf=c.open_sftp()
sf.put(r'$onnx', f'/tmp/{stem}.onnx')
sf.close(); c.close()
"
    python (Join-Path $Root "scripts\ssh_run.py") server "python3 /tmp/onnx2rknn_board.py /tmp/$stem.onnx /tmp/$stem.rknn $($m.Imgsz)"
    python -c "
import scripts.ssh_run as s
from pathlib import Path
Path(r'$Out').mkdir(parents=True, exist_ok=True)
c=s.connect('server')
c.open_sftp().get(f'/tmp/$stem.rknn', r'$Out\$stem.rknn')
c.close()
"
}

Write-Host "RKNN files in $Out"
