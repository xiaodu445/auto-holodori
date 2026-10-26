@echo off
rem Observe proposed cadence plans without changing input deadlines.
call "%~dp0run_rhythm_tuning.cmd" --global-flow shadow --measure-clock shadow --mechanism-mode shadow %*
