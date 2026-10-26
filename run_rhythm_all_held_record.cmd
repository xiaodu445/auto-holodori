@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
echo SIX KEYS HELD + recording ON. Turn OFF game AUTO. F12 stops.
"%~dp0.conda\python.exe" "%~dp0tools\rhythm_live_review.py" --live --input-mode all-held --release-scope target --record %*
if not errorlevel 1 call "%~dp0open_rhythm_review.cmd"
pause
