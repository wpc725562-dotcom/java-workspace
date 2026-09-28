@echo off
REM ============================================================================
REM  run-nacos.cmd -- run Nacos 3.x standalone, capturing stdout+stderr
REM ----------------------------------------------------------------------------
REM  Why this file exists instead of svc.cmd starting java directly:
REM
REM  Redirection placed on a `start` line does not reliably reach the child.
REM  `start` creates the child with bInheritHandles=TRUE and the child ends up
REM  holding the parent's ORIGINAL handles -- which is also why
REM  `svc.cmd start redis | tail` used to hang: the daemon kept the pipe's write
REM  end open, so the reader never saw EOF. Putting the redirection inside this
REM  wrapper puts it on the java command itself, where it always applies.
REM
REM  Side benefit: running this file directly runs Nacos in the FOREGROUND,
REM  which is what you want when it refuses to start and you need to read the
REM  stack trace live. svc.cmd logs nacos tails the captured file instead.
REM
REM  Keep this file ASCII-only, CRLF. cmd reads .cmd with the OEM codepage (GBK
REM  on a Chinese Windows) while the file is UTF-8, so non-ASCII bytes turn into
REM  mojibake -- and mojibake on a REM line can leak out and be executed.
REM
REM  The workspace path must not contain spaces: %NACOS% is spliced unquoted into
REM  -Dnacos.home / -Dloader.path / --spring.config.additional-location.
REM ============================================================================

set "WS=%~dp0"
if "%WS:~-1%"=="\" set "WS=%WS:~0,-1%"
set "RT=%WS%\.runtime"
set "NACOS=%RT%\nacos\nacos"
set "LOGS=%RT%\logs"

REM Nacos 3.x needs JDK 17+. Pinned deliberately: the shell's JAVA_HOME gets
REM switched around by use-jdk.sh / use-jdk.cmd, and inheriting it would start
REM Nacos on JDK 8 and fail. Override with:  set NACOS_JDK=D:\some\jdk17
if "%NACOS_JDK%"=="" set "NACOS_JDK=C:\Program Files\Amazon Corretto\jdk17.0.20_10"

if not exist "%NACOS%\target\nacos-server.jar" (
  echo [FAIL] Nacos not found at "%NACOS%\target\nacos-server.jar"
  exit /b 1
)
if not exist "%NACOS_JDK%\bin\java.exe" (
  echo [FAIL] No java.exe under "%NACOS_JDK%" -- Nacos 3.x needs JDK 17+
  exit /b 1
)
if not exist "%LOGS%" mkdir "%LOGS%"

REM ---------------------------------------------------------------------------
REM  Sanitise the inherited environment.
REM
REM  The WorkBuddy desktop app injects SERVER__HOST and SERVER__PORT into every
REM  process it spawns -- they point at its own backend service. Spring Boot's
REM  relaxed binding reads SERVER__PORT as server.port, so any Spring app started
REM  from inside a WorkBuddy session tries to bind the harness's own port and
REM  dies with:
REM      Tomcat initialized with port 22407 (http)
REM      APPLICATION FAILED TO START ... PortInUseException
REM
REM  Measured twice, on two different apps: eladmin (P0) and Nacos itself.
REM  Nacos 3.x IS a Spring Boot 3.4 application, so it is not immune. Before this
REM  line existed, Nacos logged "started successfully" and then failed to bind.
REM
REM  Clearing them here means Nacos always lands on 8848 (client) and 8849
REM  (console) regardless of who launched it.
REM ---------------------------------------------------------------------------
set "SERVER__PORT="
set "SERVER__HOST="

REM Flags below are copied from the standalone branch of the vendor's
REM bin\startup.cmd so that this stays behaviourally identical to the
REM documented launch path.
set "NOPTS=-Dnacos.standalone=true -Xms512m -Xmx512m -Xmn256m -Dnacos.deployment.mode=merged"
set "NOPTS=%NOPTS% -Dloader.path=%NACOS%/plugins,%NACOS%/plugins/health,%NACOS%/plugins/cmdb,%NACOS%/plugins/selector"
set "NOPTS=%NOPTS% -Dnacos.home=%NACOS%"
set "NOPTS=%NOPTS% -jar %NACOS%\target\nacos-server.jar"
set "NOPTS=%NOPTS% --spring.config.additional-location=file:%NACOS%/conf/"
set "NOPTS=%NOPTS% --logging.config=%NACOS%/conf/nacos-logback.xml"

REM The program arg "nacos.nacos" is load-bearing: the vendor's bin\shutdown.cmd
REM locates the process with  jps -m ^| find "nacos.nacos"  . Without it, stop
REM cannot find the JVM and falls back to a PID kill on 8848.
"%NACOS_JDK%\bin\java.exe" %NOPTS% nacos.nacos > "%LOGS%\nacos-console.log" 2>&1
