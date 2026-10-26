@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
set "mapper_python=%~dp0.conda\python.exe"
if not exist "%mapper_python%" set "mapper_python=%~dp0learning\jump_rope_yolo\.venv\Scripts\python.exe"
"%mapper_python%" -m modular_agent.realtime.minimap_scan %*
set "mapper_exit=%errorlevel%"
pause
exit /b %mapper_exit%
