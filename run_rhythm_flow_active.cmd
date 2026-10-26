@echo off
rem EXPERIMENTAL: shared scroll speed changes future input deadlines.
rem Uses the existing tuning values. Keep release scope set to target.
call "%~dp0run_rhythm_tuning.cmd" --global-flow active %*
