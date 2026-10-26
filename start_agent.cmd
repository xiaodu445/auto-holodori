@echo off
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src"
"%~dp0.conda\python.exe" -m modular_agent chat --project-root "%~dp0." --domain hololive_dreams --live --log-window %*
