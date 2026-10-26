@echo off
rem Mechanism input DISABLED pending false-positive / missed-trigger investigation.
echo Mechanism OFF: no cadence reordering or speculative extra presses.
call "%~dp0run_rhythm_tuning.cmd" --global-flow shadow --measure-clock shadow %* --mechanism-mode off
