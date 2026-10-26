@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
"%~dp0.vision\Scripts\python.exe" "%~dp0domains\hololive_dreams\models\kitchen\kitchen_play.py" %*
pause
