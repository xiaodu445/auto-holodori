@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
"%~dp0.vision\Scripts\python.exe" "%~dp0domains\hololive_dreams\models\jump_rope\game_jump_live.py" --live %*
if errorlevel 1 pause
