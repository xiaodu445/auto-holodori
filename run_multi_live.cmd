@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
"%~dp0.conda\python.exe" "%~dp0tools\run_multi_live.py" %*
exit /b %errorlevel%
