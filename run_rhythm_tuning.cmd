@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"

rem Edit values below, save, then restart this file.
rem Target processing FPS: 30..240. Actual capture FPS can be lower.
set "RHYTHM_FPS=120"
rem Recognition width: 480..1600. Lower values use less CPU.
set "RHYTHM_WIDTH=960"
rem Beat-grid snap window: 0..25 ms. 0 disables correction. Default 3.
set "RHYTHM_GRID_SNAP=20"
rem Key DOWN offset: -100..100 ms. Positive = earlier.
set "RHYTHM_OFFSET=75"
rem Key UP lead before compensated DOWN target: 0..300 ms.
set "RHYTHM_RELEASE_LEAD=5"
rem Dense sequence threshold: 0..300 ms. 0 = disable.
set "RHYTHM_DENSE_GAP=10"
rem Wait after protected head before restoring held keys: 25..500 ms.
set "RHYTHM_DENSE_RECOVERY=125"
rem Dense-mode press duration: 1..50 ms.
set "RHYTHM_DENSE_TAP=12"
rem Minimum DOWN duration before next release: 1..50 ms.
set "RHYTHM_MIN_DOWN=12"
rem Minimum UP duration before next press: 1..50 ms.
set "RHYTHM_RELEASE_GAP=8"
rem Look ahead for keys that avoid later notes: 0..300 ms; 0 = centre key.
set "RHYTHM_KEY_LOOKAHEAD=0"
rem Keep small notes on their own column before coloured slides: 0..500 ms.
set "RHYTHM_SLIDE_GUARD=160"
rem Session limit including pauses: 0 = unlimited; or 1..1800 seconds.
set "RHYTHM_DURATION=0"
rem target = release target key; all = experimental global release.
set "RHYTHM_RELEASE_SCOPE=target"

echo F8: Start/Pause input. F10: Start/Stop recording. F12: Exit.
echo Initially paused, recording OFF. Turn OFF game AUTO and switch to game.
echo FPS=%RHYTHM_FPS% Width=%RHYTHM_WIDTH% DownOffset=%RHYTHM_OFFSET%ms UpLead=%RHYTHM_RELEASE_LEAD%ms
echo DenseGap=%RHYTHM_DENSE_GAP%ms Recovery=%RHYTHM_DENSE_RECOVERY%ms Tap=%RHYTHM_DENSE_TAP%ms
echo GridSnap=%RHYTHM_GRID_SNAP%ms
echo SlideGuard=%RHYTHM_SLIDE_GUARD%ms
echo MinDown=%RHYTHM_MIN_DOWN%ms ReleaseGap=%RHYTHM_RELEASE_GAP%ms KeyLookahead=%RHYTHM_KEY_LOOKAHEAD%ms
"%~dp0.conda\python.exe" "%~dp0tools\rhythm_live_review.py" --live --input-mode all-held --release-scope %RHYTHM_RELEASE_SCOPE% --record --fps %RHYTHM_FPS% --analysis-width %RHYTHM_WIDTH% --offset-ms %RHYTHM_OFFSET% --release-lead-ms %RHYTHM_RELEASE_LEAD% --dense-gap-ms %RHYTHM_DENSE_GAP% --dense-recovery-ms %RHYTHM_DENSE_RECOVERY% --dense-tap-ms %RHYTHM_DENSE_TAP% --grid-snap-ms %RHYTHM_GRID_SNAP% --min-down-ms %RHYTHM_MIN_DOWN% --release-gap-ms %RHYTHM_RELEASE_GAP% --key-lookahead-ms %RHYTHM_KEY_LOOKAHEAD% --slide-guard-ms %RHYTHM_SLIDE_GUARD% --duration %RHYTHM_DURATION% %*
pause
