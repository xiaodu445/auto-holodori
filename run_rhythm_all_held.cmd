@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
echo Experimental SIX KEYS HELD. Recording OFF by default. Turn OFF game AUTO.
echo Do not run another input bot. F12 / loss of focus stops and releases keys.
"%~dp0.conda\python.exe" "%~dp0tools\rhythm_live_review.py" --live --input-mode all-held --release-scope target --no-record %*
pause
