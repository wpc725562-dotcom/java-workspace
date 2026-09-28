@echo off
REM ============================================================================
REM  use-jdk.cmd -- switch JAVA_HOME / PATH for the CURRENT cmd window only
REM ----------------------------------------------------------------------------
REM  Usage:
REM      D:\java-workspace\use-jdk.cmd 8       (JDK 8  -> P0 eladmin-mp)
REM      D:\java-workspace\use-jdk.cmd 17      (JDK 17 -> P2 mall-swarm)
REM      D:\java-workspace\use-jdk.cmd 21      (JDK 21 -> P1 yu-ai-agent)
REM      D:\java-workspace\use-jdk.cmd list
REM      D:\java-workspace\use-jdk.cmd status
REM
REM  NOTE: batch files cannot modify the caller's environment by "running";
REM        they must be CALLed. Calling with a full path works fine --
REM        cmd treats a directly-invoked .cmd as a call in the same context.
REM        Do NOT wrap this in `cmd /c`, that WOULD lose the changes.
REM
REM  System environment variables are never touched. Close the window to undo.
REM  (Comments are ASCII-only on purpose: non-ASCII in .cmd gets mangled by
REM   the console codepage and can corrupt the file's parsing.)
REM ============================================================================

setlocal EnableDelayedExpansion

set "WS=%~dp0"
if "%WS:~-1%"=="\" set "WS=%WS:~0,-1%"

set "JDK8=%WS%\.jdks\corretto-8"
set "JDK17=C:\Program Files\Amazon Corretto\jdk17.0.20_10"
set "JDK21=%WS%\.jdks\corretto-21"

if "%~1"==""          goto :usage
if /I "%~1"=="list"   goto :list
if /I "%~1"=="status" goto :status
if /I "%~1"=="-h"     goto :usage
if /I "%~1"=="--help" goto :usage
if "%~1"=="8"         goto :pick8
if /I "%~1"=="1.8"    goto :pick8
if /I "%~1"=="java8"  goto :pick8
if "%~1"=="17"        goto :pick17
if /I "%~1"=="java17" goto :pick17
if "%~1"=="21"        goto :pick21
if /I "%~1"=="java21" goto :pick21

echo [ERROR] Unknown version "%~1". Use: 8 / 17 / 21 / list / status
goto :eof

:pick8
set "JH=%JDK8%"
set "VER=8"
set "NAME=Amazon Corretto 8"
set "JTO=-Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8"
goto :apply

:pick17
set "JH=%JDK17%"
set "VER=17"
set "NAME=Amazon Corretto 17 (system)"
set "JTO=-Dfile.encoding=UTF-8"
goto :apply

:pick21
set "JH=%JDK21%"
set "VER=21"
set "NAME=Amazon Corretto 21"
set "JTO="
goto :apply

:apply
if not exist "%JH%\bin\java.exe" (
  echo [ERROR] JDK %VER% not found at:
  echo         %JH%
  echo.
  echo         Run "%~nx0 list" to see what is available.
  endlocal
  exit /b 1
)

REM Strip any previously-injected JDK bin dirs so PATH does not grow on every switch.
set "NEWPATH=%PATH%"
call :strip "%JDK8%\bin"
call :strip "%JDK17%\bin"
call :strip "%JDK21%\bin"

REM endlocal + set on ONE line: %JH%, %NEWPATH% and %JTO% below are expanded
REM BEFORE endlocal runs, so the values survive into the caller's scope.
REM Setting JAVA_TOOL_OPTIONS to an empty string DELETES it, which is what we
REM want for JDK 21 (already UTF-8 by default since JEP 400).
REM
REM SERVER__PORT / SERVER__HOST are cleared for the same reason (empty value
REM deletes the variable). The WorkBuddy desktop app injects them into every
REM process it spawns, pointing at its own backend (port 22407). Spring Boot's
REM relaxed binding reads SERVER__PORT as server.port, so any Spring app started
REM from such a session tries to bind the harness's own port and dies with
REM     Tomcat initialized with port 22407 (http)
REM     APPLICATION FAILED TO START ... PortInUseException
REM Measured on eladmin (P0) and on Nacos itself -- Nacos 3.x is a Spring Boot
REM 3.4 app and is not immune. Your own terminal will not have these vars, but
REM clearing them costs nothing and removes a very misleading failure mode.
endlocal & set "JAVA_HOME=%JH%" & set "PATH=%JH%\bin;%NEWPATH%" & set "JAVA_TOOL_OPTIONS=%JTO%" & set "SERVER__PORT=" & set "SERVER__HOST="

echo Switched to JDK %VER% -- %NAME%
echo    JAVA_HOME = %JH%
if not "%JTO%"=="" echo    Encoding  = %JTO%
"%JH%\bin\java.exe" -version 2>&1 | findstr /R /C:"version"
goto :eof

REM -- helper: remove a dir from NEWPATH (delayed expansion, so !NEWPATH! is live)
:strip
set "RM=%~1"
if "!NEWPATH!"=="" goto :eof
set "NEWPATH=!NEWPATH:%RM%=!"
set "NEWPATH=!NEWPATH:;;=;!"
if "!NEWPATH:~0,1!"==";" set "NEWPATH=!NEWPATH:~1!"
goto :eof

:list
echo.
echo   VER   STATUS    PATH
echo   ------------------------------------------------------------------------------------
call :showone 8  "%JDK8%"
call :showone 17 "%JDK17%"
call :showone 21 "%JDK21%"
echo.
call :status
echo.
endlocal
goto :eof

:showone
set "V=%~1"
set "P=%~2"
if exist "%P%\bin\java.exe" (set "S=ready  ") else (set "S=MISSING")
echo   %V%     !S!  %P%
goto :eof

:status
if "%JAVA_HOME%"=="" (
  echo   Current: JAVA_HOME is NOT set
) else (
  echo   Current: %JAVA_HOME%
  "%JAVA_HOME%\bin\java.exe" -version 2>&1 | findstr /R /C:"version"
)
endlocal
goto :eof

:usage
echo.
echo  use-jdk.cmd -- switch JDK for the current cmd window only
echo.
echo    use-jdk.cmd 8        JDK 8   --^> P0 eladmin-mp
echo    use-jdk.cmd 17       JDK 17  --^> P2 mall-swarm
echo    use-jdk.cmd 21       JDK 21  --^> P1 yu-ai-agent
echo    use-jdk.cmd list     list all JDKs and their status
echo    use-jdk.cmd status   show the currently active JDK
echo.
echo  System environment variables are never modified.
echo  Close the window, or run this without a switch, to undo.
echo.
endlocal
goto :eof
