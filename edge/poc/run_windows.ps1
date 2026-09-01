# 在 Windows 上跑通边缘 PoC（需已安装 Python 3.10+，建议 3.11）
# 若提示禁止脚本：以管理员或当前用户执行一次
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 python，请先安装 Python 3.10+ 并勾选 Add to PATH" -ForegroundColor Red
    exit 1
}

Write-Host "创建虚拟环境 .venv ..."
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& .\.venv\Scripts\Activate.ps1

Write-Host "安装依赖（首次会下载 PyTorch / ultralytics，稍慢）..."
python -m pip install --upgrade pip
pip install -r requirements.txt

Write-Host ""
Write-Host "首次运行 HyperLPR3 会下载模型到 $env:USERPROFILE\.hyperlpr3（需联网）。" -ForegroundColor Cyan
Write-Host "若报错 WinError 32：关闭其它 Python 进程，删掉该目录下未完成 .zip 后重试。" -ForegroundColor Cyan
Write-Host ""

# 默认：本机摄像头 0 + 示例 ROI；无 LPR：$env:NO_LPR=1; .\run_windows.ps1
# 充电枪：准备自训单类 YOLO 权重后：$env:GUN_WEIGHTS = "D:\models\gun.pt"; .\run_windows.ps1

$src = if ($env:SOURCE) { $env:SOURCE } else { "0" }
$extra = @()
if ($env:NO_LPR -eq "1") { $extra += "--no-lpr" }
if ($env:LPR_HIGH -eq "1") { $extra += "--lpr-high" }
if ($env:HSV_FALLBACK -eq "0") { $extra += "--no-hsv-fallback" }
if ($env:GUN_WEIGHTS) { $extra += "--gun-weights", $env:GUN_WEIGHTS }

python poc_pipeline.py --source $src --rois sample_rois.json @extra
