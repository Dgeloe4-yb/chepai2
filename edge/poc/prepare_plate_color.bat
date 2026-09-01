@echo off
cd /d "%~dp0"
echo [1/3] 下载 CCPD 数据集（绿牌 + 蓝牌，无需手标）
".venv\Scripts\python.exe" training\plate_color\download_datasets.py
echo.
echo [2/3] 转换 YOLO 数据集（蓝牌/绿牌，无需手标）
".venv\Scripts\python.exe" training\plate_color\prepare_ccpd.py
echo.
echo [3/3] 如需训练，运行 train_plate_color.bat
