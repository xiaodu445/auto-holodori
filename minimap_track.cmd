@echo off
setlocal
cd /d "%~dp0"
call patrol.cmd preview --fast-track --fps 10 --start-delay 8 %*
