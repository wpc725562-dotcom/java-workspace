@echo off
REM ============================================================================
REM  stop.cmd -- stop the java-workspace project dashboard
REM ----------------------------------------------------------------------------
REM  Usage:
REM      stop.cmd              stop the dashboard on the default port (8990)
REM      stop.cmd 8991         stop one running on a different port
REM
REM  Scope -- read this before assuming it cleans everything up:
REM      This stops ONLY the dashboard web server.
REM      Projects and middleware that the dashboard started KEEP RUNNING. That is
REM      intentional and matches how server.py spawns them: they are detached
REM      processes, and they already survive a plain Ctrl+C of the server. Killing
REM      the UI should not silently take down applications you are using.
REM      To stop those: use the dashboard's own stop buttons, or svc.cmd / p2.sh.
REM
REM  That is also why this uses `taskkill /F` and NOT `taskkill /T /F`:
REM      /T walks the child tree, and every project the dashboard launched is a
REM      child of the server -- /T would kill exactly the things this script is
REM      documented to leave alone.
REM
REM  Idempotent: when nothing is listening it prints a note and exits 0, so it is
REM  safe to call from a script or a scheduled task.
REM
REM  Keep this file ASCII-only, CRLF. cmd reads .cmd with the OEM codepage (GBK on
REM  a Chinese Windows) while the file itself is UTF-8, so non-ASCII bytes turn
REM  into mojibake -- and mojibake on a REM line can leak out and be executed.
REM  Verify with:  grep -cP '[^\x00-\x7F]' dashboard/stop.cmd   ->  must be 0
REM ============================================================================

setlocal enabledelayedexpansion

set "JW_PORT=%~1"
if "%JW_PORT%"=="" set "JW_PORT=8990"

REM ---------------------------------------------------------------------------
REM  Find the PID listening on the port. Column 5 of a netstat -ano row is the
REM  PID; the ":PORT " pattern has a trailing space so it cannot match a longer
REM  foreign address, and the LISTENING filter drops ESTABLISHED/TIME_WAIT rows.
REM ---------------------------------------------------------------------------
set "JW_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /C:":%JW_PORT% " ^| findstr /C:"LISTENING"') do set "JW_PID=%%P"

if not defined JW_PID (
  echo [SKIP] nothing is listening on port %JW_PORT% -- the dashboard is not running.
  exit /b 0
)

echo [STOP] killing PID !JW_PID! ...
taskkill /PID !JW_PID! /F >nul 2>&1
if errorlevel 1 (
  echo [FAIL] taskkill could not kill PID !JW_PID!.
  echo        It may belong to another user, or it may have already exited.
  exit /b 1
)

REM ---------------------------------------------------------------------------
REM  Confirm the port actually went away instead of trusting taskkill's exit code.
REM  TIME_WAIT rows linger for a while and are NOT a failure -- only a LISTENING
REM  row means something still holds the port.
REM ---------------------------------------------------------------------------
set "JW_STILL="
for /l %%I in (1,1,10) do (
  if not defined JW_STILL (
    netstat -ano | findstr /C:":%JW_PORT% " | findstr /C:"LISTENING" >nul 2>&1
    if not errorlevel 1 (
      ping -n 2 127.0.0.1 >nul 2>&1
      set "JW_STILL=1"
    )
  )
)

if defined JW_STILL (
  echo [WARN] port %JW_PORT% is still LISTENING after 5 seconds.
  echo        Something else may have taken it. Check with:
  echo          netstat -ano ^| findstr /C:":%JW_PORT% "
  exit /b 1
)

echo [ OK ] dashboard stopped; port %JW_PORT% released.
exit /b 0
