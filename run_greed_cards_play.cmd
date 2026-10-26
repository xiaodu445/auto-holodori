@echo off
cd /d "%~dp0"
set PYTHONPATH=src
.conda\python.exe -m modular_agent local-play --domain hololive_dreams --live %*
pause
