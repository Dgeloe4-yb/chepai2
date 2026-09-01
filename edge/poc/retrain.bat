@echo off
cd /d "%~dp0"
echo 用手动标注数据重新训练 gun 模型 (batch=24, workers=4, cache=disk)
echo 预计 1-2 小时，训练完成后 gun.pt 会自动更新
".venv\Scripts\python.exe" training\train_gun.py --name gun_manual --base-weights weights\gun.pt --epochs 120 --batch 24 --workers 4 --cache disk --device 0
