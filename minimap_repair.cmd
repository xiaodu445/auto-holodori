@echo off
setlocal
cd /d "%~dp0"
call minimap_continue.cmd --repair-map %*
