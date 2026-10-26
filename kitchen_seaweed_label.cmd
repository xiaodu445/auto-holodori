@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
"%~dp0.conda\python.exe" tools\kitchen_point_label.py --recording "runtime/kitchen/recordings/seaweed-review-20261024" --labels-dir "runtime/kitchen/manual-labeling/seaweed-review-20261024" --classes "data/kitchen/manual-classes.json" --box-mode
pause
