@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
"%~dp0.conda\python.exe" "%~dp0domains\hololive_dreams\models\rhythm\rhythm_game.py" %*
pause
