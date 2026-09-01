@echo off
setlocal
cd /d "%~dp0"
set WORK_ROOT=D:\chepai2_train\mini_ad

".venv\Scripts\python.exe" training\mini_ad\prepare_dataset.py --work-root "%WORK_ROOT%" %*
exit /b %ERRORLEVEL%
