@echo off
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src"
"%~dp0.conda\python.exe" -m modular_agent vision-import --project-root "%~dp0." --domain hololive_dreams %*
echo.
pause
