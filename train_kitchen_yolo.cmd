@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
set "record_python=%~dp0learning\jump_rope_yolo\.venv\Scripts\python.exe"
if not exist "%record_python%" (
  echo Missing YOLO training environment.
  pause
  exit /b 1
)
"%record_python%" learning\kitchen_yolo\train.py %*
set "record_exit=%errorlevel%"
pause
exit /b %record_exit%
