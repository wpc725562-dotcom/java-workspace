#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py —— java-workspace 项目工作台（零依赖本地服务）

只做三件事：
  ① 把 dashboard/web/ 下的静态页面托管出去
  ② 读 projects.json，把每个项目的**实时状态**（端口在不在听）算出来给前端
  ③ 提供 start / stop / log 接口，真的能把项目拉起来

为什么用标准库 http.server 而不是 Flask/FastAPI：
  这个工作台的整个卖点是「删掉目录就等于没来过」。一旦引入第三方依赖，
  就得先 pip install，回滚也不再干净。标准库够用 —— 并发量是 1。

------------------------------------------------------------------------------
设计上的几个关键决定
------------------------------------------------------------------------------

【1】启动命令走 bash + source use-jdk.sh，不自己拼环境变量
    工作区里 use-jdk.sh 干的不只是切 JAVA_HOME，它还：
      · unset SERVER__PORT / SERVER__HOST  —— WorkBuddy 会往每个子进程注入这两个变量，
        Spring Boot 的松散绑定会把 SERVER__PORT 当成 server.port，应用会去抢宿主端口
        然后 PortInUseException 死掉。症状极其误导（yml 里写着 8090，日志里是 22404）。
      · 给 JDK 8 / 17 设 JAVA_TOOL_OPTIONS 修编码（中文 Windows 下默认 GBK，
        日志和异常堆栈会变成乱码，而且**不报错**）
    这些逻辑如果在这里重写一遍，两边就会漂移。所以直接复用：
        bash -c 'source use-jdk.sh 17 && cd <cwd> && exec java -jar <jar> <args>'

【2】启动是异步的，接口立刻返回
    起一个 Spring 应用要 20–120 秒。如果 POST /start 同步等到就绪，
    浏览器会以为页面卡死。所以开后台线程干活，前端轮询 /api/projects 看进度。

【3】状态以「端口在不在听」为准，不以「我们有没有拉起过」为准
    你完全可能在另一个终端里手工起了一个项目。这时工作台也该显示「运行中」，
    也该能把它停掉。所以 stop 会先看自己记录的 PID，没有就按端口反查 PID。

【4】子进程用 DETACHED_PROCESS 起，日志落文件
    工作台自己是可以随时关掉的，不该把应用一起带走。
    日志落到 logs/ 下（该目录已在 .gitignore 里），前端可以 tail 出来看。

用法：
    python dashboard/server.py                 # 默认 8990
    python dashboard/server.py --port 8991
    python dashboard/server.py --no-browser    # 不自动开浏览器
"""

import argparse
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent            # dashboard/
WS = HERE.parent                                   # D:\java-workspace
WEB = HERE / "web"
CONFIG = HERE / "projects.json"
LOGDIR = WS / "logs"

IS_WINDOWS = os.name == "nt"

# Windows 进程创建标志
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

# 从子进程环境里必须清掉的东西（use-jdk.sh 也会清，这里是双保险）
POISON_ENV = ("SERVER__PORT", "SERVER__HOST", "SERVER_PORT")


# ---------------------------------------------------------------------------
# ★ 先把标准输出的编码钉死，否则 print() 会炸
# ---------------------------------------------------------------------------
# 中文 Windows 上，stdout 一旦被重定向到文件，Python 用的就是 locale 编码（GBK），
# 不是 UTF-8。于是任何 GBK 表达不了的字符都会让 print() 抛 UnicodeEncodeError：
#
#     UnicodeEncodeError: 'gbk' codec can't encode character '\u274c'
#
# 实测踩到过两次，而且**两次都崩在异常处理里面**：
#   start_middleware 打印子进程输出时炸 → job_start 的 except 想补一条
#   「❌ 启动失败：…」又炸 → 线程静默死亡 → 前端永远停在「启动中」，日志里
#   只剩一段 traceback，看不出是哪一步失败的。
#
# 触发它的字符有两类，都很容易碰到：
#   ① 日志文案里的 ❌ ✗ 这类符号；
#   ② U+FFFD —— 把 GBK 字节按 UTF-8 解码时会成片产生，而它同样编不进 GBK。
#      也就是说「解码选错了编码」最后表现为「打印崩溃」，因果隔了一层，
#      排查时很容易往错误的方向找。
#
# 所以两个方向都要钉死：读子进程一律走 decode_console()，
# 写出统一 UTF-8 + errors="replace"。
def _force_utf8_stdio():
    """把 stdout/stderr 切成 UTF-8 + errors='replace'，让 print() 永不因编码抛异常。

    顺带打开 line_buffering。这不是性能调优，是正确性：stdout 一旦被重定向到
    文件（start.cmd 就是这么干的），Python 默认按 8KB 块缓冲，于是启动 banner
    会一直卡在缓冲区里 —— `tail` 看不到任何东西，而进程被 taskkill 杀掉时那块
    缓冲直接丢掉，日志里连「它到底起没起来」都查不到。实测踩到过：端口已经在
    监听了，日志还是 0 字节。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError, OSError):
            pass  # 流被换成了非文本对象（例如 pythonw 下 stdout 是 None）—— 跳过


_force_utf8_stdio()


def decode_console(raw: bytes) -> str:
    """解码 Windows 控制台程序（svc.cmd / bash / netstat）的输出。

    不能一律按 UTF-8 解：中文 Windows 上 cmd 系的输出是 GBK/CP936 字节，
    按 UTF-8 解会得到满屏 U+FFFD，中文全丢 —— 而且这些 U+FFFD 还会把后面的
    print 一起炸掉（见上面那段注释）。

    也不能一律按 GBK 解：工作区里不少脚本自己设了 UTF-8（JAVA_TOOL_OPTIONS
    那一套），它们的输出是合法 UTF-8，按 GBK 解会变成乱码。

    所以：先严格试 UTF-8，失败再严格试 GBK，都失败才 replace。
    纯 ASCII 时两种都能解且结果相同，顺序无影响。
    """
    if not raw:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def log(*a):
    print("[dashboard]", *a, flush=True)


def now_iso():
    return datetime.now().strftime("%H:%M:%S")


def win2unix(p: str) -> str:
    """D:\\java-workspace\\x  ->  /d/java-workspace/x  （给 bash 用）"""
    p = str(p).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/" + p[0].lower() + p[2:]
    return p


def _is_wsl_bash(path) -> bool:
    """判断一个 bash.exe 是 WSL 的启动器，而不是 Git Bash。

    ★ 为什么必须把它排掉 —— 这是整个工作台里最阴的一个坑：

      Windows 在 System32 里放了一个 bash.exe，那不是 bash，是 WSL 的启动器；
      真正的 Linux bash 跑在一个 Hyper-V 虚拟机里。而工作区的脚本是**给 Git Bash
      写的**（用 cygpath、用 /d/ 这种盘符路径），交给 WSL 只有两个结果：

        · 报 HCS_E_HYPERV_NOT_INSTALLED（没开 Hyper-V 时就是这句），而且
        · WSL 的输出是 UTF-16，按单字节读出来是一片
          「B a s h / S e r v i c e / C r e a t e I n s t a n c e /...」的乱码，
          看不出到底是谁在报错、在报什么错。

      它只在**从普通 Windows 命令行启动**时才踩得到：

        · 从 WorkBuddy 的 bash 里启动 → PATH 上第一个 bash 就是 Git Bash → 正常
        · 双击 dashboard\\start.cmd 启动 → PATH 上没有 Git Bash 时，
          shutil.which("bash") 就命中 System32 里那个 WSL 启动器 → 全线失败

      也就是说：开发时怎么试都是好的，用户一用就坏。实测踩到过 ——
      从 bash 启动时 P0/P4 都能起来，从 start.cmd 启动时连 MySQL 都拉不起来。
    """
    if not path:
        return False
    p = os.path.normcase(os.path.abspath(path))
    win = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    # System32\bash.exe（WSL 启动器）以及 WindowsApps 里那个别名
    return p.startswith(win + os.sep) or "windowsapps" in p


def find_bash() -> str:
    cands = [
        shutil.which("bash"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Git\bin\bash.exe"),
    ]
    for c in cands:
        if c and os.path.isfile(c) and not _is_wsl_bash(c):
            return c
    raise RuntimeError(
        "找不到可用的 Git Bash —— 工作区的脚本都是 bash 写的，必须先装 Git for Windows。"
        "（注意 C:\\Windows\\System32\\bash.exe 是 WSL 的启动器，不是 Git Bash，"
        "工作台的脚本不能用它跑）"
    )


# ---------------------------------------------------------------------------
# 端口探测
# ---------------------------------------------------------------------------
def netstat_listeners() -> dict:
    """一次 netstat 拿到所有本机监听端口 -> PID。比逐个 socket 连接快得多。"""
    try:
        raw = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=20).stdout
    except Exception:
        return {}
    for enc in ("gbk", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")

    out = {}
    for line in text.splitlines():
        parts = line.split()
        # TCP  0.0.0.0:8000  0.0.0.0:0  LISTENING  12345
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[-2].upper() == "LISTENING":
            local = parts[1]
            port = local.rsplit(":", 1)[-1]
            if port.isdigit():
                pid = parts[-1]
                out[int(port)] = int(pid) if pid.isdigit() else None
    return out


def port_open(port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


# --- 进程名核验 -------------------------------------------------------------
# ★ 为什么必须有这一步：
#   「端口在听」不等于「我们要的服务起来了」。
#   实测踩到过：5672（RabbitMQ 的端口）被 **WorkBuddyAI.exe 自己**占着 ——
#   宿主客户端内部也用了这个端口。只看端口的话，工作台会理直气壮地显示
#   「RabbitMQ 运行中」，而实际上 RabbitMQ 一个字节都没跑起来。
#   所以这里再问一次 tasklist：监听这个端口的到底是哪个进程？
_PROC_CACHE = {"at": 0.0, "map": {}}


def process_names(pids) -> dict:
    """{pid: '进程名'}。带 5 秒缓存 —— tasklist 每次要几百毫秒。"""
    pids = [int(p) for p in pids if p]
    if not pids:
        return {}
    if time.time() - _PROC_CACHE["at"] < 5:
        cached = _PROC_CACHE["map"]
        if all(p in cached for p in pids):
            return {p: cached[p] for p in pids}
    out = {}
    for pid in pids:
        try:
            raw = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, timeout=15).stdout
            text = raw.decode("gbk", "replace")
            # 输出形如："WorkBuddyAI.exe","22276","Console","1","535,012 K"
            for line in text.splitlines():
                if line.startswith('"'):
                    parts = [x.strip('"') for x in line.split('","')]
                    if len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) == pid:
                        out[pid] = parts[0]
                        break
        except Exception:  # noqa: BLE001
            pass
    _PROC_CACHE["at"] = time.time()
    _PROC_CACHE["map"] = out
    return out


def check_owner(port, listeners, hints, names):
    """判断监听 port 的进程是不是我们期望的那个。

    返回 (状态, 进程名)。状态：ok / wrong-process / unknown / not-listening
    """
    if port not in listeners:
        return "not-listening", None
    pid = listeners.get(port)
    if not pid:
        return "unknown", None
    name = names.get(pid)
    if not name:
        return "unknown", None
    if not hints:
        return "ok", name
    low = name.lower()
    for h in hints:
        if h.lower() in low:
            return "ok", name
    return "wrong-process", name


def http_probe(url: str, timeout: float = 3.0):
    """返回 (状态码, 说明)。任何 HTTP 响应都算「HTTP 层活着」——
    401/403/404 都证明服务起来了，只有连不上才是不活。"""
    try:
        req = Request(url, headers={"User-Agent": "workspace-dashboard"})
        with urlopen(req, timeout=timeout) as r:
            return r.status, "ok"
    except HTTPError as e:
        return e.code, "http-error"
    except URLError as e:
        return None, str(e.reason)
    except Exception as e:  # noqa: BLE001
        return None, str(e)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
class Config:
    def __init__(self, path: Path):
        self.path = path
        self.raw = json.loads(path.read_text(encoding="utf-8"))
        self.projects = self.raw.get("projects", [])
        self.middleware = self.raw.get("middleware", [])
        self.categories = self.raw.get("categories", [])
        self.origins = self.raw.get("origins", [])
        self.dashboard = self.raw.get("dashboard", {})
        self._index = {p["id"]: p for p in self.projects}

    def project(self, pid):
        return self._index.get(pid)

    def middleware_by_id(self, mid):
        for m in self.middleware:
            if m["id"] == mid:
                return m
        return None

    def category_label(self, cid):
        for c in self.categories:
            if c["id"] == cid:
                return c["label"]
        return cid

    def origin(self, kind):
        for o in self.origins:
            if o["id"] == kind:
                return o
        return {"id": kind, "label": kind, "short": kind}


CFG: Config = None  # type: ignore


def reload_config() -> "Config":
    """重新读 projects.json。做成函数是为了把 `global CFG` 收在一处 ——
    散在 Handler 里会踩「name is used prior to global declaration」。"""
    global CFG
    CFG = Config(CONFIG)
    return CFG


# ---------------------------------------------------------------------------
# JDK 注册表：直接解析 use-jdk.sh，避免两处维护造成漂移
# ---------------------------------------------------------------------------
# 形如：  '17|Amazon Corretto 17 (系统已装)|C:\Program Files\...|/c/Program Files/...'
#
# ★ 每个字段都必须排除 \n 并锚到行尾。
#   最初写成 ([^|]*) 是错的：引号本身也属于 [^|]，贪婪匹配会越过行尾的 '
#   一路吃到下一行的引号，于是「17」那一行被前一条匹配整个吞掉，
#   结果只解析出 8 和 21 —— 表现为「JDK 17 莫名其妙不见了」。
_JDK_RE = re.compile(r"^\s*'(\d+)\|([^|\n]*)\|([^|\n]*)\|([^|\n]*)'\s*$", re.M)


def jdk_registry() -> dict:
    """{ '17': {'version':'17','name':...,'win':...,'unix':...,'exists':bool} }"""
    out = {}
    src = "use-jdk.sh"
    f = WS / "use-jdk.sh"
    if f.is_file():
        for m in _JDK_RE.finditer(f.read_text(encoding="utf-8", errors="replace")):
            ver, name, win, unix = m.group(1), m.group(2), m.group(3), m.group(4)
            out[ver] = {
                "version": ver, "name": name, "win": win, "unix": unix,
                "exists": os.path.isfile(os.path.join(win, "bin", "java.exe")),
            }
    else:
        src = "(找不到 use-jdk.sh)"
    return {"source": src, "jdks": out}


# ---------------------------------------------------------------------------
# 运行时状态
# ---------------------------------------------------------------------------
class Runtime:
    """每个项目一份。state 是工作台的判断，phase 是给用户看的进度文字。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}          # pid -> dict

    def get(self, pid):
        with self.lock:
            return dict(self.data.get(pid) or self._blank())

    def _blank(self):
        return {"state": "idle", "phase": "", "error": None, "jobLog": [],
                "trackedPid": None, "startedAt": None}

    def ensure(self, pid):
        with self.lock:
            if pid not in self.data:
                self.data[pid] = self._blank()
            return self.data[pid]

    def update(self, pid, **kw):
        with self.lock:
            self.data.setdefault(pid, self._blank()).update(kw)

    def say(self, pid, text):
        # pid=None 表示「这不是某个项目的任务日志」（比如从中间件面板直接点的启动），
        # 只打到服务端控制台，不往项目日志里塞。
        if pid is not None:
            with self.lock:
                d = self.data.setdefault(pid, self._blank())
                d["jobLog"].append({"t": now_iso(), "text": text})
                if len(d["jobLog"]) > 300:
                    del d["jobLog"][:-300]
        log(pid, text)

    def log_of(self, pid):
        with self.lock:
            return list((self.data.get(pid) or {}).get("jobLog", []))


RT = Runtime()


# ---------------------------------------------------------------------------
# 中间件
# ---------------------------------------------------------------------------
def middleware_status():
    listeners = netstat_listeners()
    names = process_names([listeners.get(m["port"]) for m in CFG.middleware])
    out = []
    for m in CFG.middleware:
        status, owner = check_owner(m["port"], listeners, m.get("processHint"), names)
        extra = {str(p): (p in listeners) for p in m.get("extraPorts", [])}
        out.append({
            "id": m["id"], "name": m["name"], "version": m.get("version", ""),
            "port": m["port"], "note": m.get("note", ""),
            # running 只认「进程名也对得上」的那种
            "running": status == "ok",
            "ownerStatus": status, "owner": owner,
            "pid": listeners.get(m["port"]),
            "extraPorts": extra,
            "managed": mw_manageable(m),
            "launcher": m.get("launcher"),
        })
    return out


def middleware_up(mid, listeners=None, names=None) -> bool:
    """这个中间件是不是真的起来了。

    listeners / names 可以从外部传进来复用，避免每个项目、每个中间件都跑一遍
    netstat + tasklist（一次页面刷新会跑十几次，慢到没法看）。

    语义：
      ok            -> 起来了
      unknown       -> 端口在听但认不出进程，保守地当作起来了（并让前端标注「未知」）
      wrong-process -> 端口被别的程序占着，**不算起来**（这正是 5672 踩到的坑）
      not-listening -> 没起来
    """
    m = CFG.middleware_by_id(mid)
    if not m:
        return False
    if listeners is None:
        listeners = netstat_listeners()
    if names is None:
        names = process_names([listeners.get(m["port"])])
    status, _ = check_owner(m["port"], listeners, m.get("processHint"), names)
    return status in ("ok", "unknown")


def spawn_cmd(bat: Path, logfile: Path):
    """把一个 .cmd 启动器 detached 地跑起来（Ollama 这类没有 svc.sh 集成的服务）。

    run-ollama.cmd 是**前台**启动器（它自己在注释里说明了为什么不用 `start`：
    重定向到不了子进程，日志会丢）。所以这里替它做分离 + 落日志。
    """
    LOGDIR.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in POISON_ENV}
    fh = open(logfile, "ab")
    fh.write(f"\n\n===== {datetime.now().isoformat(timespec='seconds')} 由工作台启动 =====\n".encode("utf-8"))
    fh.flush()
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
    try:
        p = subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(WS), env=env,
                             stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                             creationflags=flags, close_fds=True)
    finally:
        fh.close()
    return p.pid


def svc_run(args, timeout=240):
    """调 ./svc.sh（Git Bash 转发壳，真正实现在 svc.cmd 里）。"""
    bash = find_bash()
    p = subprocess.run([bash, "svc.sh"] + list(args), cwd=str(WS),
                       capture_output=True, timeout=timeout)
    # ★ 用 decode_console，不要写死 "utf-8"：svc.cmd 在中文 Windows 上吐的是
    #   GBK 字节，按 UTF-8 解会变成 U+FFFD —— 中文全丢，而且会让后面的 print 炸掉。
    out = decode_console(p.stdout or b"") + decode_console(p.stderr or b"")
    return p.returncode, out.strip()


def mw_manageable(m):
    """工作台能不能自己把这个中间件拉起来。"""
    return bool(m) and bool(m.get("svc") or m.get("launcher"))


def start_middleware(pid, m):
    """起一个中间件。返回 (ok, 说明文字)。"""
    if m.get("svc"):
        rc, out = svc_run(["start", m["svc"]])
        tail = [l.strip() for l in out.splitlines() if l.strip()][-4:]
        for line in tail:
            RT.say(pid, "  " + line)
        RT.say(pid, f"  svc.sh start {m['svc']} 退出码 {rc}")
        return rc == 0, f"svc.sh 退出码 {rc}"

    if m.get("launcher"):
        bat = WS / m["launcher"]
        if not bat.is_file():
            RT.say(pid, f"  ✗ 找不到启动器 {m['launcher']}")
            return False, f"找不到 {m['launcher']}"
        logfile = LOGDIR / f"dashboard-mw-{m['id']}.log"
        child = spawn_cmd(bat, logfile)
        RT.say(pid, f"  cmd /c {m['launcher']}  → PID {child}，日志 logs/{logfile.name}")
        return True, f"PID {child}"

    return False, "不在工作台管理范围内"


def ensure_middleware(pid, ids):
    """把缺的中间件起起来。返回「到最后还是没起来」的 id 列表。"""
    listeners = netstat_listeners()
    names = process_names([listeners.get((CFG.middleware_by_id(i) or {}).get("port")) for i in ids])
    need = [i for i in ids if not middleware_up(i, listeners, names)]
    if not need:
        RT.say(pid, f"中间件已就绪：{', '.join(ids) if ids else '（无）'}")
        return []

    names_txt = [CFG.middleware_by_id(i)["name"] for i in need if CFG.middleware_by_id(i)]
    RT.say(pid, f"缺少中间件，开始启动：{', '.join(names_txt)}")

    # ★ 一个服务一次调用，**不能**写成 `svc.sh start mysql57 redis`。
    #   svc.cmd 里是 `set "TARGET=%~2"` —— 只认第二个参数，后面的一律丢弃。
    #   踩过：传 `start mysql57 redis` 时只起了 mysql57，redis 被静默忽略，
    #   然后工作台老老实实等了 180 秒才报「Redis 没起来」。
    #   逐个调用还有个好处：svc.cmd 会等每个服务自己的端口就绪，
    #   返回时就带上了精确的成败信息，不用我们去猜。
    for i in need:
        m = CFG.middleware_by_id(i)
        if not m:
            continue
        if not mw_manageable(m):
            RT.say(pid, f"  ⚠ {m['name']} 工作台起不了 —— 请手动运行"
                        + (f" {m['launcher']}" if m.get("launcher") else "（工作区里没有它的启动器）"))
            continue
        RT.say(pid, f"  启动 {m['name']}…")
        start_middleware(pid, m)

    # 只等「工作台能管、而且还有希望起来」的那些。
    # ★ 这里必须把「端口被别的进程占着」的排除掉 —— 实测踩到：RabbitMQ 的 5672
    #   被 WorkBuddyAI.exe 占着，等多久都不会变成 RabbitMQ，却白等了整整 120 秒。
    ls0 = netstat_listeners()
    nm0 = process_names([ls0.get((CFG.middleware_by_id(i) or {}).get("port")) for i in ids])
    wait_ids = []
    for i in ids:
        m = CFG.middleware_by_id(i)
        if not mw_manageable(m):
            continue
        st, _ = check_owner(m["port"], ls0, m.get("processHint"), nm0)
        if st == "wrong-process":
            RT.say(pid, f"  ⏭ 不等 {m['name']} 了 —— 它的端口已经被别的进程占住，等也不会变")
            continue
        wait_ids.append(i)

    deadline = time.time() + 120
    while time.time() < deadline:
        ls = netstat_listeners()
        nm = process_names([ls.get((CFG.middleware_by_id(i) or {}).get("port")) for i in wait_ids])
        still = [i for i in wait_ids if not middleware_up(i, ls, nm)]
        if not still:
            RT.say(pid, "中间件全部就绪")
            return [i for i in ids if not middleware_up(
                i, ls, process_names([ls.get((CFG.middleware_by_id(i) or {}).get("port"))]))]
        time.sleep(3)

    ls = netstat_listeners()
    nm = process_names([ls.get((CFG.middleware_by_id(i) or {}).get("port")) for i in ids])
    still = [i for i in ids if not middleware_up(i, ls, nm)]
    # 说清楚为什么没起来 —— 「端口被别的进程占着」和「压根没起来」是两回事
    for i in still:
        m = CFG.middleware_by_id(i)
        if not m:
            continue
        st, owner = check_owner(m["port"], ls, m.get("processHint"), nm)
        if st == "wrong-process":
            RT.say(pid, f"  ⚠ {m['name']} 的端口 {m['port']} 被 {owner} 占着，"
                        f"不是 {m['name']} —— 需要先腾出这个端口")
    return still


# ---------------------------------------------------------------------------
# 启动 / 停止
# ---------------------------------------------------------------------------
def build_launch_command(proj):
    """返回 (bash 脚本, 日志文件路径, 说明)。"""
    L = proj["launch"]
    kind = L["type"]
    ws_u = win2unix(WS)

    if kind == "jar":
        jdk = L["jdk"]
        cwd_u = win2unix(WS / L["cwd"])
        jar_u = win2unix(WS / L["cwd"] / L["jar"])
        args = " ".join(shlex.quote(a) for a in L.get("args", []))
        script = (
            f'set -e\n'
            f'source "{ws_u}/use-jdk.sh" {shlex.quote(jdk)} >/dev/null 2>&1\n'
            f'echo "[launcher] JAVA_HOME=$JAVA_HOME"\n'
            f'cd "{cwd_u}"\n'
            f'echo "[launcher] pwd=$(pwd)"\n'
            f'echo "[launcher] java -jar {L["jar"]} {args}"\n'
            f'exec java -jar "{jar_u}" {args}\n'
        )
        return script, LOGDIR / L.get("logFile", f"dashboard-{proj['id']}.log"), f"java -jar {L['jar']} {args}"

    if kind == "script":
        s = L["script"]
        a = " ".join(shlex.quote(x) for x in L.get("startArgs", []))
        script = f'cd "{ws_u}"\nexec bash "{s}" {a}\n'
        return script, LOGDIR / L.get("logFile", f"dashboard-{proj['id']}.log"), f"bash {s} {a}"

    raise RuntimeError(L.get("reason", "这个项目不支持一键启动"))


def spawn(script, logfile: Path, cwd: Path):
    logfile.parent.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in POISON_ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    fh = open(logfile, "ab")
    fh.write(f"\n\n===== {datetime.now().isoformat(timespec='seconds')} 由工作台启动 =====\n".encode("utf-8"))
    fh.flush()
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
    try:
        p = subprocess.Popen(
            [find_bash(), "-c", script],
            cwd=str(cwd), env=env,
            stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
            creationflags=flags, close_fds=True,
        )
    finally:
        fh.close()
    return p.pid


def job_start(pid):
    proj = CFG.project(pid)
    RT.update(pid, state="starting", error=None, startedAt=datetime.now().isoformat(timespec="seconds"))
    RT.say(pid, f"── 开始启动 {proj['name']} ──")

    try:
        L = proj["launch"]
        if L["type"] == "none":
            raise RuntimeError(L.get("reason", "这个项目不支持一键启动"))

        ports = proj.get("ports", [])
        req = [p["port"] for p in ports if not p.get("optional")]
        allp = [p["port"] for p in ports]

        # 0) 已经起来了就别重复起。但必须先确认端口后面站的是 java ——
        #    否则「端口被别的程序占着」会被误判成「已经在运行」，然后一路成功到底。
        if allp:
            ls = netstat_listeners()
            nm = process_names([ls.get(p) for p in allp])
            sts = [check_owner(p, ls, ["java"], nm) for p in allp]
            if all(s in ("ok", "unknown") for s in sts):
                RT.say(pid, "端口已经在监听（进程名也对得上），视为已在运行")
                RT.update(pid, state="running", phase="已在运行")
                return
            for p, s in zip(allp, sts):
                if s == "wrong-process":
                    owner = nm.get(ls.get(p))
                    raise RuntimeError(
                        f"端口 {p} 被 {owner} 占着，不是 java —— 这个端口不腾出来，"
                        f"{proj['name']} 起不来。先停掉占用它的程序。")

        # 1) 中间件
        RT.update(pid, phase="检查中间件")
        missing = ensure_middleware(pid, proj.get("middleware", []))

        # strictMiddleware=false 的项目（比如 P2 有 7 个模块、依赖各不相同）
        # 不因为缺中间件就拒绝启动 —— 能起几个是几个，起不来的在结果里如实报告。
        strict = L.get("strictMiddleware", True)
        blocking = [i for i in missing
                    if strict and (CFG.middleware_by_id(i) or {}).get("svc")]
        if blocking:
            names = ", ".join(CFG.middleware_by_id(i)["name"] for i in blocking if CFG.middleware_by_id(i))
            raise RuntimeError(f"中间件没能起来：{names}。可以手动跑 ./svc.sh start，或看 ./svc.sh status")
        if missing and not strict:
            names = ", ".join(CFG.middleware_by_id(i)["name"] for i in missing if CFG.middleware_by_id(i))
            RT.say(pid, f"⚠ 这些中间件没起来：{names} —— 继续启动，相关模块可能会失败")

        # 2) 构建产物检查（早失败早报错，比等 120 秒端口超时友好得多）
        if L["type"] == "jar":
            jar = WS / L["cwd"] / L["jar"]
            if not jar.is_file():
                raise RuntimeError(
                    f"找不到构建产物 {jar.relative_to(WS)}。先构建："
                    + f"cd {L['cwd']} && mvn -DskipTests clean package"
                )

        # 3) 拉起
        RT.update(pid, phase="拉起进程")
        script, logfile, desc = build_launch_command(proj)
        RT.say(pid, f"启动命令：{desc}")
        RT.say(pid, f"工作目录：{proj['path']}（JDK {L.get('jdk', '由脚本决定')}）")
        RT.say(pid, f"日志文件：logs/{logfile.name}")

        child = spawn(script, logfile, WS)
        RT.update(pid, trackedPid=child)
        RT.say(pid, f"进程已拉起，PID {child}")

        # 4) 等端口。只等「必需」端口 —— 标了 optional 的（比如 mall-portal 要四个
        #    中间件才起得来）不参与就绪判定，但它们的状态会照实报告出来。
        if req:
            timeout = L.get("readyTimeoutSec", 120)
            RT.update(pid, phase=f"等待端口就绪（最多 {timeout} 秒）")
            deadline = time.time() + timeout
            while time.time() < deadline:
                if all(port_open(p) for p in req):
                    break
                time.sleep(1.5)
            else:
                tail = tail_file(logfile, 12)
                RT.say(pid, "⚠ 端口在超时前没有起来，日志尾部：")
                for line in tail:
                    RT.say(pid, "  " + line)
                raise RuntimeError(
                    f"{timeout} 秒内必需端口 {', '.join(map(str, req))} 没有进入监听状态。"
                    f"完整日志：logs/{logfile.name}"
                )

        # 必需端口就绪后，再给可选端口留点时间。
        # ★ P2 实测：mall-portal / mall-demo 比必需端口晚约 60 秒（它们要等 Nacos
        #   配置拉完才起 Tomcat）。不额外等一下的话，卡片上会先闪一条
        #   「8085 没起来」的假警报 —— 明明只是慢，却报成了失败。
        if any(p.get("optional") for p in ports):
            extra_deadline = time.time() + 75
            while time.time() < extra_deadline:
                if all(port_open(p["port"]) for p in ports):
                    break
                time.sleep(2)

        up = [p for p in allp if port_open(p)]
        down = [p for p in allp if p not in up]
        RT.say(pid, f"✅ 端口就绪：{', '.join(map(str, up)) if up else '（该项目无端口）'}")
        for p in ports:
            if p["port"] in down:
                RT.say(pid, f"  ⚠ {p['port']}（{p.get('label', '')}）还没起来"
                            + (f" —— {p['why']}" if p.get("why") else "")
                            + "。卡片状态会持续刷新，如果后面起来了会自动变绿。")
        RT.update(pid, state="running", phase="运行中")
        RT.say(pid, f"── {proj['name']} 启动完成 ──")

    except Exception as e:  # noqa: BLE001
        RT.say(pid, f"❌ 启动失败：{e}")
        RT.update(pid, state="failed", error=str(e), phase="启动失败")


def kill_pid(pid: int):
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=30)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def job_stop(pid):
    proj = CFG.project(pid)
    RT.update(pid, state="stopping", error=None)
    RT.say(pid, f"── 开始停止 {proj['name']} ──")
    L = proj["launch"]

    try:
        if L["type"] == "script" and L.get("stopArgs"):
            RT.say(pid, f"调用 bash {L['script']} {' '.join(L['stopArgs'])}")
            bash = find_bash()
            p = subprocess.run([bash, L["script"]] + L["stopArgs"], cwd=str(WS),
                               capture_output=True, timeout=180)
            txt = decode_console(p.stdout or b"")
            for line in txt.splitlines()[-15:]:
                RT.say(pid, "  " + line.strip())
            RT.say(pid, f"退出码 {p.returncode}")
        else:
            listeners = netstat_listeners()
            tracked = RT.get(pid).get("trackedPid")
            targets = set()
            if tracked and tracked in listeners.values():
                targets.add(tracked)
            for prt in [p["port"] for p in proj.get("ports", [])]:
                if prt in listeners and listeners[prt]:
                    targets.add(listeners[prt])
            if not targets:
                RT.say(pid, "端口都没在听，也没有记录的进程 —— 视为已停止")
            for t in targets:
                RT.say(pid, f"taskkill /PID {t} /T /F")
                kill_pid(t)

        # 等端口真的关掉
        ports = [p["port"] for p in proj.get("ports", [])]
        deadline = time.time() + 45
        while time.time() < deadline:
            if not any(port_open(p) for p in ports):
                break
            time.sleep(1)
        left = [p for p in ports if port_open(p)]
        if left:
            raise RuntimeError(f"端口 {', '.join(map(str, left))} 仍在监听 —— 可能还有别的进程占着")

        RT.update(pid, state="idle", phase="已停止", trackedPid=None)
        RT.say(pid, f"✅ {proj['name']} 已停止")

    except Exception as e:  # noqa: BLE001
        RT.say(pid, f"❌ 停止失败：{e}")
        RT.update(pid, state="failed", error=str(e), phase="停止失败")


def tail_file(path: Path, lines=200):
    if not path.is_file():
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = min(size, 256 * 1024)
            f.seek(size - block)
            raw = f.read()
        text = raw.decode("utf-8", "replace")
        return text.splitlines()[-lines:]
    except Exception as e:  # noqa: BLE001
        return [f"(读日志失败：{e})"]


# ---------------------------------------------------------------------------
# 汇总视图
# ---------------------------------------------------------------------------
def project_view(proj, listeners, names=None):
    names = names or {}
    # 项目期望的宿主进程：jar / script 类型最终都是 java
    L = proj["launch"]
    hints = ["java"] if L["type"] in ("jar", "script") else []

    ports = []
    for p in proj.get("ports", []):
        status, owner = check_owner(p["port"], listeners, hints, names)
        ports.append({**p, "listening": p["port"] in listeners,
                      "pid": listeners.get(p["port"]),
                      "ownerStatus": status, "owner": owner})

    # 只有「端口在听」且「进程名对得上（或认不出来）」才算真的在运行
    required = [p for p in ports if not p.get("optional")]
    optional = [p for p in ports if p.get("optional")]

    def is_up(p):
        return p["listening"] and p["ownerStatus"] != "wrong-process"

    hijacked = [p for p in ports if p["ownerStatus"] == "wrong-process"]
    any_up = any(is_up(p) for p in ports)
    down_optional = [p for p in optional if not is_up(p)]
    rt = RT.get(proj["id"])

    # 必需端口全绿、且没有可选模块掉队，才算「运行中」。
    # ★ 早先的写法是「必需端口齐了就 running」，结果 P2 的 mall-portal 挂了
    #   却显示成「运行中」—— 7 个模块的进程列表里少了两个，界面上完全看不出来。
    #   宁可标成「部分运行」并列出掉队的是谁，也不要给一个漂亮的假绿灯。
    if required:
        req_ok = all(is_up(p) for p in required)
    else:
        req_ok = any_up

    if rt["state"] in ("starting", "stopping"):
        state = rt["state"]
    elif req_ok and not down_optional:
        state = "running"
    elif any_up:
        state = "partial"
    elif rt["state"] == "failed":
        state = "failed"
    else:
        state = "stopped"

    path = WS / proj["path"]

    build = None
    if L["type"] == "jar":
        jar = WS / L["cwd"] / L["jar"]
        build = {"artifact": str(Path(L["cwd"]) / L["jar"]), "exists": jar.is_file()}
    elif L["type"] == "script":
        build = {"artifact": L["script"], "exists": (WS / L["script"]).is_file()}

    declared = "planned" if L["type"] == "none" else (
        "ready" if (build and build["exists"]) else "needs-build")

    return {
        "id": proj["id"], "stage": proj["stage"], "name": proj["name"],
        "title": proj["title"], "summary": proj["summary"],
        "category": proj["category"], "categoryLabel": CFG.category_label(proj["category"]),
        "tags": proj.get("tags", []), "stack": proj.get("stack", []),
        "origin": {**CFG.origin(proj["origin"]["kind"]), "kind": proj["origin"]["kind"],
                   "repo": proj["origin"].get("repo"), "note": proj["origin"].get("note")},
        "path": proj["path"], "absPath": str(path), "pathExists": path.is_dir(),
        "openUrl": proj.get("openUrl"), "openLabel": proj.get("openLabel"),
        "ports": ports,
        "docs": proj.get("docs", {}),
        "middleware": [
            {"id": m, "name": (CFG.middleware_by_id(m) or {}).get("name", m),
             "running": middleware_up(m, listeners, names),
             "port": (CFG.middleware_by_id(m) or {}).get("port")}
            for m in proj.get("middleware", [])
        ],
        "launch": {
            "type": L["type"], "jdk": L.get("jdk"), "reason": L.get("reason"),
            "command": describe_command(proj),
            "canStart": L["type"] != "none",
        },
        "build": build,
        "declared": declared,
        "state": state,
        "hijacked": hijacked,
        "downOptional": [{"port": p["port"], "label": p.get("label"), "why": p.get("why")}
                         for p in down_optional],
        "warning": (
            "端口 " + "、".join(f"{h['port']}（被 {h['owner']} 占用）" for h in hijacked)
            + " —— 这个端口被别的程序占着，项目起不来也不会显示成运行中"
        ) if hijacked else None,
        "phase": rt["phase"],
        "error": rt["error"],
        "trackedPid": rt["trackedPid"],
        "startedAt": rt["startedAt"],
        "logFile": f"logs/{(L.get('logFile') or '')}" if L.get("logFile") else None,
    }


def describe_command(proj):
    """把启动命令拼成一句人能读的话，显示在界面上（含中间件前置）。"""
    L = proj["launch"]
    if L["type"] == "none":
        return None
    mw = [m for m in proj.get("middleware", [])]
    pre = f"./svc.sh start {' '.join(mw)}   # 中间件（工作台会自动跑）\n" if mw else ""
    if L["type"] == "jar":
        args = " ".join(L.get("args", []))
        return (f"{pre}source use-jdk.sh {L['jdk']}\n"
                f"cd {L['cwd']}\n"
                f"java -jar {L['jar']} {args}".rstrip())
    a = " ".join(L.get("startArgs", []))
    return f"{pre}./{L['script']} {a}".rstrip()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "WorkspaceDashboard/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # 静音；需要时打开
        pass

    # -- helpers ----------------------------------------------------------
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _err(self, code, msg):
        self._json({"ok": False, "error": msg}, code)

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # -- routing ----------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)

        if path.startswith("/api/"):
            return self.api_get(path, q)
        return self.static(path)

    do_HEAD = do_GET

    def do_POST(self):
        u = urlparse(self.path)
        body = self._read_body()
        try:
            return self.api_post(u.path, body)
        except Exception as e:  # noqa: BLE001
            return self._err(500, f"内部错误：{e}")

    # -- static -----------------------------------------------------------
    MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
            ".woff2": "font/woff2"}

    def static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        # 只允许 web/ 下的文件，防止 ../ 穿越
        rel = path.lstrip("/")
        target = (WEB / rel).resolve()
        try:
            target.relative_to(WEB.resolve())
        except ValueError:
            return self._err(403, "越界")
        if not target.is_file():
            return self._err(404, f"找不到 {path}")
        ctype = self.MIME.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    # -- GET api ----------------------------------------------------------
    def api_get(self, path, q):
        if path == "/api/health":
            return self._json({"ok": True, "service": "workspace-dashboard", "ts": now_iso()})

        if path == "/api/config":
            return self._json({
                "ok": True,
                "workspace": str(WS),
                "dashboard": CFG.dashboard,
                "categories": CFG.categories,
                "origins": CFG.origins,
                "configPath": str(CONFIG.relative_to(WS)),
                "configAbsPath": str(CONFIG),
            })

        if path == "/api/projects":
            listeners = netstat_listeners()
            # 一次把「所有项目端口 + 所有中间件端口」的宿主进程名解析出来，复用给全部项目
            want = set()
            for p in CFG.projects:
                want.update(x["port"] for x in p.get("ports", []))
            for m in CFG.middleware:
                want.add(m["port"])
            names = process_names([listeners.get(x) for x in want])
            items = [project_view(p, listeners, names) for p in CFG.projects]
            # 支持 ?q= / ?category= / ?tag= / ?state= / ?origin= —— 服务端也实现一遍，
            # 这样接口本身可用（前端为了即时响应仍然在本地过滤）
            kw = (q.get("q", [""])[0] or "").strip().lower()
            cat = q.get("category", [None])[0]
            tag = q.get("tag", [None])[0]
            st = q.get("state", [None])[0]
            og = q.get("origin", [None])[0]
            if kw:
                items = [i for i in items if kw in " ".join([
                    i["name"], i["title"], i["summary"], " ".join(i["stack"]),
                    " ".join(i["tags"]), i["stage"], i["categoryLabel"]]).lower()]
            if cat:
                items = [i for i in items if i["category"] == cat]
            if tag:
                items = [i for i in items if tag in i["tags"]]
            if st:
                items = [i for i in items if i["state"] == st]
            if og:
                items = [i for i in items if i["origin"]["kind"] == og]
            return self._json({"ok": True, "count": len(items),
                               "total": len(CFG.projects), "projects": items})

        m = re.fullmatch(r"/api/projects/([\w-]+)/log", path)
        if m:
            proj = CFG.project(m.group(1))
            if not proj:
                return self._err(404, "没有这个项目")
            lines = int((q.get("lines", ["200"])[0] or 200))
            L = proj["launch"]

            # script 类型（P2）的日志是多份的：p2.sh 自己只输出一张状态表，
            # 每个模块真正的启动日志在 logs/p2-<模块>.log 里。
            # 只看 dashboard-p2.log 等于什么都没看到，所以支持 logGlob 一把捞全。
            globpat = L.get("logGlob")
            if globpat:
                files = sorted(LOGDIR.glob(Path(globpat).name))
                if not files:
                    return self._json({"ok": True, "file": globpat, "exists": False,
                                       "lines": [f"（还没有匹配 {globpat} 的文件）"]})
                per = max(20, lines // max(1, len(files)))
                out = []
                for f in files:
                    out.append(f"===== {f.name}（末 {per} 行）=====")
                    out.extend(tail_file(f, per))
                    out.append("")
                return self._json({"ok": True, "file": globpat, "exists": True,
                                   "files": [f"logs/{f.name}" for f in files], "lines": out})

            lf = L.get("logFile")
            if not lf:
                return self._json({"ok": True, "lines": [], "note": "这个项目没有日志文件"})
            f = LOGDIR / lf
            return self._json({"ok": True, "file": f"logs/{lf}", "exists": f.is_file(),
                               "lines": tail_file(f, max(1, min(lines, 2000)))})

        m = re.fullmatch(r"/api/projects/([\w-]+)/job", path)
        if m:
            return self._json({"ok": True, "jobLog": RT.log_of(m.group(1)),
                               "runtime": RT.get(m.group(1))})

        if path == "/api/system":
            reg = jdk_registry()
            return self._json({
                "ok": True,
                "workspace": str(WS),
                "platform": sys.platform,
                "python": sys.version.split()[0],
                "bash": find_bash(),
                "jdks": reg["jdks"],
                "jdksSource": reg["source"],
                "middleware": middleware_status(),
                "listeners": netstat_listeners(),
                "dashboardPort": PORT,
            })

        if path == "/api/template":
            return self._json({"ok": True, "template": TEMPLATE, "howto": TEMPLATE_HOWTO})

        return self._err(404, f"没有这个接口：{path}")

    # -- POST api ---------------------------------------------------------
    def api_post(self, path, body):
        m = re.fullmatch(r"/api/projects/([\w-]+)/(start|stop)", path)
        if m:
            pid, action = m.group(1), m.group(2)
            proj = CFG.project(pid)
            if not proj:
                return self._err(404, "没有这个项目")
            cur = RT.get(pid)
            if cur["state"] in ("starting", "stopping"):
                return self._json({"ok": True, "state": cur["state"],
                                   "note": "已有任务在执行，忽略本次请求"}, 202)
            # 不支持启动的项目当场拒绝，别先 202 再失败 ——
            # 那样前端会先亮一下「启动中」，再变成失败，看着像出错了。
            if action == "start" and proj["launch"]["type"] == "none":
                return self._err(400, proj["launch"].get("reason", "这个项目不支持一键启动"))
            fn = job_start if action == "start" else job_stop
            threading.Thread(target=fn, args=(pid,), daemon=True).start()
            return self._json({"ok": True, "state": "starting" if action == "start" else "stopping"}, 202)

        m = re.fullmatch(r"/api/middleware/([\w-]+)/(start|stop)", path)
        if m:
            mid, action = m.group(1), m.group(2)
            mm = CFG.middleware_by_id(mid)
            if not mm:
                return self._err(404, "没有这个中间件")
            if not mw_manageable(mm):
                return self._err(400, f"{mm['name']} 工作台起不了 —— 工作区里没有它的启动器，"
                                      f"请手动启动")

            if action == "start":
                # 同步等它起来：中间件比应用轻，几十秒内见分晓，
                # 而且用户点这个按钮时就是要一个明确结果。
                try:
                    ok, detail = start_middleware(None, mm)
                except subprocess.TimeoutExpired:
                    return self._err(504, "启动命令超时")
                deadline = time.time() + 90
                while time.time() < deadline and not middleware_up(mid):
                    time.sleep(2)
                return self._json({"ok": middleware_up(mid), "detail": detail,
                                   "running": middleware_up(mid)})

            # stop
            if mm.get("svc"):
                try:
                    rc, out = svc_run(["stop", mm["svc"]])
                    return self._json({"ok": rc == 0, "exitCode": rc,
                                       "output": out[-4000:], "running": middleware_up(mid)})
                except subprocess.TimeoutExpired:
                    return self._err(504, "svc.sh 超时")
            # launcher 类型（Ollama）：按端口反查 PID 杀
            ls = netstat_listeners()
            pidv = ls.get(mm["port"])
            if not pidv:
                return self._json({"ok": True, "running": False, "note": "端口没在听，视为已停止"})
            nm = process_names([pidv])
            owner = nm.get(pidv)
            if mm.get("processHint") and owner and \
                    not any(h.lower() in owner.lower() for h in mm["processHint"]):
                return self._err(409, f"端口 {mm['port']} 上是 {owner}，不是 {mm['name']}，拒绝结束它")
            kill_pid(pidv)
            time.sleep(1.5)
            return self._json({"ok": not middleware_up(mid), "killedPid": pidv,
                               "running": middleware_up(mid)})

        if path == "/api/reload":
            try:
                reload_config()
                return self._json({"ok": True, "count": len(CFG.projects)})
            except Exception as e:  # noqa: BLE001
                return self._err(400, f"projects.json 解析失败：{e}")

        return self._err(404, f"没有这个接口：{path}")


# ---------------------------------------------------------------------------
# 新增项目模板（给「预留新增项目入口」用）
# ---------------------------------------------------------------------------
TEMPLATE = {
    "id": "p5-my-project",
    "stage": "P5",
    "name": "my-project",
    "title": "一句话标题",
    "summary": "2-3 行简介：这个项目是干什么的、用了什么。",
    "category": "api",
    "tags": ["标签一", "标签二"],
    "origin": {"kind": "original", "repo": "https://github.com/你/仓库", "note": "来源说明"},
    "path": "p5-my-project",
    "ports": [{"port": 8099, "label": "HTTP"}],
    "stack": ["Java 17", "Spring Boot 3.5"],
    "docs": {"README": "p5-my-project/README.md"},
    "middleware": ["mysql8"],
    "launch": {
        "type": "jar", "jdk": "17", "cwd": "p5-my-project",
        "jar": "target/my-project-1.0.0.jar",
        "args": ["--server.port=8099"],
        "logFile": "dashboard-p5.log", "readyTimeoutSec": 120
    }
}
TEMPLATE_HOWTO = [
    "打开 dashboard/projects.json，在 projects 数组里粘贴这个对象",
    "把 id / stage / name / title / summary / category / path / ports / stack 改成你自己的",
    "origin.kind 三选一：original（自己写的）/ clone（克隆来学习的）/ planned（还没代码）—— 这一项必须如实填",
    "category 必须是文件里 categories 数组里的某个 id，否则卡片会显示原始值",
    "launch.type：jar（用 java -jar 起）/ script（调工作区里的 .sh）/ none（不支持启动）",
    "改完在页面上点右上角「重载配置」，不用重启服务",
]


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
PORT = 8990


def main():
    global CFG, PORT
    ap = argparse.ArgumentParser(description="java-workspace 项目工作台")
    ap.add_argument("--port", type=int, default=None, help="监听端口（默认取 projects.json 里的 dashboard.port）")
    ap.add_argument("--no-browser", action="store_true", help="启动后不自动开浏览器")
    args = ap.parse_args()

    if not CONFIG.is_file():
        print(f"[dashboard] 找不到配置文件 {CONFIG}", file=sys.stderr)
        return 1
    try:
        CFG = Config(CONFIG)
    except Exception as e:  # noqa: BLE001
        print(f"[dashboard] projects.json 解析失败：{e}", file=sys.stderr)
        return 1

    PORT = args.port or int(CFG.dashboard.get("port", 8990))

    if port_open(PORT):
        print(f"[dashboard] 端口 {PORT} 已被占用 —— 工作台可能已经在跑了。"
              f"\n            打开 http://127.0.0.1:{PORT}/ ，或换一个端口："
              f"python dashboard/server.py --port 8991", file=sys.stderr)
        return 1

    LOGDIR.mkdir(parents=True, exist_ok=True)

    # 只绑回环：这个服务能启动本机进程，绝不能对局域网暴露
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    httpd.daemon_threads = True

    url = f"http://127.0.0.1:{PORT}/"
    print()
    print("  ┌────────────────────────────────────────────────┐")
    print("  │  java-workspace 项目工作台                     │")
    print("  └────────────────────────────────────────────────┘")
    print(f"   地址      {url}")
    print(f"   工作区    {WS}")
    print(f"   清单      {CONFIG.relative_to(WS)}（{len(CFG.projects)} 个项目）")
    print(f"   绑定      127.0.0.1（仅本机可访问）")
    print(f"   停止      Ctrl+C")
    print()

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] 收到 Ctrl+C，正在关闭…")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
