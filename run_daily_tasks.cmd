@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
if not exist "%~dp0.conda\python.exe" (
  echo [ERROR] Python runtime missing: "%~dp0.conda\python.exe"
  exit /b 1
)
"%~dp0.conda\python.exe" -m modular_agent local-daily --project-root "%~dp0." --domain hololive_dreams --live %*
exit /b %errorlevel%
