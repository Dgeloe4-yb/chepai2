@echo off
cd /d "%~dp0"
set CHEPAI_BACKEND_URL=http://38.207.179.218:8080
set CHEPAI_EDGE_BOX_ID=rk3588-01
set CHEPAI_INFERENCE=ultralytics
rem weights 目录 + 上级 poc 目录（yolov8n.pt 在 poc 根目录）
set CHEPAI_WEIGHTS_DIR=%~dp0..\poc\weights
set CHEPAI_SNAPSHOT_DIR=%~dp0snapshots
if not exist "%CHEPAI_SNAPSHOT_DIR%" mkdir "%CHEPAI_SNAPSHOT_DIR%"
echo Starting edge agent (dev mode, ultralytics)...
"%~dp0..\poc\.venv\Scripts\python.exe" -m chepai_edge.main --weights-dir "%CHEPAI_WEIGHTS_DIR%"
