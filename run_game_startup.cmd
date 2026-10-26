@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
set PYTHONIOENCODING=utf-8
"%~dp0.conda\python.exe" -m modular_agent local-start --domain hololive_dreams --live
pause
