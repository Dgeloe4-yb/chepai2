@echo off
setlocal
cd /d "%~dp0"
set WORK_ROOT=D:\chepai2_train\mini_ad
if not exist "%WORK_ROOT%" mkdir "%WORK_ROOT%"
if not exist "%WORK_ROOT%\downloads" mkdir "%WORK_ROOT%\downloads"
if not exist "%WORK_ROOT%\raw" mkdir "%WORK_ROOT%\raw"
if not exist "%WORK_ROOT%\logs" mkdir "%WORK_ROOT%\logs"

echo mini_ad dataset download (GitHub + optional Roboflow)
echo work_root=%WORK_ROOT%
echo.
echo Set ROBOFLOW_API_KEY for ~5k illegal banner dataset (free at app.roboflow.com)
echo.

".venv\Scripts\python.exe" training\mini_ad\download_datasets.py --work-root "%WORK_ROOT%" --all %*
exit /b %ERRORLEVEL%
