@echo off
rem Song-local pulse and bar candidates only; stable input stays unchanged.
call "%~dp0run_rhythm_tuning.cmd" --global-flow shadow --measure-clock shadow %*
