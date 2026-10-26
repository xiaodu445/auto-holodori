@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
"%~dp0.conda\pythonw.exe" gui\kitchen_control.py
