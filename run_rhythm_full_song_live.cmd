@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
echo Live play + full-song recording. Turn OFF in-game AUTO. F12 stops.
echo Default maximum 10 minutes. Keep the game foreground. Allow 10GB disk space.
"%~dp0.conda\python.exe" "%~dp0tools\rhythm_live_review.py" --live %*
if not errorlevel 1 call "%~dp0open_rhythm_review.cmd"
pause
