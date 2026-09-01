@echo off
setlocal
cd /d "%~dp0"

set WORK_ROOT=D:\chepai2_train
if not exist "%WORK_ROOT%\datasets\plate_color\dataset.yaml" (
  echo [error] missing dataset: %WORK_ROOT%\datasets\plate_color
  exit /b 1
)

if not exist "%WORK_ROOT%\logs" mkdir "%WORK_ROOT%\logs"
if not exist "%WORK_ROOT%\tmp" mkdir "%WORK_ROOT%\tmp"

set LOG=%WORK_ROOT%\logs\train_plate_color.log

echo plate_color training started > "%LOG%"
echo work_root=%WORK_ROOT%>> "%LOG%"

".venv\Scripts\python.exe" training\plate_color\train_plate_color.py --work-root "%WORK_ROOT%" --epochs 80 --batch 32 --workers 4 --cache disk --device 0 --skip-predict >> "%LOG%" 2>&1

echo exit_code=%ERRORLEVEL%>> "%LOG%"
exit /b %ERRORLEVEL%
