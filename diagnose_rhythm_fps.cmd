@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
"%~dp0.conda\python.exe" "%~dp0tools\diagnose_rhythm_fps.py"
pause
