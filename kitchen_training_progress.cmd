@echo off
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
"%~dp0.conda\python.exe" "%~dp0learning\kitchen_yolo\progress.py"
