@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
"%~dp0learning\jump_rope_yolo\.venv\Scripts\python.exe" -m modular_agent.realtime.kitchen_play %*
pause
