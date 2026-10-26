@echo off
cd /d "%~dp0..\.."
set "PYTHONIOENCODING=utf-8"
"learning\jump_rope_yolo\.venv\Scripts\python.exe" "learning\jump_rope_yolo\upgrade.py" %*
pause
