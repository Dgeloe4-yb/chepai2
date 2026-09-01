@echo off
cd /d "%~dp0"
echo Chepai 三模型图片调试（车辆 + 车牌色 + 枪）
echo.
if "%~1"=="" (
  ".venv\Scripts\python.exe" debug_image.py
) else (
  ".venv\Scripts\python.exe" debug_image.py %*
)
