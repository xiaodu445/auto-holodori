@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
"%~dp0.conda\python.exe" tools\kitchen_point_label.py --recording "runtime/kitchen/recordings/review-confusions-20261024" --labels-dir "runtime/kitchen/manual-labeling/review-confusions-20261024" --classes "data/kitchen/manual-classes.json" --box-mode
pause
