@echo off
REM ============================================================================
REM  svc.cmd -- portable MySQL / Redis / Nacos lifecycle manager
REM ----------------------------------------------------------------------------
REM  Everything lives under D:\java-workspace\.runtime\ . Nothing is installed as
REM  a Windows service and no system setting is touched. Delete the folder and it
REM  is gone -- no leftover registry keys, no autostart entry, no PATH edit.
REM
REM  Usage:
REM      svc.cmd init              one-time: init data dirs, set root pw, create schemas
REM      svc.cmd start  [target]   start  mysql8 | mysql57 | redis | nacos | mongodb
REM                                      | elasticsearch | rabbitmq | minio | all | full
REM      svc.cmd stop   [target]   graceful shutdown
REM      svc.cmd restart [target]
REM      svc.cmd status            show listening state of every service
REM      svc.cmd cli    <target>   open a mysql / redis / mongodb client
REM      svc.cmd logs   <target>   tail the log file
REM
REM      all  = mysql8 + mysql57 + redis   (what P0/P1 need -- fast)
REM      full = all + nacos + mongodb + elasticsearch + rabbitmq + minio
REM                                        (what P2 needs)
REM
REM  !! DO NOT CREATE A VARIABLE NAMED "LOGS" ANYWHERE IN THIS FILE !!
REM  RabbitMQ reads an env var called plain "LOGS" (not RABBITMQ_LOGS) and treats
REM  it as its log FILE path. Because `start` gives the child the parent's whole
REM  environment, a LOGS variable here would break the broker with
REM      BOOT FAILED ... failed to open log file at '<the directory>',
REM      reason: illegal operation on a directory
REM  before it even reads rabbitmq.conf. It used to be called LOGS; it is now
REM  LOGDIR. See the header of run-rabbitmq.cmd for the measurement.
REM
REM  Output is intentionally ASCII-only: cmd.exe writes GBK on a Chinese Windows
REM  and piping that into Git Bash produces mojibake. Keep it English, stay safe.
REM
REM  Design note: action handlers use plain `exit /b`, never `endlocal & exit /b`.
REM  A subroutine entered via `call` that runs `endlocal` would pop the script-level
REM  setlocal, and every !delayed! variable after it would silently go wrong.
REM ============================================================================

setlocal EnableDelayedExpansion

set "WS=%~dp0"
if "%WS:~-1%"=="\" set "WS=%WS:~0,-1%"
set "RT=%WS%\.runtime"
set "CONF=%RT%\conf"
set "LOGDIR=%RT%\logs"
set "SQLDIR=%WS%\sql"

set "H8=%RT%\mysql-8.0"
set "H57=%RT%\mysql-5.7"
set "HR=%RT%\redis"
set "HM=%RT%\mongodb"
set "HE=%RT%\elasticsearch"
set "ERL=%RT%\erlang"
set "HRMQ=%RT%\rabbitmq\rabbitmq_server-4.3.6"
set "HMINIO=%RT%\minio"
set "D8=%RT%\data\mysql8"
set "D57=%RT%\data\mysql57"
set "DR=%RT%\data\redis"
set "DM=%RT%\data\mongodb"
set "DE=%RT%\data\elasticsearch"
set "DRMQ=%RT%\data\rabbitmq"
set "DMINIO=%RT%\data\minio"

REM Nacos 3.x needs JDK 17+. It is NOT the same JDK the projects use, so the
REM path is pinned here instead of reading the ambient JAVA_HOME -- the user
REM switches JDKs with use-jdk.sh/use-jdk.cmd, and inheriting that would start
REM Nacos on the wrong JVM. Override with:  set NACOS_JDK=D:\some\jdk17
set "NACOS=%RT%\nacos\nacos"
if "%NACOS_JDK%"=="" set "NACOS_JDK=C:\Program Files\Amazon Corretto\jdk17.0.20_10"

set "PW=123456"

set "ACTION=%~1"
set "TARGET=%~2"
if "%TARGET%"=="" set "TARGET=all"

if "%ACTION%"==""           goto :usage
if /I "%ACTION%"=="help"    goto :usage
if /I "%ACTION%"=="-h"      goto :usage
if /I "%ACTION%"=="--help"  goto :usage
if /I "%ACTION%"=="init"    goto :act_init
if /I "%ACTION%"=="start"   goto :act_start
if /I "%ACTION%"=="stop"    goto :act_stop
if /I "%ACTION%"=="restart" goto :act_restart
if /I "%ACTION%"=="status"  goto :act_status
if /I "%ACTION%"=="cli"     goto :act_cli
if /I "%ACTION%"=="logs"    goto :act_logs

echo [ERROR] unknown action "%ACTION%"
goto :usage


REM ===========================================================================
REM  init -- one-time bootstrap
REM ===========================================================================
:act_init
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if not exist "%RT%\tmp" mkdir "%RT%\tmp"

echo.
echo === [1/4] MySQL 8.0 : data directory ===
call :initone "%H8%" "%CONF%\mysql8.ini" "%D8%" "MySQL 8.0"

echo.
echo === [2/4] MySQL 5.7 : data directory ===
call :initone "%H57%" "%CONF%\mysql57.ini" "%D57%" "MySQL 5.7"

echo.
echo === [3/4] Redis : data directory ===
if not exist "%DR%" mkdir "%DR%"
echo [OK] Redis data dir ready (nothing to initialize)

echo.
echo === [4/4] Start everything, then configure ===
call :startone mysql8
call :startone mysql57
call :startone redis

echo.
echo Waiting for MySQL 8.0 on 3308 ...
call :waitport 3308 90
if errorlevel 1 goto :initfail
echo Waiting for MySQL 5.7 on 3307 ...
call :waitport 3307 90
if errorlevel 1 goto :initfail
echo Waiting for Redis on 6380 ...
call :waitport 6380 30
if errorlevel 1 goto :initfail

call :setrootpw "%H8%"  "%CONF%\mysql8.ini"  "MySQL 8.0"
call :setrootpw "%H57%" "%CONF%\mysql57.ini" "MySQL 5.7"

echo.
echo Creating schemas and the dev account ...
if not exist "%SQLDIR%\01-schemas.sql" (
  echo [WARN] %SQLDIR%\01-schemas.sql not found -- skipping schema creation
) else (
  REM mysql prints "Using a password on the command line interface can be
  REM insecure" on every invocation that passes -p. MYSQL_PWD avoids that.
  REM It is scoped to this cmd process only, so nothing leaks into the user's
  REM environment. Cleared again as soon as the schema work is done.
  set "MYSQL_PWD=%PW%"
  "%H8%\bin\mysql.exe"  --defaults-file="%CONF%\mysql8.ini"  -uroot --default-character-set=utf8mb4 < "%SQLDIR%\01-schemas.sql"
  if errorlevel 1 (echo [WARN] MySQL 8.0 : schema script reported an error) else (echo [OK] MySQL 8.0 schemas ready)
  "%H57%\bin\mysql.exe" --defaults-file="%CONF%\mysql57.ini" -uroot --default-character-set=utf8mb4 < "%SQLDIR%\01-schemas.sql"
  if errorlevel 1 (echo [WARN] MySQL 5.7 : schema script reported an error) else (echo [OK] MySQL 5.7 schemas ready)
  set "MYSQL_PWD="
)

echo.
echo ===========================================================================
echo  Init complete -- everything is up.
echo    MySQL 8.0   127.0.0.1:3308    root/%PW%    dev/dev123456
echo    MySQL 5.7   127.0.0.1:3307    root/%PW%    dev/dev123456
echo    Redis       127.0.0.1:6380    (no password)
echo.
echo  "svc.cmd status" to check, "svc.cmd stop" to shut down.
echo ===========================================================================
exit /b 0

:initfail
echo.
echo [FAIL] something did not come up. Check the logs:
echo        %LOGDIR%\mysql8-error.log
echo        %LOGDIR%\mysql57-error.log
echo        %LOGDIR%\redis.log
exit /b 1


REM ===========================================================================
REM  start / stop / restart
REM ===========================================================================
:act_start
call :dispatch start
exit /b 0

:act_stop
call :dispatch stop
exit /b 0

:act_restart
call :dispatch stop
call :sleepps 3
call :dispatch start
exit /b 0

REM dispatch <verb> -- honours %TARGET%, or an explicit "all" / "full"
REM   all  = the three core services only. Nacos is deliberately excluded: it
REM          takes ~30s and 512MB, and P0/P1 never touch it. Keeping "all" fast
REM          matters because it is what gets run every day.
REM   full = all + nacos + mongodb + elasticsearch + rabbitmq  (what P2 needs)
:dispatch
set "_V=%~1"
if /I "%TARGET%"=="all" (
  call :doone %_V% mysql8
  call :doone %_V% mysql57
  call :doone %_V% redis
) else if /I "%TARGET%"=="full" (
  call :doone %_V% mysql8
  call :doone %_V% mysql57
  call :doone %_V% redis
  call :doone %_V% nacos
  call :doone %_V% mongodb
  call :doone %_V% elasticsearch
  call :doone %_V% rabbitmq
  call :doone %_V% minio
) else (
  call :doone %_V% "%TARGET%"
)
exit /b 0

:doone
set "_V=%~1"
set "_T=%~2"
if /I "%_V%"=="start" call :startone "%_T%"
if /I "%_V%"=="stop"  call :stopone  "%_T%"
exit /b 0

:startone
if /I "%~1"=="mysql8"        goto :sm8
if /I "%~1"=="mysql57"       goto :sm57
if /I "%~1"=="redis"         goto :sr
if /I "%~1"=="nacos"         goto :snacos
if /I "%~1"=="mongodb"       goto :smongo
if /I "%~1"=="elasticsearch" goto :ses
if /I "%~1"=="rabbitmq"      goto :srabbitmq
if /I "%~1"=="minio"         goto :sminio
echo [ERROR] unknown target "%~1"   (mysql8 / mysql57 / redis / nacos / mongodb / elasticsearch / rabbitmq / minio / all / full)
exit /b 1

:sm8
call :isup 3308
if not errorlevel 1 (echo [SKIP] MySQL 8.0 already listening on 3308 & exit /b 0)
if not exist "%H8%\bin\mysqld.exe" (echo [SKIP] MySQL 8.0 not extracted yet & exit /b 1)
echo [START] MySQL 8.0 ...
REM The trailing ">nul 2>&1" is NOT cosmetic -- see the note in :sr below.
start "jw-mysql8" /min /D "%H8%\bin" mysqld.exe --defaults-file="%CONF%\mysql8.ini" >nul 2>&1
exit /b 0

:sm57
call :isup 3307
if not errorlevel 1 (echo [SKIP] MySQL 5.7 already listening on 3307 & exit /b 0)
if not exist "%H57%\bin\mysqld.exe" (echo [SKIP] MySQL 5.7 not extracted yet & exit /b 1)
echo [START] MySQL 5.7 ...
start "jw-mysql57" /min /D "%H57%\bin" mysqld.exe --defaults-file="%CONF%\mysql57.ini" >nul 2>&1
exit /b 0

:sr
call :isup 6380
if not errorlevel 1 (echo [SKIP] Redis already listening on 6380 & exit /b 0)
if not exist "%HR%\redis-server.exe" (echo [SKIP] Redis not extracted yet & exit /b 1)
echo [START] Redis ...
REM ---------------------------------------------------------------------------
REM  IMPORTANT: pass a WORKING DIRECTORY plus a BARE RELATIVE FILENAME here.
REM  Do NOT pass an absolute config path.
REM
REM  The msys2 build of redis-windows mangles absolute paths given on the
REM  command line: it ignores the drive letter and prepends the current working
REM  directory, so it fails with
REM      can't open config file '/.runtime/redis/D:\...\redis.conf': No such file
REM  Backslash, forward-slash and /d/ forms were all tried -- all of them fail.
REM
REM  Absolute paths INSIDE the config file are fine (dir / logfile resolve
REM  correctly), so the only thing to work around is argv. Setting the working
REM  directory to the conf folder and passing a bare filename does exactly that.
REM  This is also what the shipped start.bat does.
REM
REM  Keep every comment in this file ASCII-only. cmd reads .cmd files using the
REM  OEM codepage (GBK on a Chinese Windows) while this file is UTF-8, so any
REM  non-ASCII byte becomes mojibake -- and mojibake on a REM line can leak out
REM  and get executed as a command. Already burned by this once.
REM
REM  The trailing ">nul 2>&1" just keeps cmd's chatter down. It does NOT solve
REM  handle inheritance -- see the long note at the top of svc.sh. Measured:
REM  start creates the child with bInheritHandles=TRUE, so a piped caller
REM  (e.g. svc.sh init piped into tail) leaves the daemon holding the pipe
REM  write end; the reader then waits forever and the command looks hung --
REM  even though every service actually came up fine.
REM  The pipe-safe path lives in svc.sh: it hands cmd a FILE, not a pipe.
REM  mysqld/redis both log to files, so nothing useful is lost either way.
REM ---------------------------------------------------------------------------
start "jw-redis" /min /D "%CONF%" "%HR%\redis-server.exe" redis.conf >nul 2>&1
exit /b 0

:snacos
call :isup 8848
if not errorlevel 1 (echo [SKIP] Nacos already listening on 8848 & exit /b 0)
if not exist "%NACOS%\target\nacos-server.jar" (
  echo [SKIP] Nacos not extracted under %NACOS%
  exit /b 1
)
if not exist "%WS%\run-nacos.cmd" (
  echo [FAIL] %WS%\run-nacos.cmd is missing
  exit /b 1
)
if not exist "%NACOS_JDK%\bin\java.exe" (
  echo [FAIL] Nacos 3.x needs JDK 17+ but no java.exe under "%NACOS_JDK%"
  echo        Override with:  set NACOS_JDK=D:\path\to\jdk17
  exit /b 1
)
echo [START] Nacos 3.0.3 standalone (JDK 17) ...
REM The actual java invocation lives in run-nacos.cmd. Reasons it is not inlined:
REM   - it needs its own stdout redirect to a file, which does not work reliably
REM     when placed on a `start` line (see the header of run-nacos.cmd)
REM   - keeping one definition means `run-nacos.cmd` can also be run directly in
REM     the foreground when Nacos refuses to start and a live stack trace matters
REM
REM Nacos takes ~30s to come up (it is a Spring Boot 3.4 app). Check with
REM   svc.cmd status           (8848 = client API)
REM   svc.cmd logs nacos       (tail %LOGDIR%\nacos-console.log)
start "jw-nacos" /min /D "%NACOS%" cmd /c "%WS%\run-nacos.cmd" >nul 2>&1
exit /b 0

:smongo
call :isup 27017
if not errorlevel 1 (echo [SKIP] MongoDB already listening on 27017 & exit /b 0)
if not exist "%HM%\bin\mongod.exe" (echo [SKIP] MongoDB not extracted under %HM% & exit /b 1)
if not exist "%DM%" mkdir "%DM%"
echo [START] MongoDB 7.0.14 ...
REM Config lives in %CONF%\mongod.yml -- see the header of that file for why
REM authentication is deliberately OFF (mall-swarm's config carries no
REM credentials for MongoDB) and why bindIp keeps it on loopback only.
REM mongod writes its own log file (systemLog.path), so stdout is discarded.
start "jw-mongodb" /min /D "%HM%\bin" mongod.exe --config "%CONF%\mongod.yml" >nul 2>&1
exit /b 0

:ses
call :isup 9200
if not errorlevel 1 (echo [SKIP] Elasticsearch already listening on 9200 & exit /b 0)
if not exist "%HE%\bin\elasticsearch.bat" (echo [SKIP] Elasticsearch not extracted under %HE% & exit /b 1)
echo [START] Elasticsearch 8.18.8 ...
REM Elasticsearch ships its own bundled JDK, so the shell's JAVA_HOME is
REM irrelevant here -- that is why this one does not need a pinned JDK the way
REM Nacos does.
REM
REM ES 8.x enables security (HTTPS + auth) by default, but mall-swarm talks to
REM a bare http://localhost:9200 with no credentials. config\elasticsearch.yml
REM therefore sets xpack.security.enabled=false. See that file for the details.
REM
REM It is slow to start: expect 30-60s, and the first run does some extra work.
REM
REM No stdout redirect here on purpose. Nesting a quoted log path inside
REM `cmd /c "..."` breaks cmd's quote handling, and putting the redirect on the
REM `start` line does not reliably reach the child anyway (see :sr). ES writes a
REM proper log of its own, so `svc.cmd logs elasticsearch` tails that instead.
start "jw-elasticsearch" /min /D "%HE%\bin" cmd /c "elasticsearch.bat" >nul 2>&1
exit /b 0

:srabbitmq
call :isup 5672
if not errorlevel 1 (echo [SKIP] RabbitMQ already listening on 5672 & exit /b 0)
if not exist "%ERL%\bin\erl.exe" (
  echo [SKIP] Erlang not extracted under %ERL%
  echo        RabbitMQ on Windows cannot run without Erlang/OTP.
  exit /b 1
)
if not exist "%HRMQ%\sbin\rabbitmq-server.bat" (
  echo [SKIP] RabbitMQ not extracted under %HRMQ%
  exit /b 1
)
if not exist "%WS%\run-rabbitmq.cmd" (
  echo [FAIL] %WS%\run-rabbitmq.cmd is missing
  exit /b 1
)
echo [START] RabbitMQ 4.3.6 (Erlang/OTP 28) ...
REM Same reason as Nacos: the launch needs its own stdout redirect to a file,
REM which does not work reliably when placed on a `start` line. run-rabbitmq.cmd
REM also pins ERLANG_HOME and RABBITMQ_BASE so the broker stays inside .runtime.
REM
REM It comes up in about 4 seconds (much faster than Nacos) and logs to
REM   %DRMQ%\log\rabbit@localhost.log      (broker's own log)
REM   %LOGDIR%\rabbitmq-console.log        (captured console output)
REM
REM The management UI is at http://127.0.0.1:15672/  -- user mall / mall.
REM
REM DO NOT add a variable named LOGS above this line. See the file header.
start "jw-rabbitmq" /min /D "%WS%" cmd /c "%WS%\run-rabbitmq.cmd" >nul 2>&1
exit /b 0

:sminio
call :isup 9000
if not errorlevel 1 (echo [SKIP] MinIO already listening on 9000 & exit /b 0)
if not exist "%HMINIO%\minio.exe" (
  echo [SKIP] MinIO not extracted under %HMINIO%
  exit /b 1
)
if not exist "%WS%\run-minio.cmd" (
  echo [FAIL] %WS%\run-minio.cmd is missing
  exit /b 1
)
echo [START] MinIO RELEASE.2025-07-23 ...
REM Same reason as the other wrappers: the console redirect has to live on the
REM real command line, not on a `start` line. run-minio.cmd also pins the root
REM credentials (minioadmin/minioadmin) that mall-admin's config expects, and
REM pins the console port so it does not change on every restart.
REM
REM Comes up in about 4 seconds.
REM   API     : http://127.0.0.1:9000     bucket "mall", public read
REM   Console : http://127.0.0.1:9001     minioadmin / minioadmin
REM   Log     : %LOGDIR%\minio-console.log
start "jw-minio" /min /D "%WS%" cmd /c "%WS%\run-minio.cmd" >nul 2>&1
exit /b 0

:stopone
if /I "%~1"=="mysql8"        goto :tm8
if /I "%~1"=="mysql57"       goto :tm57
if /I "%~1"=="redis"         goto :tr
if /I "%~1"=="nacos"         goto :tnacos
if /I "%~1"=="mongodb"       goto :tmongo
if /I "%~1"=="elasticsearch" goto :tes
if /I "%~1"=="rabbitmq"      goto :trabbitmq
if /I "%~1"=="minio"         goto :tminio
echo [ERROR] unknown target "%~1"
exit /b 1

:tm8
call :isup 3308
if errorlevel 1 (echo [SKIP] MySQL 8.0 is not running & exit /b 0)
echo [STOP] MySQL 8.0 ...
"%H8%\bin\mysqladmin.exe" --defaults-file="%CONF%\mysql8.ini" -uroot -p%PW% shutdown 2>nul
if errorlevel 1 (
  REM Root may still have an empty password -- true right after
  REM --initialize-insecure, or after an init that aborted before the password
  REM step. Retry without a password before declaring failure.
  "%H8%\bin\mysqladmin.exe" --defaults-file="%CONF%\mysql8.ini" -uroot shutdown 2>nul
)
if errorlevel 1 echo [WARN] graceful shutdown failed -- mysqld.exe may need to be killed manually
exit /b 0

:tm57
call :isup 3307
if errorlevel 1 (echo [SKIP] MySQL 5.7 is not running & exit /b 0)
echo [STOP] MySQL 5.7 ...
"%H57%\bin\mysqladmin.exe" --defaults-file="%CONF%\mysql57.ini" -uroot -p%PW% shutdown 2>nul
if errorlevel 1 (
  REM Same fallback as above.
  "%H57%\bin\mysqladmin.exe" --defaults-file="%CONF%\mysql57.ini" -uroot shutdown 2>nul
)
if errorlevel 1 echo [WARN] graceful shutdown failed -- mysqld.exe may need to be killed manually
exit /b 0

:tr
call :isup 6380
if errorlevel 1 (echo [SKIP] Redis is not running & exit /b 0)
echo [STOP] Redis ...
"%HR%\redis-cli.exe" -h 127.0.0.1 -p 6380 shutdown nosave 2>nul
exit /b 0

:tnacos
call :isup 8848
if errorlevel 1 (echo [SKIP] Nacos is not running & exit /b 0)
echo [STOP] Nacos ...
REM Prefer the vendor's shutdown.cmd: it locates the JVM with `jps -m` (matching
REM the "nacos.nacos" program arg we pass) and taskkills it. It needs jps.exe, so
REM JAVA_HOME has to point at a JDK for the duration of the call.
REM
REM Note it is a hard taskkill, not a graceful shutdown -- that is the vendor's
REM own behaviour, and standalone Nacos keeps its state in conf/ + an embedded
REM store, so it survives. Save the local copy of JAVA_HOME and put it back so a
REM later step in the same invocation (e.g. `restart`) is unaffected.
set "_SAVEDJH=%JAVA_HOME%"
set "JAVA_HOME=%NACOS_JDK%"
if exist "%NACOS%\bin\shutdown.cmd" (
  call "%NACOS%\bin\shutdown.cmd"
) else (
  echo [WARN] %NACOS%\bin\shutdown.cmd missing
)
set "JAVA_HOME=%_SAVEDJH%"

REM Fallback: if shutdown.cmd could not find the process (e.g. it was started by
REM a different user session), kill whatever still holds 8848.
call :isup 8848
if not errorlevel 1 (
  echo [WARN] 8848 still listening -- falling back to a PID kill
  for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":8848 .*LISTENING"') do taskkill /F /PID %%p >nul 2>&1
)
exit /b 0

:tmongo
call :isup 27017
if errorlevel 1 (echo [SKIP] MongoDB is not running & exit /b 0)
echo [STOP] MongoDB ...
REM mongod has no shutdown command in the community Windows build, and there is
REM no `mongosh` in the 7.0 zip to call db.shutdownServer(). So this is a PID
REM kill. It is safe: mongod uses a journaled WiredTiger store, so it recovers
REM cleanly on the next start rather than corrupting.
REM
REM Find the PID via the port rather than by image name -- the workspace may
REM have other mongod processes, and killing those would be wrong.
set "_MPID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":27017 .*LISTENING"') do if not defined _MPID set "_MPID=%%p"
if defined _MPID (
  taskkill /F /PID !_MPID! >nul 2>&1
  if errorlevel 1 (echo [WARN] taskkill failed for PID !_MPID!) else (echo [OK] MongoDB stopped (PID !_MPID!))
) else (
  echo [WARN] could not determine the PID holding 27017
)
exit /b 0

:tes
call :isup 9200
if errorlevel 1 (echo [SKIP] Elasticsearch is not running & exit /b 0)
echo [STOP] Elasticsearch ...
REM ES exposes no local shutdown endpoint (the /_shutdown API was removed in
REM 8.x). So: PID kill on whatever holds 9200. ES is a search index here, not a
REM system of record -- worst case it is re-indexed.
set "_EPID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":9200 .*LISTENING"') do if not defined _EPID set "_EPID=%%p"
if defined _EPID (
  taskkill /F /PID !_EPID! >nul 2>&1
  if errorlevel 1 (echo [WARN] taskkill failed for PID !_EPID!) else (echo [OK] Elasticsearch stopped (PID !_EPID!))
) else (
  echo [WARN] could not determine the PID holding 9200
)
exit /b 0

:trabbitmq
call :isup 5672
if errorlevel 1 (echo [SKIP] RabbitMQ is not running & exit /b 0)
echo [STOP] RabbitMQ ...
REM Unlike MongoDB/Elasticsearch, RabbitMQ DOES have a graceful shutdown:
REM rabbitmqctl stop halts the node and lets mnesia flush cleanly. Go through
REM run-rabbitmq.cmd so ERLANG_HOME and RABBITMQ_BASE are set the same way they
REM were at startup -- rabbitmqctl needs both to find the node.
REM
REM rabbitmqctl can take ~10s (it waits for the node to halt), so this is not
REM instant even though it returns synchronously.
if not exist "%WS%\run-rabbitmq.cmd" (
  echo [WARN] %WS%\run-rabbitmq.cmd is missing -- falling back to a PID kill
) else (
  call "%WS%\run-rabbitmq.cmd" ctl stop >nul 2>&1
)
REM Fallback: if the graceful stop did not take (wrong node name, stale cookie,
REM or an epmd mismatch), kill whatever still holds 5672.
call :isup 5672
if not errorlevel 1 (
  echo [WARN] 5672 still listening -- falling back to a PID kill
  set "_RPID="
  for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":5672 .*LISTENING"') do if not defined _RPID set "_RPID=%%p"
  if defined _RPID taskkill /F /PID !_RPID! >nul 2>&1
) else (
  echo [OK] RabbitMQ stopped gracefully
)
exit /b 0

:tminio
call :isup 9000
if errorlevel 1 (echo [SKIP] MinIO is not running & exit /b 0)
echo [STOP] MinIO ...
REM MinIO DOES have a graceful stop: `mc admin service stop <alias>`. Use it --
REM a hard kill mid-write can leave incomplete multipart uploads behind.
REM The alias "jw" lives in the workspace-local mc config dir, which is why
REM --config-dir is passed explicitly (mc would otherwise look in %HOME%\.mc).
if exist "%HMINIO%\mc.exe" (
  "%HMINIO%\mc.exe" --config-dir "%DMINIO%\mc" admin service stop jw >nul 2>&1
)
REM Fallback: if the graceful stop did not take (alias missing, credentials
REM changed), kill whatever still holds 9000.
call :isup 9000
if not errorlevel 1 (
  echo [WARN] 9000 still listening -- falling back to a PID kill
  set "_NPID="
  for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":9000 .*LISTENING"') do if not defined _NPID set "_NPID=%%p"
  if defined _NPID taskkill /F /PID !_NPID! >nul 2>&1
) else (
  echo [OK] MinIO stopped gracefully
)
exit /b 0


REM ===========================================================================
REM  status / cli / logs
REM ===========================================================================
:act_status
echo.
echo   SERVICE          PORT    STATUS       DATA DIR
echo   --------------------------------------------------------------------------
REM Names are space-padded to a common width so the columns line up -- cmd's
REM echo has no printf-style padding. Trailing spaces inside the quotes survive.
call :showstatus "MySQL 8.0    " 3308 "%D8%"
call :showstatus "MySQL 5.7    " 3307 "%D57%"
call :showstatus "Redis        " 6380 "%DR%"
call :showstatus "Nacos        " 8848 "%NACOS%"
call :showstatus "MongoDB      " 27017 "%DM%"
call :showstatus "Elasticsearch" 9200 "%DE%"
call :showstatus "RabbitMQ     " 5672 "%DRMQ%"
call :showstatus "MinIO        " 9000 "%DMINIO%"
echo.
echo   Nacos console:  http://127.0.0.1:8849/    (root path -- NOT 8848/nacos)
echo                   user nacos / Workspace#2026  (admin pw already initialised)
echo   RabbitMQ mgmt:  http://127.0.0.1:15672/   user mall / mall
echo                   vhost /mall   (NOT /)
echo   MinIO console:  http://127.0.0.1:9001/    user minioadmin / minioadmin
echo                   bucket "mall" (public read)
echo.
echo   Connect with:
echo     svc.cmd cli mysql8 / mysql57 / redis / mongodb
echo     "%H8%\bin\mysql.exe"  --defaults-file="%CONF%\mysql8.ini"  -uroot -p%PW%
echo     "%H57%\bin\mysql.exe" --defaults-file="%CONF%\mysql57.ini" -uroot -p%PW%
echo     "%HR%\redis-cli.exe" -h 127.0.0.1 -p 6380
echo     "%HM%\bin\mongosh.exe" mongodb://127.0.0.1:27017
echo     run-rabbitmq.cmd ctl status        (rabbitmqctl, env already set up)
echo     "%HMINIO%\mc.exe" --config-dir "%DMINIO%\mc" ls jw
echo.
exit /b 0

:showstatus
set "SVCNAME=%~1"
set "SVCPORT=%~2"
set "SVCDIR=%~3"
call :isup %SVCPORT%
if errorlevel 1 (set "ST=stopped  ") else (set "ST=LISTENING")
echo   %SVCNAME%   %SVCPORT%   !ST!   %SVCDIR%
exit /b 0

:act_cli
REM Same MYSQL_PWD trick as in init: avoids the "password on the command line"
REM warning before the prompt. Scoped to this process.
set "MYSQL_PWD=%PW%"
if /I "%TARGET%"=="mysql8" (
  "%H8%\bin\mysql.exe" --defaults-file="%CONF%\mysql8.ini" -uroot --default-character-set=utf8mb4
  exit /b 0
)
if /I "%TARGET%"=="mysql57" (
  "%H57%\bin\mysql.exe" --defaults-file="%CONF%\mysql57.ini" -uroot --default-character-set=utf8mb4
  exit /b 0
)
if /I "%TARGET%"=="redis" (
  "%HR%\redis-cli.exe" -h 127.0.0.1 -p 6380
  exit /b 0
)
if /I "%TARGET%"=="mongodb" (
  if not exist "%HM%\bin\mongosh.exe" (
    echo [ERROR] mongosh not found at "%HM%\bin\mongosh.exe"
    echo         The MongoDB 7.0 Windows zip does NOT bundle mongosh -- it is a
    echo         separate download from https://www.mongodb.com/try/download/shell
    echo         Everything else works without it; only this interactive shell needs it.
    exit /b 1
  )
  "%HM%\bin\mongosh.exe" "mongodb://127.0.0.1:27017"
  exit /b 0
)
echo [ERROR] cli needs a target: mysql8 / mysql57 / redis / mongodb
exit /b 1

:act_logs
set "LF="
if /I "%TARGET%"=="mysql8"        set "LF=%LOGDIR%\mysql8-error.log"
if /I "%TARGET%"=="mysql57"       set "LF=%LOGDIR%\mysql57-error.log"
if /I "%TARGET%"=="redis"         set "LF=%LOGDIR%\redis.log"
if /I "%TARGET%"=="nacos"         set "LF=%LOGDIR%\nacos-console.log"
if /I "%TARGET%"=="mongodb"       set "LF=%LOGDIR%\mongodb.log"
if /I "%TARGET%"=="elasticsearch" set "LF=%HE%\logs\elasticsearch.log"
if /I "%TARGET%"=="rabbitmq"      set "LF=%LOGDIR%\rabbitmq-console.log"
if /I "%TARGET%"=="minio"         set "LF=%LOGDIR%\minio-console.log"
if "%LF%"=="" (echo [ERROR] logs needs a target: mysql8 / mysql57 / redis / nacos / mongodb / elasticsearch / rabbitmq / minio & exit /b 1)
if not exist "%LF%" (echo [ERROR] no log file at %LF% & exit /b 1)
powershell -NoProfile -Command "Get-Content -LiteralPath '%LF%' -Tail 60 -Wait"
exit /b 0


REM ===========================================================================
REM  helpers
REM ===========================================================================

REM isup <port>  -- errorlevel 0 if something is LISTENING on that port
:isup
netstat -ano | findstr /R /C:":%~1 .*LISTENING" >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0

REM waitport <port> <max_seconds>
:waitport
set /a "_n=0"
:wp_loop
call :isup %~1
if not errorlevel 1 exit /b 0
set /a "_n+=1"
if !_n! GEQ %~2 (
  echo [FAIL] port %~1 still not listening after %~2s
  exit /b 1
)
call :sleepps 1
goto :wp_loop

REM sleepps <seconds>  -- portable sleep (timeout.exe breaks when stdin is redirected)
:sleepps
ping -n %~1 127.0.0.1 >nul 2>&1
exit /b 0

REM initone <home> <ini> <datadir> <label>
:initone
set "IH=%~1"
set "II=%~2"
set "ID=%~3"
set "IL=%~4"
if not exist "%IH%\bin\mysqld.exe" (
  echo [SKIP] %IL% : mysqld.exe not found under %IH%
  echo        -- extract the zip first.
  exit /b 1
)
if exist "%ID%\mysql" (
  echo [SKIP] %IL% : data directory already initialized
  exit /b 0
)
if not exist "%ID%" mkdir "%ID%"
echo [INIT] %IL% : creating data directory ...
"%IH%\bin\mysqld.exe" --defaults-file="%II%" --initialize-insecure --console
if errorlevel 1 (
  echo [FAIL] %IL% : initialization failed
  exit /b 1
)
echo [OK] %IL% : initialized (root currently has an empty password)
exit /b 0

REM setrootpw <home> <ini> <label>
:setrootpw
set "SH=%~1"
set "SI=%~2"
set "SL=%~3"
REM Only succeeds while root still has an empty password. If it was already set,
REM this fails -- which is fine, hence the ignored exit code.
"%SH%\bin\mysql.exe" --defaults-file="%SI%" -uroot -e "ALTER USER 'root'@'localhost' IDENTIFIED BY '%PW%';" >nul 2>&1
if errorlevel 1 (
  echo [SKIP] %SL% : root password already set
) else (
  echo [OK] %SL% : root password set to %PW%
)
exit /b 0


:usage
echo.
echo  svc.cmd -- portable MySQL / Redis / Nacos / MongoDB / Elasticsearch /
echo             RabbitMQ / MinIO manager
echo             (nothing installed system-wide, no Windows service, no PATH edit)
echo.
echo    svc.cmd init              one-time bootstrap
echo    svc.cmd start  [t]        start  mysql8 ^| mysql57 ^| redis ^| nacos ^| mongodb
echo                                     ^| elasticsearch ^| rabbitmq ^| minio ^| all ^| full
echo    svc.cmd stop   [t]        graceful shutdown
echo    svc.cmd restart [t]
echo    svc.cmd status            show listening state
echo    svc.cmd cli    ^<t^>        open a client (mysql8 / mysql57 / redis / mongodb)
echo    svc.cmd logs   ^<t^>        tail the log (mysql8 / mysql57 / redis / nacos /
echo                                     mongodb / elasticsearch / rabbitmq / minio)
echo.
echo    all  = mysql8 + mysql57 + redis          (P0/P1 -- fast)
echo    full = all + nacos + mongodb + elasticsearch + rabbitmq + minio
echo                                             (P2 -- slow, opt-in)
echo.
echo    Ports:     MySQL 8.0 = 3308   MySQL 5.7 = 3307   Redis = 6380
echo               Nacos client = 8848   Nacos console = 8849
echo               MongoDB = 27017   Elasticsearch = 9200
echo               RabbitMQ AMQP = 5672   mgmt = 15672   epmd = 4369
echo               MinIO API = 9000   MinIO console = 9001
echo    Accounts:  root/123456        dev/dev123456
echo               Nacos console: nacos/Workspace#2026
echo               RabbitMQ: mall/mall   vhost /mall
echo               MinIO: minioadmin/minioadmin   bucket mall
echo.
echo    Extra tools:
echo      run-rabbitmq.cmd ctl status      rabbitmqctl (env set up for you)
echo      run-rabbitmq.cmd plugins list
echo      "%HMINIO%\mc.exe" --config-dir "%DMINIO%\mc" ls jw
echo.
exit /b 0
