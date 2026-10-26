@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\rhythm\latest-review.txt" (
 echo No review yet. Run record_rhythm_review.cmd or drag video onto analyze_rhythm_video.cmd.
 pause
 exit /b 1
)
set /p rhythm_review_page=<"runtime\rhythm\latest-review.txt"
start "" "%rhythm_review_page%"
