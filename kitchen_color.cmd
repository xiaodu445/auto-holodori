@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
set "record_python=%~dp0.conda\python.exe"
if not exist "%record_python%" set "record_python=%~dp0learning\jump_rope_yolo\.venv\Scripts\python.exe"
"%record_python%" tools\kitchen_color_review.py %*
set "record_exit=%errorlevel%"
pause
exit /b %record_exit%
