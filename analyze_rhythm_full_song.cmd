@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
"%~dp0.conda\python.exe" "%~dp0tools\rhythm_review.py" --full-song %*
if not errorlevel 1 call "%~dp0open_rhythm_review.cmd"
pause
