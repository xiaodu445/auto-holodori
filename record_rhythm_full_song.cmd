@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
echo Full-song recording: switch to game, play song, press F12 after the result screen.
echo Maximum 10 minutes by default. Recording does not press game keys. Allow 10GB free disk.
"%~dp0.conda\python.exe" "%~dp0tools\rhythm_review.py" --record --full-song %*
if not errorlevel 1 call "%~dp0open_rhythm_review.cmd"
pause
