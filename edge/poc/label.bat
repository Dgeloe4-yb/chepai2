@echo off
cd /d "%~dp0"
echo 充电枪手动标注工具
echo.
echo 用法示例:
echo   label.bat                     标注 train 集
echo   label.bat val                 标注 val 集
echo   label.bat unlabeled           只标未标注的图
echo.
set SPLIT=train
set FILTER=all
if /I "%~1"=="val" set SPLIT=val
if /I "%~1"=="both" set SPLIT=both
if /I "%~1"=="unlabeled" set FILTER=unlabeled
".venv\Scripts\python.exe" training\label_gun.py --split %SPLIT% --filter %FILTER%
