@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
set "patrol_python=%~dp0.conda\python.exe"
if not exist "%patrol_python%" set "patrol_python=%~dp0learning\jump_rope_yolo\.venv\Scripts\python.exe"
"%patrol_python%" -m modular_agent.realtime.patrol %*
set "patrol_exit=%errorlevel%"
pause
exit /b %patrol_exit%
