@echo off
REM ============================================================================
REM  run-rabbitmq.cmd -- portable RabbitMQ 4.3.6 launcher / control wrapper
REM ----------------------------------------------------------------------------
REM  Usage:
REM      run-rabbitmq.cmd                     run the broker in the FOREGROUND
REM      run-rabbitmq.cmd ctl <args...>       run rabbitmqctl.bat  <args>
REM      run-rabbitmq.cmd plugins <args...>   run rabbitmq-plugins.bat <args>
REM      run-rabbitmq.cmd diagnostics <args>  run rabbitmq-diagnostics.bat
REM      run-rabbitmq.cmd queues <args...>    run rabbitmq-queues.bat
REM
REM  Anything after the subcommand is forwarded verbatim (up to 8 arguments).
REM
REM  ---------------------------------------------------------------------------
REM  !! DO NOT NAME ANY VARIABLE IN THIS FILE "LOGS" !!
REM  ---------------------------------------------------------------------------
REM  RabbitMQ reads an environment variable named LOGS -- plain "LOGS", NOT
REM  "RABBITMQ_LOGS" -- and uses its value as the log FILE path. If LOGS points
REM  at a directory (which is exactly what a variable called LOGS would
REM  naturally hold), the broker dies during prelaunch, before it even reads
REM  rabbitmq.conf:
REM
REM      BOOT FAILED
REM      ===========
REM      failed to open log file at 'd:/java-workspace/.runtime/logs',
REM      reason: illegal operation on a directory
REM
REM  Measured, not guessed. With the node stopped and everything else held
REM  constant, adding ONLY  LOGS=D:\java-workspace\.runtime\logs  reproduced the
REM  failure; removing it and changing nothing else booted the broker. The
REM  failure happens BEFORE the config file is parsed, so nothing in
REM  rabbitmq.conf can work around it -- and because no "config file(s)" line
REM  is ever printed, the log gives no hint that an env var is involved.
REM
REM  Hence: every local in this file carries a JW_ prefix. svc.cmd was renamed
REM  from LOGS to LOGDIR for the same reason -- it starts the broker too, and a
REM  child inherits the parent's environment.
REM
REM  ---------------------------------------------------------------------------
REM  Why a wrapper instead of calling sbin\*.bat directly:
REM
REM  1) ERLANG_HOME. rabbitmq-server.bat hard-fails unless
REM         %ERLANG_HOME%\bin\erl.exe
REM     exists (rabbitmq-server.bat line 28). Without ERLANG_HOME it falls back
REM     to asking PowerShell to locate erl.exe on PATH -- which would mean
REM     touching the system PATH. Setting ERLANG_HOME here keeps the whole
REM     stack self-contained: delete .runtime and nothing is left behind.
REM
REM  2) RABBITMQ_BASE. Defaults to %APPDATA%\RabbitMQ, i.e. OUTSIDE the
REM     workspace -- mnesia data, logs, .erlang.cookie and rabbitmq.conf would
REM     all land in the user profile. Pointing it at
REM     .runtime\data\rabbitmq keeps everything inside .runtime.
REM     It also means rabbitmq.conf is picked up from its DEFAULT location,
REM     so RABBITMQ_CONFIG_FILE never has to be set -- which sidesteps the
REM     ambiguous "does it want the .conf extension or not" question entirely.
REM
REM  3) Foreground execution. Same reason as run-nacos.cmd: redirection placed
REM     on a `start` line does not reliably reach the child, so the console log
REM     is captured HERE, on the actual command line.
REM
REM  Keep this file ASCII-only, CRLF. cmd reads .cmd with the OEM codepage (GBK
REM  on a Chinese Windows) while the file is UTF-8, so non-ASCII bytes turn into
REM  mojibake -- and mojibake on a REM line can leak out and be executed.
REM  Verify with:  grep -cP '[^\x00-\x7F]' run-rabbitmq.cmd   ->  must be 0
REM ============================================================================

setlocal enabledelayedexpansion

set "JW_WS=%~dp0"
if "%JW_WS:~-1%"=="\" set "JW_WS=%JW_WS:~0,-1%"
set "JW_RT=%JW_WS%\.runtime"
set "JW_ERL=%JW_RT%\erlang"
set "JW_RMQ=%JW_RT%\rabbitmq\rabbitmq_server-4.3.6"
set "JW_RMBASE=%JW_RT%\data\rabbitmq"
set "JW_LOGDIR=%JW_RT%\logs"

if not exist "%JW_ERL%\bin\erl.exe" (
  echo [FAIL] Erlang not found at "%JW_ERL%\bin\erl.exe"
  exit /b 1
)
if not exist "%JW_RMQ%\sbin\rabbitmq-server.bat" (
  echo [FAIL] RabbitMQ not found at "%JW_RMQ%\sbin\rabbitmq-server.bat"
  exit /b 1
)
if not exist "%JW_RMBASE%" mkdir "%JW_RMBASE%"
if not exist "%JW_RMBASE%\log" mkdir "%JW_RMBASE%\log"
if not exist "%JW_LOGDIR%" mkdir "%JW_LOGDIR%"

REM ---------------------------------------------------------------------------
REM  Erlang / RabbitMQ home
REM ---------------------------------------------------------------------------
set "ERLANG_HOME=%JW_ERL%"
set "RABBITMQ_BASE=%JW_RMBASE%"
set "RABBITMQ_HOME=%JW_RMQ%"

REM Pin the node name. The default is rabbit@%COMPUTERNAME%, which requires that
REM the machine name resolves to itself. It normally does, but on a laptop that
REM has been renamed or is off-VPN it can fail with "unable to connect to epmd",
REM which looks like a RabbitMQ bug rather than a DNS problem.
set "RABBITMQ_NODENAME=rabbit@localhost"

REM ---------------------------------------------------------------------------
REM  Keep the Erlang cookie inside the workspace.
REM
REM  Erlang stores its distribution cookie at <home>\.erlang.cookie, and on
REM  Windows <home> defaults to %USERPROFILE% -- i.e. C:\Users\<name>\.erlang.cookie,
REM  OUTSIDE .runtime. That breaks the "delete .runtime and nothing is left
REM  behind" promise, so the home directory is repointed at RABBITMQ_BASE.
REM
REM  NOTE: setting HOME alone does NOT work -- measured, the cookie still landed
REM  in %USERPROFILE%. Erlang's Windows code path reads HOMEDRIVE + HOMEPATH,
REM  not HOME. Both are set below.
REM
REM  Measured: move the profile cookie away, start the broker, and a fresh one
REM  is created -- so it IS this stack's footprint, not something pre-existing.
REM  (Careful: the file's timestamp reads 00:00:00 regardless of when it was
REM  written, so do NOT judge its age from the metadata.)
REM
REM  Both the broker and rabbitmqctl go through this file, so they always agree
REM  on the cookie -- which is the only thing that matters for them to talk.
REM ---------------------------------------------------------------------------
set "HOMEDRIVE=%~d0"
set "HOMEPATH=%JW_RMBASE:~2%"
set "HOME=%JW_RMBASE%"

REM ---------------------------------------------------------------------------
REM  Sanitise the inherited environment.
REM  RabbitMQ is NOT a Spring app, so SERVER__PORT does not hijack it -- but
REM  leaving a stray SERVER__HOST/SERVER__PORT in the child environment is a
REM  foot-gun for anything RabbitMQ spawns later. Clearing is free.
REM ---------------------------------------------------------------------------
set "SERVER__PORT="
set "SERVER__HOST="

REM ---------------------------------------------------------------------------
REM  Dispatch
REM ---------------------------------------------------------------------------
if "%~1"=="" goto :runserver

set "JW_SUB=%~1"
set "JW_ARGS="
shift
:collect
if "%~1"=="" goto :rundispatch
set "JW_ARGS=!JW_ARGS! %1"
shift
goto :collect

:rundispatch
REM Map the short subcommand onto the real script name. Only `ctl` deviates:
REM the file is rabbitmqctl.bat, NOT rabbitmq-ctl.bat. The rest follow the
REM rabbitmq-<sub>.bat pattern.
if /I "%JW_SUB%"=="ctl" (
  set "JW_TARGET=%JW_RMQ%\sbin\rabbitmqctl.bat"
) else (
  set "JW_TARGET=%JW_RMQ%\sbin\rabbitmq-%JW_SUB%.bat"
)
if not exist "!JW_TARGET!" (
  echo [FAIL] No such RabbitMQ tool: "!JW_TARGET!"
  echo        Expected one of: ctl, plugins, diagnostics, queues, upgrade, streams
  exit /b 1
)
echo [RUN] %JW_SUB%.bat !JW_ARGS!
call "!JW_TARGET!" !JW_ARGS!
exit /b %ERRORLEVEL%

:runserver
REM The vendor script writes its own log under %RABBITMQ_BASE%\log. The
REM redirection below captures the CONSOLE output, which is where startup
REM errors surface first -- and on a first run it is the only place that shows
REM the "config file(s) : ..." line, which is how you confirm which
REM rabbitmq.conf actually got loaded.
echo [RUN] rabbitmq-server.bat  (foreground; console redirected to %JW_LOGDIR%\rabbitmq-console.log)
call "%JW_RMQ%\sbin\rabbitmq-server.bat" > "%JW_LOGDIR%\rabbitmq-console.log" 2>&1
exit /b %ERRORLEVEL%
