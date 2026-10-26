@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
"%~dp0.conda\python.exe" -m modular_agent.realtime.fishing %*
pause
