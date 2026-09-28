@echo off
REM ============================================================================
REM  run-ollama.cmd -- portable Ollama server launcher (used by P1 yu-ai-agent)
REM ----------------------------------------------------------------------------
REM  Usage:
REM      run-ollama.cmd              run the server in the FOREGROUND
REM
REM  Why a wrapper (same three reasons as run-minio.cmd / run-nacos.cmd):
REM
REM   1) OLLAMA_MODELS has to be pinned. Left alone, Ollama stores every pulled
REM      model under %USERPROFILE%\.ollama\models -- i.e. OUTSIDE this workspace.
REM      That breaks the "everything portable, nothing left behind in the user
REM      profile" promise the rest of .runtime follows. (Same class of problem
REM      as the Erlang cookie that used to land in %USERPROFILE% until
REM      run-rabbitmq.cmd started repointing HOMEDRIVE/HOMEPATH.)
REM
REM   2) OLLAMA_HOST is pinned to loopback, matching the security boundary of
REM      every other service here (bind 127.0.0.1, never 0.0.0.0).
REM      Ollama has NO authentication -- exposing it to the LAN means anyone on
REM      the Wi-Fi can run models on this machine.
REM
REM   3) Foreground execution: a redirect placed on a `start` line does not
REM      reliably reach the child, so the console log is captured here, on the
REM      real command line.
REM
REM  First run:
REM      1) run-ollama.cmd                     (leave it running)
REM      2) ollama pull gemma3:1b              (chat model,      ~815 MB)
REM         ollama pull nomic-embed-text       (embedding model, ~274 MB)
REM     Both are read from OLLAMA_MODELS, so they land inside the workspace.
REM
REM  Verify the server is up:
REM      curl http://127.0.0.1:11434/api/tags
REM
REM  Keep this file ASCII-only, CRLF. cmd reads .cmd with the OEM codepage (GBK
REM  on a Chinese Windows) while the file is UTF-8, so non-ASCII bytes turn into
REM  mojibake -- and mojibake on a REM line can leak out and be executed.
REM  Verify with:  grep -cP '[^\x00-\x7F]' run-ollama.cmd   ->  must be 0
REM ============================================================================

setlocal enabledelayedexpansion

set "JW_WS=%~dp0"
if "%JW_WS:~-1%"=="\" set "JW_WS=%JW_WS:~0,-1%"
set "JW_RT=%JW_WS%\.runtime"
set "JW_BIN=%JW_RT%\ollama\ollama.exe"
set "JW_MODELS=%JW_RT%\ollama\models"
set "JW_LOGDIR=%JW_RT%\logs"

if not exist "%JW_BIN%" (
  echo [FAIL] Ollama not found at "%JW_BIN%"
  exit /b 1
)
if not exist "%JW_MODELS%" mkdir "%JW_MODELS%"
if not exist "%JW_LOGDIR%" mkdir "%JW_LOGDIR%"

REM ---------------------------------------------------------------------------
REM  Keep models and the server socket inside the workspace.
REM ---------------------------------------------------------------------------
set "OLLAMA_MODELS=%JW_MODELS%"
set "OLLAMA_HOST=127.0.0.1:11434"

REM ---------------------------------------------------------------------------
REM  Sanitise the inherited environment (same habit as the other launchers).
REM  Ollama is a Go binary, not a Spring app, so SERVER__PORT cannot hijack it --
REM  but the variable is cleared anyway so nothing downstream inherits it.
REM ---------------------------------------------------------------------------
set "SERVER__PORT="
set "SERVER__HOST="

echo [RUN] ollama serve  (foreground; console redirected to %JW_LOGDIR%\ollama-console.log)
echo       API    : http://127.0.0.1:11434
echo       Models : %JW_MODELS%
echo       Pull   : ollama pull gemma3:1b    /    ollama pull nomic-embed-text
"%JW_BIN%" serve > "%JW_LOGDIR%\ollama-console.log" 2>&1
exit /b %ERRORLEVEL%
