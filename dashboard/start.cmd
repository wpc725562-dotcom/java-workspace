@echo off
REM ============================================================================
REM  start.cmd -- one-click launcher for the java-workspace project dashboard
REM ----------------------------------------------------------------------------
REM  Usage:
REM      start.cmd              start on the default port (8990) and open a browser
REM      start.cmd 8991         start on a different port
REM
REM  Behaviour:
REM      1) locates a Python 3.8+ interpreter ("py -3" first, then "python")
REM      2) if the port is ALREADY listening, it just opens the browser. It does
REM         NOT start a second copy: server.py refuses to share a port, so a
REM         second launch would only print an error and exit.
REM      3) otherwise runs the server in the FOREGROUND -- the same shape as
REM         run-ollama.cmd / run-minio.cmd / run-nacos.cmd -- with the console
REM         captured to logs\dashboard-console-<port>.log
REM
REM  Why foreground instead of a detached background process:
REM      A redirect placed on a `start` line does not reach the child; the child
REM      inherits the parent console instead. Capturing a detached process needs
REM      `start "" cmd /c "..."`, and that form mangles quoting the moment a path
REM      contains a space. Foreground keeps the redirect on the real command
REM      line, and Ctrl+C is then a working stop button.
REM      To stop it from another window: dashboard\stop.cmd
REM
REM  Why no pip install is mentioned anywhere:
REM      server.py is standard-library only (http.server, json, subprocess, ...).
REM      Any CPython 3.8+ can run it. There is nothing to install.
REM
REM  Keep this file ASCII-only, CRLF. cmd reads .cmd with the OEM codepage (GBK on
REM  a Chinese Windows) while the file itself is UTF-8, so non-ASCII bytes turn
REM  into mojibake -- and mojibake on a REM line can leak out and be executed.
REM  Verify with:  grep -cP '[^\x00-\x7F]' dashboard/start.cmd   ->  must be 0
REM ============================================================================

setlocal

REM ---------------------------------------------------------------------------
REM  Workspace root = the parent folder of this script's folder.
REM  pushd normalises the "..", so %CD% gives a clean absolute path even when the
REM  workspace was reached through a junction, a UNC share or a trailing slash.
REM ---------------------------------------------------------------------------
pushd "%~dp0.." 2>nul
if errorlevel 1 (
  echo [FAIL] cannot resolve the workspace root from "%~dp0"
  exit /b 1
)
set "JW_WS=%CD%"
popd

set "JW_SRV=%JW_WS%\dashboard\server.py"
set "JW_LOGDIR=%JW_WS%\logs"
set "JW_PORT=%~1"
if "%JW_PORT%"=="" set "JW_PORT=8990"
set "JW_URL=http://127.0.0.1:%JW_PORT%/"

REM ---------------------------------------------------------------------------
REM  The log name carries the port, and that is not cosmetic.
REM  Two instances (say 8990 and 8991) writing to one file does not work: cmd's
REM  `>>` redirection cannot open a file another process already holds open, so
REM  the second instance dies at once with a Windows sharing violation:
REM      "The process cannot access the file because it is being used by
REM       another process."
REM  a message that mentions neither ports nor dashboards.
REM  (Quoted in English on purpose -- this file must stay ASCII-only, and the
REM   Chinese original cannot be reproduced here without mojibake risk.)
REM  (Measured: starting 8991 while 8990 was up failed exactly this way.)
REM ---------------------------------------------------------------------------
set "JW_LOG=%JW_LOGDIR%\dashboard-console-%JW_PORT%.log"

if not exist "%JW_SRV%" (
  echo [FAIL] server.py not found at "%JW_SRV%"
  exit /b 1
)

REM ---------------------------------------------------------------------------
REM  Locate a Python 3.8+ interpreter.
REM  "py -3" is tried first: it is the official Windows launcher and still works
REM  when python.exe is absent from PATH. Plain "python" is the fallback.
REM  Note the version assert: a Python 2 "python" on PATH would otherwise be
REM  picked up and fail much later with a confusing syntax error.
REM ---------------------------------------------------------------------------
set "PY="
py -3 -c "import sys;assert sys.version_info>=(3,8)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :py_found
python -c "import sys;assert sys.version_info>=(3,8)" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :py_found
echo [FAIL] no Python 3.8+ found. Tried "py -3" and "python".
echo        Install Python 3, or run the server with an explicit interpreter:
echo          "C:\path\to\python.exe" "%JW_SRV%"
exit /b 1

:py_found

REM ---------------------------------------------------------------------------
REM  Already running? Then this click means "take me there", not "start it".
REM  The trailing space in ":PORT " matters -- without it the pattern would also
REM  match a foreign address that merely starts with the same digits.
REM ---------------------------------------------------------------------------
netstat -ano | findstr /C:":%JW_PORT% " | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo [SKIP] port %JW_PORT% is already listening -- the dashboard is up.
  echo        opening %JW_URL%
  start "" "%JW_URL%"
  exit /b 0
)

if not exist "%JW_LOGDIR%" mkdir "%JW_LOGDIR%" >nul 2>&1

echo.
echo   java-workspace project dashboard
echo   ------------------------------------------------------------
echo   URL      %JW_URL%
echo   port     %JW_PORT%
echo   python   %PY%
echo   log      %JW_LOG%
echo   stop     Ctrl+C  --  or dashboard\stop.cmd from another window
echo   ------------------------------------------------------------
echo   bound to 127.0.0.1 only; never reachable from the LAN
echo   this page can start local processes, so that is deliberate
echo.

%PY% "%JW_SRV%" --port %JW_PORT% 1>>"%JW_LOG%" 2>&1
set "JW_RC=%ERRORLEVEL%"

REM ---------------------------------------------------------------------------
REM  A non-zero exit is NOT automatically a failure, so do not label it one.
REM  taskkill /F -- which is what dashboard\stop.cmd and Task Manager use -- makes
REM  the target exit with code 1. So stopping the dashboard the normal way lands
REM  here too, and printing "[FAIL]" would send you hunting for a bug that is not
REM  there. The log tail is still printed, because it is the only thing that tells
REM  the two cases apart, and hiding it would swallow real startup errors.
REM ---------------------------------------------------------------------------
if not "%JW_RC%"=="0" (
  echo.
  echo [END] exit code %JW_RC% -- normal when stopped via dashboard\stop.cmd
  echo       if you did NOT stop it, the cause is in the log tail below:
  echo.
  REM -Encoding UTF8 is not optional here: PowerShell 5.1's Get-Content reads
  REM using the ANSI codepage by default (GBK on a Chinese Windows) while this
  REM log is UTF-8, so omitting it prints pure mojibake and makes a perfectly
  REM healthy log look corrupted. Measured, not guessed.
  powershell -NoProfile -Command "Get-Content -Tail 25 -Encoding UTF8 -LiteralPath '%JW_LOG%'" 2>nul
  echo.
  exit /b %JW_RC%
)

exit /b 0
