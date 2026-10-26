@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0gui"
"%~dp0.conda\python.exe" "%~dp0gui\hololive_dreams_gui.py"
if errorlevel 1 pause
