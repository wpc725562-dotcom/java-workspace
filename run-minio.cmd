@echo off
REM ============================================================================
REM  run-minio.cmd -- portable MinIO server launcher
REM ----------------------------------------------------------------------------
REM  Usage:
REM      run-minio.cmd              run the server in the FOREGROUND
REM
REM  Why a wrapper:
REM   1) MinIO reads its root credentials from the environment
REM      (MINIO_ROOT_USER / MINIO_ROOT_PASSWORD). They have to match what
REM      mall-swarm expects, and that expectation lives in mall-admin's config:
REM          config\admin\mall-admin-dev.yaml
REM              minio.endpoint   : http://localhost:9000
REM              minio.bucketName : mall
REM              minio.accessKey  : minioadmin
REM              minio.secretKey  : minioadmin
REM      Keeping the credentials here means they are set the same way every
REM      time, instead of depending on whatever the shell happens to export.
REM
REM   2) --console-address has to be pinned. Left alone, MinIO picks a RANDOM
REM      free port for the web console on every start, which makes it
REM      impossible to bookmark or document.
REM
REM   3) Foreground execution, same as run-nacos.cmd / run-rabbitmq.cmd: a
REM      redirect placed on a `start` line does not reliably reach the child,
REM      so the console log is captured here, on the real command line.
REM
REM  Keep this file ASCII-only, CRLF. cmd reads .cmd with the OEM codepage (GBK
REM  on a Chinese Windows) while the file is UTF-8, so non-ASCII bytes turn into
REM  mojibake -- and mojibake on a REM line can leak out and be executed.
REM  Verify with:  grep -cP '[^\x00-\x7F]' run-minio.cmd   ->  must be 0
REM ============================================================================

setlocal enabledelayedexpansion

set "JW_WS=%~dp0"
if "%JW_WS:~-1%"=="\" set "JW_WS=%JW_WS:~0,-1%"
set "JW_RT=%JW_WS%\.runtime"
set "JW_BIN=%JW_RT%\minio\minio.exe"
set "JW_DATA=%JW_RT%\data\minio"
set "JW_LOGDIR=%JW_RT%\logs"

if not exist "%JW_BIN%" (
  echo [FAIL] MinIO not found at "%JW_BIN%"
  exit /b 1
)
if not exist "%JW_DATA%" mkdir "%JW_DATA%"
if not exist "%JW_LOGDIR%" mkdir "%JW_LOGDIR%"

REM ---------------------------------------------------------------------------
REM  Root credentials -- must match mall-admin's minio.accessKey / minio.secretKey
REM ---------------------------------------------------------------------------
set "MINIO_ROOT_USER=minioadmin"
set "MINIO_ROOT_PASSWORD=minioadmin"

REM Keep the browser from trying to reach the console over a proxy.
set "MINIO_BROWSER_REDIRECT_URL=http://127.0.0.1:9001"

REM ---------------------------------------------------------------------------
REM  Sanitise the inherited environment (same habit as the other launchers).
REM  MinIO is a Go binary and not a Spring app, so SERVER__PORT cannot hijack it.
REM ---------------------------------------------------------------------------
set "SERVER__PORT="
set "SERVER__HOST="

REM ---------------------------------------------------------------------------
REM  Listen on loopback only, same security boundary as every other service.
REM  The console port is pinned so it is the same on every start.
REM ---------------------------------------------------------------------------
echo [RUN] minio server  (foreground; console redirected to %JW_LOGDIR%\minio-console.log)
echo       API     : http://127.0.0.1:9000
echo       Console : http://127.0.0.1:9001    user minioadmin / minioadmin
echo       Data    : %JW_DATA%
"%JW_BIN%" server "%JW_DATA%" --address 127.0.0.1:9000 --console-address 127.0.0.1:9001 > "%JW_LOGDIR%\minio-console.log" 2>&1
exit /b %ERRORLEVEL%
