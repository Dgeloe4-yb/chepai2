@echo off
setlocal
cd /d "%~dp0"
set WORK_ROOT=D:\chepai2_train\mini_ad
set LOG=%WORK_ROOT%\logs\train_mini_ad.log

if not exist "%WORK_ROOT%\datasets\mini_ad\dataset.yaml" (
  echo [error] missing dataset. Run download_mini_ad.bat and prepare_mini_ad.bat first.
  exit /b 1
)

echo mini_ad training started > "%LOG%"
echo work_root=%WORK_ROOT%>> "%LOG%"

".venv\Scripts\python.exe" training\mini_ad\train_mini_ad.py --work-root "%WORK_ROOT%" --epochs 120 --batch 24 --workers 4 --cache disk --device 0 >> "%LOG%" 2>&1

echo exit_code=%ERRORLEVEL%>> "%LOG%"
type "%LOG%"
exit /b %ERRORLEVEL%
