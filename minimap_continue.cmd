@echo off
setlocal
cd /d "%~dp0"
call minimap_scan.cmd --continue-manual %*
