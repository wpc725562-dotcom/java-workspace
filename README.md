# Java Workspace —— 赴日 IT 就职项目训练场

> **🇯🇵 日本語サマリー**
> Spring Boot 2.7 / 3.4 / 3.5 という**互換性のない 3 世代**の Java プロジェクトを
> **1 台の Windows マシン上で共存**させるための、ポータブルな開発ワークスペースです。
>
> - システム環境を**一切変更しない**（JDK はポータブル版、ミドルウェアは展開するだけ）
> - ミドルウェア 8 種（MySQL 5.7/8.0、Redis、Nacos、MongoDB、Elasticsearch、RabbitMQ、MinIO）
>   を `svc.cmd` 1 コマンドで起停
> - JDK 8 / 17 / 21 を `use-jdk` で**ウィンドウ単位**に切替（`JAVA_HOME` は汚さない）
> - 各プロジェクトの起動手順・ハマりどころを **2,400 行超のドキュメント**に記録
> - E2E 検証スクリプト 7 本（Python）＋ 自作の**プロジェクト・ダッシュボード**
>   —— 5 プロジェクトの状態を一覧し、ワンクリックで起停（UI 検証 55 項目パス）
> - さらに **自作の Spring Boot 製 REST API**（[exam-tracker](https://github.com/wpc725562-dotcom/exam-tracker)）
>   —— 単体テスト 309 件・結合テスト 35 件・E2E 検証 86 項目、すべてパス
>
> **English summary**: A portable, zero-system-pollution development workspace that lets
> three mutually incompatible Spring Boot generations (2.7 / 3.4 / 3.5) coexist on one
> Windows host — portable JDKs, script-managed middleware, ~3,300 lines of runbooks,
> 7 end-to-end verification scripts, a **self-built project dashboard** (one-click
> start/stop for all five projects, verified by 55 browser assertions), plus a
> **from-scratch Spring Boot REST API**
> ([exam-tracker](https://github.com/wpc725562-dotcom/exam-tracker)) with 309 unit tests,
> 35 integration tests and 86 passing end-to-end assertions.

> 建立于 2026-09-28。目的：把 P0–P3 四个阶段的项目**隔离**在一个工作区里，共用一套中间件，
> 但**互不干扰**（各自的 JDK、各自的依赖、各自的数据库 schema、各自的端口）。
>
> 关键约束：**不改动系统环境**。所有 JDK 走便携版，所有中间件走「解压即用」的便携版。
> 删掉 `D:\java-workspace` 就等于完全回滚，系统里不留任何痕迹。
>
> **本工作区自己写的项目**（不属于 P0–P3 的克隆）：**[exam-tracker](https://github.com/wpc725562-dotcom/exam-tracker)**
> —— 备考任务追踪 API，Spring Boot 3.5 / Java 17 / JWT / MySQL，
> 22 个接口、309 个单元测试、35 个集成测试、86 项端到端断言。它**单独发了一个仓库**，见第 0 节。
>
> **本工作区自己写的工具**：**[dashboard/](dashboard/)** —— 项目工作台。
> 一个页面看完 P0–P4 的状态，能筛选能搜索，能真的把项目起起来。
> 零第三方依赖（标准库 `http.server` + 原生 JS），65 项浏览器断言全通过。

---

## 0. 这个仓库是什么、不是什么

**是什么**：一套**自研的环境工程工具链**。脚本、文档、验证工具全部原创。

**不是什么**：**不包含任何第三方项目源码，也不包含 P4 的源码。**
P0 / P1 / P2 三个学习项目是上游开源仓库的浅克隆（各自独立仓库、origin 指向上游，已被 `.gitignore` 排除）；
P4 `exam-tracker` 是**本工作区原创**的，但它**单独发了一个仓库**，所以这里同样排除 ——
本仓库只放「让这些东西能跑起来」的脚本、文档与验证工具。

| 阶段 | 项目 | 性质 | 本仓库提供的是 |
|---|---|---|---|
| P0 | [elunez/eladmin-mp](https://github.com/elunez/eladmin-mp) | 上游克隆 | 启动手册 + 配置修复 + 登录验证脚本 |
| P1 | [liyupi/yu-ai-agent](https://github.com/liyupi/yu-ai-agent) | 上游克隆 | 启动手册 + 本地 Ollama 离线化方案 + 24 项 E2E 验证 |
| P2 | [macrozheng/mall-swarm](https://github.com/macrozheng/mall-swarm) | 上游克隆 | 启动手册 + 配置批量修复 + Nacos 配置发布 + E2E 验证 |
| **P4** | **[wpc725562-dotcom/exam-tracker](https://github.com/wpc725562-dotcom/exam-tracker)** | **★ 本工作区原创** | 只在本仓库登记端口与库；**源码请去它自己的仓库看** |

> 之所以不把 P0–P2 并进来：一是版权（那是别人的代码），二是技术上也做不到
> —— 见第 1 节的 `javax` / `jakarta` 硬墙。
>
> P4 是原创，为什么也不放进来？因为**埋在子目录里没人会点进去**。
> 它需要一个能被一眼看到的仓库地址，才能填上「Java + Spring 后端」那一栏。

**内容规模**：脚本 1,900 行、文档 3,300 行、验证工具 1,400 行、项目工作台 3,900 行，
合计 **约 10,500 行**（不含 P4 的 11,500 行）。

**P4 单独统计**：60 个主源文件 / 5,270 行 + 23 个测试文件 / 6,311 行 = **11,581 行**，
309 个单元测试、35 个集成测试、86 项端到端断言，全部实测通过（CI 上同样全绿）。

---

## 1. 为什么不是「集成进现有项目」

调研结论（见 `docs/` 与之前的集成可行性报告）：**这四个项目在技术上无法合并成一个工程**。

| 冲突维度 | P0 eladmin-mp | P1 yu-ai-agent | P2 mall-swarm | 能否调和 |
|---|---|---|---|---|
| Java 版本 | 1.8 | 21 | 17 | ❌ 无法在同一个 JVM 里跑 |
| Spring Boot | 2.7.18 | 3.4.4 | 3.5.14 | ❌ 2.x 与 3.x API 不兼容 |
| 命名空间 | `javax.*` | `jakarta.*` | `jakarta.*` | ❌ **硬墙**，必须改源码 |
| groupId | `me.zhengjie` | `com.yupi` | `com.macro.mall` | ✅ 不冲突 |
| 端口 | 8000 | 8123 | 8080–8401 | ✅ 不冲突 |

`javax.*` → `jakarta.*` 是**硬墙**：这两套命名空间在同一个 JVM 里无法共存，
合并意味着要改掉成千上万行 import，改完之后它就不再是「那个开源项目」了，
面试时也无法拿它当学习样本讲。

**所以正确做法是「共处一个工作区」而不是「合并成一个工程」** ——
Monorepo ≠ mono-build。「同一个目录」和「同一个构建」是两件事。

---

## 2. 目录结构

```
java-workspace\
├── README.md                    ← 你在这里
├── svc.cmd / svc.sh             ← 中间件启停（svc.sh 是 Git Bash 的转发壳，真正实现是 svc.cmd）
├── use-jdk.cmd / use-jdk.sh     ← 切换 JDK（只影响当前窗口）
├── run-minio.cmd                ← 单个中间件的独立启动器（MinIO）
├── run-nacos.cmd                ← Nacos
├── run-rabbitmq.cmd             ← RabbitMQ（同时是 rabbitmqctl 的包装器）
├── run-ollama.cmd               ← Ollama（本地大模型，P1 依赖它）
├── docker-compose.yml           ← Docker 方案（**当前不可用**，见 docs/runtime.md 第 1 节）
├── p2.sh                        ← P2 mall-swarm 的一键构建/启动
├── sql\01-schemas.sql           ← 建库建账号脚本（便携版和 Docker 共用这一份）
│
├── .jdks\                       ← 便携版 JDK（不进 git）
│   ├── corretto-8\              ← 给 P0 eladmin-mp
│   ├── corretto-21\             ← 给 P1 yu-ai-agent
│   └── （JDK 17 用系统已装的）
├── .runtime\                    ← 便携版中间件（不进 git，约 6 GB）
│   ├── mysql-8.0\               ← 3308
│   ├── mysql-5.7\               ← 3307
│   ├── redis\                   ← 6380
│   ├── nacos\                   ← 8848 / 8849
│   ├── mongodb\                 ← 27017
│   ├── elasticsearch\           ← 9200
│   ├── erlang\ + rabbitmq\      ← 5672 / 15672
│   ├── minio\                   ← 9000 / 9001
│   ├── ollama\                  ← 11434（含 qwen3:0.6b 等 3 个模型）
│   ├── conf\                    ← my.ini / redis.conf / mongod.yml 等
│   ├── data\                    ← 数据目录（删掉即重置）
│   └── logs\                    ← 日志
│
├── docs\
│   ├── runtime.md               ← 运行环境总说明（8 个中间件怎么装、怎么踩的坑）
│   ├── port-map.md              ← 端口分配表（全工作区，避免撞车）
│   ├── jdk-matrix.md            ← 哪个项目用哪个 JDK、编码问题怎么修
│   ├── run-p0.md                ← P0 eladmin-mp 启动手册
│   ├── run-p1.md                ← P1 yu-ai-agent 启动手册
│   └── run-p2.md                ← P2 mall-swarm 启动手册
│
├── dashboard\                   ← ★ 本工作区自研：项目工作台（见第 10 节）
│   ├── README.md                ← 用法 + 加新项目 + 设计上踩过的 14 个坑
│   ├── projects.json            ← 声明式项目清单：加项目只改这个文件
│   ├── server.py                ← 零依赖本地服务（标准库 http.server）
│   ├── start.cmd / stop.cmd     ← 一键启动 / 按端口停止（纯 ASCII + CRLF）
│   ├── verify-ui.js             ← 真浏览器 65 项界面断言 + 三断点截图
│   └── web\                     ← index.html / style.css / app.js（无框架无构建）
│
├── tools\                       ← 验证与自动化工具（Python）
│   ├── p0-login-test.py         ← P0 登录链路验证
│   ├── p1-e2e-test.py           ← P1 端到端验证（24 项断言）
│   ├── p2-e2e-test.py           ← P2 端到端验证（全链路）
│   ├── p2-fix-configs.py        ← P2 配置批量修复
│   ├── p2-publish-nacos-configs.py ← 把配置发布到 Nacos
│   ├── p2-minio-test.py         ← MinIO 上传/下载验证
│   └── p2-rabbitmq-test.py      ← RabbitMQ 收发验证
│
├── p0-eladmin-mp\               ← 【不进本仓库】P0：Spring Boot 单体（Java 8 / Boot 2.7 / javax）
├── p1-yu-ai-agent\              ← 【不进本仓库】P1：Java + AI（Java 21 / Boot 3.4 / jakarta）
├── p2-mall-swarm\               ← 【不进本仓库】P2：微服务（Java 17 / Boot 3.5 / jakarta）
├── p3-seckill\                  ← P3：计划中（见 p3-seckill/README-为何先空着.md）
└── p4-exam-tracker\             ← 【不进本仓库】★ 本工作区原创：备考任务追踪 API
                                    （Spring Boot 3.5 / Java 17 / JWT / MySQL）
                                    自己的仓库：https://github.com/wpc725562-dotcom/exam-tracker
                                    端口 8090、库 exam_tracker（MySQL 3308）
```

**每个 `pX-*` 目录都是独立的 git 仓库**（克隆进来的第三方项目自带 `.git`；
`p4-exam-tracker` 也有自己的 `.git`，origin 指向它自己的 GitHub 仓库），
它们被本仓库的 `.gitignore` 排除，**不参与本仓库的版本控制**。
不要把它们改成 submodule —— 保持彼此独立，各自 `git pull` 升级上游。

> ⚠️ 本仓库的 `.git` 在工作区根目录。在 `p0-eladmin-mp/` 等子目录里执行 git 命令时，
> git 会自动找到**最近的那个** `.git`（也就是子项目自己的），不会误伤本仓库。

---

## 3. 快速开始

```bash
cd /d/java-workspace

# ① 起中间件（便携版，不需要 Docker）
./svc.sh status            # 看状态
./svc.sh start             # 起 mysql8 + mysql57 + redis
./svc.sh start mysql8      # 也可以只起一个

# ② 切 JDK（Git Bash 里必须 source）
source use-jdk.sh 8        # 给 P0 用
source use-jdk.sh 21       # 给 P1 用
source use-jdk.sh 17       # 给 P2 用（走系统已装的 JDK 17）

# ③ 进项目编译
cd p0-eladmin-mp && ./mvnw -DskipTests clean package
```

Windows cmd 里：`svc.cmd start` / `use-jdk.cmd 8`（`use-jdk.cmd` 不用 call，直接跑就行）。

> ⚠️ `use-jdk.sh` **必须 `source`**（它改当前 shell 的环境变量）；
> `svc.sh` **直接执行**（它不改环境变量，只是转发给 `svc.cmd`）。两个规则不一样，别记混。

---

## 4. JDK 策略：为什么是便携版

系统里**只有 JDK 17**（Amazon Corretto 17.0.20.10，装在 `C:\Program Files\Amazon Corretto\`）。

- P2 mall-swarm 要 Java 17 → **系统现成的就能用**，不用装。
- P0 eladmin-mp 要 Java 1.8 → 需要 JDK 8。
- P1 yu-ai-agent 要 Java 21 → 需要 JDK 21。

如果去装 JDK 8 / 21 的安装包，它们会**抢着改系统的 `JAVA_HOME` 和 `PATH`**，
把现有 JDK 17 搞坏，而且卸载时经常清不干净。

所以这里用**便携版**：下载 zip → 解压到 `D:\java-workspace\.jdks\` → 谁都不碰。
切换靠 `use-jdk` 脚本，**只改当前那个命令行窗口的环境变量**，关掉窗口就恢复。
系统环境变量一个字节都不动。

细节见 `docs/jdk-matrix.md`。

---

## 5. 中间件策略：便携版（Docker 暂时用不了）

本机 **MySQL ❌ / Redis ❌ 都没装**，Docker 装了但**起不来**。

根因不在 Docker，在 Windows：`bcdedit` 里 `hypervisorlaunchtype = Off`，
WSL2 创建虚拟机时直接报 `HCS_E_HYPERV_NOT_INSTALLED`。
这个开关**只在开机时读一次**，改完必须重启，而且它被关掉大概率是为了 VMware 让路。

**所以当前方案是便携版**：把中间件的 zip 解压到 `.runtime\`，
用脚本启停，不装服务、不写注册表、不改 PATH。**8 个中间件全部覆盖**：

| 中间件 | 端口 | 用途 | 启动器 |
|---|---|---|---|
| MySQL 8.0.43 | 3308 | P1/P2/P3 | `svc.cmd` |
| MySQL 5.7.44 | 3307 | P0（8.0 保留字问题） | `svc.cmd` |
| Redis 8.10.2 | 6380 | P0/P2 | `svc.cmd` |
| Nacos 3.0.3 | 8848 / 8849 | P2 注册中心 + 配置中心 | `run-nacos.cmd` |
| MongoDB 7.0.14 | 27017 | P2 mall-portal | `svc.cmd full` |
| Elasticsearch 8.18.8 | 9200 | P2 mall-search | `svc.cmd full` |
| RabbitMQ 4.3.6 | 5672 / 15672 | P2 订单超时取消 | `run-rabbitmq.cmd` |
| MinIO | 9000 / 9001 | P2 对象存储 | `run-minio.cmd` |
| Ollama 0.34.4 | 11434 | **P1 的本地大模型**（免 API key） | `run-ollama.cmd` |

```bash
./svc.sh start          # 日常：mysql8 + mysql57 + redis
./svc.sh start full     # 跑 P2：再加 nacos + mongo + es + rabbitmq + minio
./svc.sh status         # 一次看完
```

| 方案 | 优点 | 缺点 |
|---|---|---|
| **便携版（现在用）** | 零系统改动、无需重启、删目录即卸载、8 个中间件全覆盖 | 需要自己写启动器（本仓库就是干这个的） |
| Docker（等重启后） | 一条命令起全套 | 需要重启 + 可能拖慢 VMware |

完整分析、以及「什么时候该切到 Docker、怎么切」写在 `docs/runtime.md` 第 1 节。

> `docker-compose.yml` 保留着，配置都是好的，重启开 Hyper-V 之后就能直接用。
> 里面的 `sql/01-schemas.sql` 挂载路径和便携版共用同一份，不存在两套配置漂移的问题。

---

## 6. 数据库账号

| 项 | 值 | 说明 |
|---|---|---|
| MySQL root 密码 | `123456` | 只监听 `127.0.0.1`，不对局域网暴露 |
| MySQL 业务账号 | `dev` / `dev123456` | 对各 schema 有全部权限，应用配置里建议用这个 |
| MySQL 端口 | `3307`（5.7）/ `3308`（8.0） | |
| Redis 密码 | 无 | 同样只监听 `127.0.0.1` |
| Redis 端口 | `6380` | 按 DB 隔离：DB1 eladmin / DB2 mall / DB3 yu_ai_agent / DB4 seckill |

> ⚠️ 这些是**本地开发用的弱口令**，只绑定 127.0.0.1，不要拿去任何有外网的环境。

四个 schema 在**两个 MySQL 实例里都建了**：

| schema | 归属 |
|---|---|
| `eladmin` | P0 |
| `yu_ai_agent` | P1 |
| `mall` | P2 / P3 |
| `seckill` | P3 |

用不到的空着就是了，省得以后切项目还要回来补建。

### 应用配置里怎么写

```yaml
spring:
  datasource:
    url: jdbc:mysql://127.0.0.1:3308/mall?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&useSSL=false&allowPublicKeyRetrieval=true
    username: dev
    password: dev123456
  data:
    redis:
      host: 127.0.0.1
      port: 6380
      database: 2          # DB2 = mall
```

> `serverTimezone=Asia/Shanghai` 不能省 —— 不加的话 JDBC 会按 UTC 解释时间，
> 取到的时间差 8 小时。`allowPublicKeyRetrieval=true` 是给 MySQL 8 的
> `caching_sha2_password` 兜底的（虽然我们已经强制了 native password，写上无害）。

---

## 7. 已知的坑（提前知道能省几小时）

1. **`javax` / `jakarta` 不能混** —— 见第 1 节。任何时候都不要试图把 P0 和 P1/P2 的依赖放到同一个 `pom.xml` 里。
2. **MySQL 5.7 vs 8.0 的保留字** —— MySQL 8 里 `rank` / `groups` / `system` / `window` 是保留字，
   老项目（尤其 eladmin）的建表 SQL 里可能有裸用这些词做列名的，在 8.0 上会报错。
   这就是为什么 P0 单独给了个 5.7 容器，而不是和大家共用一个 8.0。
3. **MySQL 8 的认证插件** —— 已强制 `mysql_native_password`，
   否则老版本 JDBC 驱动会报 `Unable to load authentication plugin 'caching_sha2_password'`。
4. **`lower_case_table_names`** —— 已在启动参数里固定为 `1`（Windows 上 MySQL 的默认行为）。
   这个参数**只能在数据目录初始化时设定**，中途改会让 MySQL 起不来。
   所以如果你以后要改，必须 `docker compose down -v` 清掉数据卷重来。
5. **端口不要写死** —— 全部用 `127.0.0.1:xxxx:yyyy` 形式绑定到本机，不暴露到局域网。
6. **首次启动要等** —— MySQL 初始化数据目录需要 30–60 秒，`healthcheck` 变绿才算好。
   `docker compose up -d` 之后请等一下再连，别急着判断「连不上」。
7. **Redis 的 msys2 构建不认命令行里的绝对路径** ——
   它会无视盘符，把绝对路径拼到当前工作目录后面，报
   `can't open config file '/.runtime/redis/D:\...\redis.conf'`。
   正斜杠、反斜杠、`/d/...` 三种写法全试过，都失败。
   但**配置文件内部**的绝对路径是好的（`dir` / `logfile` 都正常）。
   所以 `svc.cmd` 里是「切工作目录 + 传裸文件名」，官方自带的 `start.bat` 也是这么干的。
8. **`.cmd` 文件里绝对不要写非 ASCII 字符** ——
   cmd 用 OEM 代码页（中文 Windows 上是 GBK）读 `.cmd`，而这个文件是 UTF-8。
   中文注释会变成乱码，而且**乱码会从 `REM` 行里漏出来被当命令执行**
   （已经在 `svc.cmd` 上踩过一次，启动时莫名报 `'xxx' 不是内部或外部命令`）。
   `svc.cmd` 现在是纯 ASCII 的，改它的时候请保持。
9. **`REM` 挡不住 `&`** —— 同一行里有 `&` 的话，后半行会被当成新命令执行。
   注释里要提 `&`，改成写 "and" 或者拆到另一行。

---

## 8. 回滚

```bash
# 只清数据，保留程序（下次 init 会重新初始化）
./svc.sh stop
rm -rf .runtime/data/mysql8 .runtime/data/mysql57 .runtime/data/redis/*
./svc.sh init

# 彻底删掉运行时（8 个中间件 + 模型，约 6 GB）
./svc.sh stop
rm -rf /d/java-workspace/.runtime

# 连便携版 JDK 一起删
rm -rf /d/java-workspace/.jdks
```

想彻底不要这个工作区：直接删掉 `D:\java-workspace` 整个目录。

**系统里没有任何残留需要清理** ——
没装服务、没写注册表、没改 PATH、没动 `JAVA_HOME`。
系统原有的 JDK 17 一个字节都没变过。

---

## 9. 怎么验证「真的跑起来了」

**不看日志关键字，只看两个东西：端口在不在听，接口有没有返回真实业务数据。**

`tools/` 下的脚本就是干这个的：

```bash
cd /d/java-workspace

# P0：登录链路
python tools/p0-login-test.py

# P1：24 项断言（Ollama / 应用基础 / 同步对话 / SSE 流式 / Agent 工具调用 / 日志体检）
python tools/p1-e2e-test.py

# P2：全链路（网关 → auth → Feign → admin → MySQL → Redis）
python tools/p2-e2e-test.py

# P4（本工作区原创项目）：86 项断言，脚本在它自己的仓库里
cd /d/java-workspace/p4-exam-tracker
python tools/p4-e2e-test.py
```

P4 的 86 项断言分 9 组：探针/文档、注册登录、**未认证 → JSON 401**、任务 CRUD 与通配符转义、
打卡（科目从任务推导 / 未来日期拒绝）、统计（连续天数 / 倒计时 / 窗口折算）、
**数据隔离（B 用户对 A 的数据全部 404）**、删除保护（409 → `force=true`）、日志体检。
实测结果：**86/86 PASS**。
设计原则写在脚本的 docstring 里，核心是两条：

1. **只看 HTTP 200 不够** —— 200 也可能是一段错误提示文本。
   所以脚本内置 `ERROR_SIGNS` 和 `looks_like_real_answer()`，
   **200 + 文本像人话**才算过。
2. **日志里"成功关键字"也可能是假的** —— Nacos 会先打印
   `started successfully` 再因为端口冲突失败。判断存活要看端口，不要看日志。

> ⚠️ 本机系统代理会劫持回环地址，`curl http://127.0.0.1:...` 会超时。
> 脚本用 `http.client` 直连（等价于 `curl --noproxy '*'`）。
> 手工 curl 时记得加 `--noproxy '*'`。

---

## 10. 项目工作台（dashboard）

五个项目各用各的 JDK、各有各的前置中间件、各有各的端口。想跑起任何一个，
都得先记住「用哪个 JDK、要不要先起中间件」。这份记忆分散在 6 份文档里，
而且**忘了一步不会报「你忘了一步」，只会报一堆看不懂的错**。

工作台把这些收进一份声明式清单，并且真的能替你把步骤跑完。

**双击 `dashboard\start.cmd`** 就能用 —— 它自己找 Python、起服务、把控制台落到日志里；
已经在跑的时候再点一次，只把浏览器打开，不会起第二个实例。停止用 `dashboard\stop.cmd`（幂等）。

也可以直接跑服务：

```bash
cd /d/java-workspace
python dashboard/server.py        # 打开 http://127.0.0.1:8990/
```

**能做什么**：卡片/列表双视图，按状态、类别、来源、标签筛选 + 关键词搜索；
一键启动（自动切 JDK、自动起中间件、轮询端口到就绪）、一键停止、一键打开；
详情抽屉里有启动命令原文、逐步骤的启动日志、应用日志；底部可展开看 9 个中间件状态。

**加项目**：只改 `dashboard/projects.json`，页面右上角「＋ 新增项目」有模板和步骤说明。

**零依赖**：标准库 `http.server` + 原生 JS/CSS。这个工作区的卖点是「删掉目录就等于没来过」，
引入 `pip install` / `npm install` 就破坏了这个前提。

### 实测启动耗时（2026-09-29）

| 项目 | 耗时 | 说明 |
|---|---|---|
| P4 exam-tracker | 12.8s | 含自动拉起 MySQL 8 |
| P0 eladmin-mp | 11.6s | 含自动拉起 MySQL 5.7 + Redis，JDK 8 |
| P1 yu-ai-agent | 32.6s | 含自动拉起 Ollama，JDK 21 |
| P2 mall-swarm | 166s | 含自动拉起 5 个中间件，7 个模块全部就绪 |
| P3 seckill | — | 拒绝启动并说明原因（还没有代码） |

界面验证：`dashboard/verify-ui.js`，真浏览器 **65 项断言全通过**，
输出桌面/平板/手机/深色四档截图到 `docs/screenshots/`。

### ⚠️ 两个必须知道的环境冲突

1. **`5672` 被 `WorkBuddyAI.exe` 占着**（宿主客户端自己也用了这个端口）。
   RabbitMQ 起不来，`mall-portal` 的 RabbitMQ 监听器会持续报
   `Frame body is too large (1345270062)` —— 它在跟 WorkBuddy 说话。
   要跑完整的 P2，得先关掉 WorkBuddy 客户端，或者把 RabbitMQ 换端口。
   > 注意：`svc.sh status` 会把这个端口报成 `RabbitMQ LISTENING`，**那是误报**。
   > 工作台会核验占用端口的进程名，所以能正确标成「端口被占用」。

2. **`svc.sh start` 只接受一个 target**（`svc.cmd` 里是 `set "TARGET=%~2"`）。
   写成 `svc.sh start mysql57 redis` 只会起 mysql57，第二个被**静默忽略**，退出码还是 0。

### ⚠️ 两个「只在双击启动时才犯」的错（已修）

工作台从 WorkBuddy 的 bash 里启动时一切正常，**双击 `start.cmd` 时却完全起不来**。
两个原因都属于「测试环境比用户环境更宽容」，细节见 [`dashboard/README.md`](dashboard/README.md) 第 6.9 / 6.10 节：

1. **`print()` 在 GBK 的 stdout 上会抛 `UnicodeEncodeError`**。bash 注入了 `PYTHONUTF8=1`，
   所以测不出来；双击启动走 PowerShell → cmd，编码是 GBK，日志里的 `❌` 和 U+FFFD 直接
   把线程打死，前端永远停在「启动中」。
2. **`shutil.which("bash")` 命中 `C:\Windows\System32\bash.exe`** —— 那不是 bash，
   是 WSL 的启动器。普通 PATH 里它排在 Git 的 bash 前面，于是所有中间件都起不来，
   报的还是 UTF-16 编码的 `HCS_E_HYPERV_NOT_INSTALLED`（读出来是一片乱码）。

完整的设计说明、以及 12 个踩过的坑（含复现方式）写在 [`dashboard/README.md`](dashboard/README.md)。
