@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
"%~dp0.conda\python.exe" -B -m modular_agent.realtime.motion_probe %*
if errorlevel 1 pause
