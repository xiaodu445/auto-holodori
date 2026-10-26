@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
set "align_python=%~dp0.conda\python.exe"
if not exist "%align_python%" set "align_python=%~dp0learning\jump_rope_yolo\.venv\Scripts\python.exe"
"%align_python%" "%~dp0tools\minimap_align.py" %*
set "align_exit=%errorlevel%"
if not "%align_exit%"=="0" pause
exit /b %align_exit%
