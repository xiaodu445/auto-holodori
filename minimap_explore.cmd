@echo off
rem Automatic walking is explicit in this separate launcher.
call "%~dp0minimap_scan.cmd" --auto-walk --auto-calibrate %*
