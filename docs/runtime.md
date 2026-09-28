# 运行环境（便携版中间件全套）

> 2026-09-28 建立，同日扩到 **8 个服务 + 2 个配套工具**。
> **本机不装任何数据库/中间件服务**，全部走解压即用的便携版，
> 放在 `D:\java-workspace\.runtime\`。删目录 = 完全卸载。

| 服务 | 版本 | 端口 | 服务于 |
|---|---|---|---|
| MySQL 8.0 | 8.0.43 | 3308 | P1 / P2 / P3 |
| MySQL 5.7 | 5.7.44 | 3307 | **P0** |
| Redis | 8.10.2 | 6380 | P0 / P2 / P3 |
| Nacos | 3.0.3 | 8848 / 8849 / 9848 | **P2** |
| MongoDB | 7.0.14 | 27017 | **P2** |
| Elasticsearch | 8.18.8 | 9200 | **P2** |
| Erlang/OTP | 28.5.0.7 | 4369 (epmd) | RabbitMQ 的运行时 |
| RabbitMQ | 4.3.6 | 5672 / 15672 | **P2** |
| MinIO | RELEASE.2025-07-23 | 9000 / 9001 | **P2** |

配套命令行工具（不是服务，但都在 `.runtime` 里）：
`.runtime\minio\mc.exe`（MinIO 客户端）、`.runtime\mongodb\bin\mongosh.exe`（MongoDB shell）。

> **P2 的中间件全家桶已经齐了。** 不需要 Docker。

---

## 1. 为什么没用 Docker

本来首选是 Docker（一条命令起全套，P2 微服务那堆 Nacos/ES/MQ/MinIO 更是非 Docker 不可），
但实测 Docker Desktop **起不来**，根因不在 Docker，在 Windows：

| 检查项 | 结果 |
|---|---|
| 机器 | ASUS 实机 / AMD Ryzen 5 5600，不是虚拟机 |
| CPU 虚拟化 | `VirtualizationFirmwareEnabled: True`，SLAT ✅ |
| `Microsoft-Windows-Subsystem-Linux` | Enabled ✅ |
| `VirtualMachinePlatform` | Enabled ✅ |
| **`hypervisorlaunchtype`（bcdedit）** | **Off** ❌ |
| `Microsoft-Hyper-V` | Disabled（被连带关掉） |

WSL2 需要的两个 Windows 功能**都是开着的**，但引导时不启动 Windows 虚拟机监控程序，
所以 WSL2 创建虚拟机时直接失败：

```
Wsl/Service/CreateInstance/CreateVm/HCS/HCS_E_HYPERV_NOT_INSTALLED
```

`hypervisorlaunchtype` **只在开机时读一次**，改完必须重启。

而且它被设成 `Off` 大概率是**主动为之** —— 这台机器上有 `D:\VMware`，
开着 Hyper-V 会让 VMware Workstation 的虚拟机走慢速兼容路径。
所以这不是一个「顺手改掉」的开关，是个需要权衡的决定。

**当前选择：全部走便携版，Docker 的事以后再说。**

### 后来的修正：便携版把 P2 全套都覆盖了

最初判断是「P2 要的 Nacos + MongoDB + Elasticsearch + RabbitMQ + MinIO
在 Windows 上没有靠谱便携版，基本必须上 Docker」。
**逐个试下来，五个全部装成了**，Docker 在这个项目里已经不是必需品：

| 组件 | 当初的判断 | 实测结论 |
|---|---|---|
| Nacos | 不确定 | ✅ 官方 Windows zip |
| MongoDB | 不确定 | ✅ 官方 Windows zip |
| Elasticsearch | 不确定 | ✅ 官方 Windows zip（自带 JDK） |
| RabbitMQ | 「必须上 Docker」 | ✅ **Erlang 也有官方 zip**，见下 |
| MinIO | 「拿不到」 | ✅ **中国镜像还活着**，见下 |

### RabbitMQ：Erlang 官方也发 zip，所以不用装系统组件

当初的顾虑是「RabbitMQ 的 Windows 版依赖 Erlang/OTP，而 Erlang 只有安装程序，
会写注册表 + PATH」。**这个顾虑不成立** —— Erlang/OTP 在 GitHub Release 里
同时提供 `.exe` 安装程序和 **`.zip` 免安装包**：

```
https://github.com/erlang/otp/releases/download/OTP-28.5.0.7/otp_win64_28.5.0.7.zip
```

所以做法和别的服务完全一样：解压到 `.runtime\erlang\`，
启动器里 `set ERLANG_HOME=` 指过去即可。**没装 Erlang 运行时、没改 PATH、没写注册表。**

> Erlang 的 zip 里确实带了个 `vc_redist.exe`，但实测**本机已经有 VC++ 运行库**，
> `erl.exe` 直接就能跑，不需要装它。

### MinIO：「上游归档」不等于「拿不到」

当初看到 `dl.min.io` 对所有社区版构建（server / `mc` / KES）统一返回
**410 Gone**，就下了「MinIO 拿不到」的结论。**这个结论是错的。**

`dl.min.io`（官方源）确实死了，项目也确实归档了，但**中国镜像还在服务**：

```
https://dl.minio.org.cn/server/minio/release/windows-amd64/minio.exe      -> 200
https://dl.minio.org.cn/client/mc/release/windows-amd64/mc.exe            -> 200
```

而且镜像**提供 sha256 校验和**，并且校验和文件里写明了对应的上游版本号，
所以能确认拿到的是原版二进制而不是被改造过的：

| 文件 | 本地实算 sha256 | 与镜像声明比对 |
|---|---|---|
| `minio.exe` | `4c7c7b6e...bb61b517` | ✅ 一致（`minio.RELEASE.2025-07-23T15-54-02Z`） |
| `mc.exe` | `5a563196...ba5931bd` | ✅ 一致（`mc.RELEASE.2025-07-21T05-28-08Z`） |

> **教训**：一条下载路径失败 ≠ 这个软件不存在。
> 当时只试了 `dl.min.io` 就下结论，没有去试镜像站。
> 这和用户级记忆里「空结果先怀疑查询本身，不先下结论」是同一类错误。

### 所以什么时候才真的需要 Docker
目前**没有必须用 Docker 的场景**了。只有这两种情况才值得考虑：
1. 想跑官方支持的 **Kafka / RocketMQ** 之类没有靠谱 Windows 便携版的组件（P3 可能会遇到）
2. 想要「一条命令重建整套环境」的体验

到时的操作（需要管理员权限 + 重启）：


```bat
REM 以管理员身份运行
bcdedit /set hypervisorlaunchtype auto
dism /online /enable-feature /featurename:Microsoft-Hyper-V /all /norestart
dism /online /enable-feature /featurename:HypervisorPlatform /all /norestart
REM 然后重启
```

重启回来后：

```bash
cd /d/java-workspace
docker compose up -d              # 只起 core
docker compose --profile swarm up -d   # 起微服务全家桶（约 4 GB 内存）
```

> ⚠️ 开 Hyper-V 前先想清楚：如果你还在用 VMware 跑虚拟机，它的性能会下降。
> 想改回去：`bcdedit /set hypervisorlaunchtype off` 再重启。

---

## 2. 装了什么

| 组件 | 版本 | 位置 | 端口 | 下载体积 |
|---|---|---|---|---|
| MySQL | **8.0.43** | `.runtime\mysql-8.0\` | `3308` | ~1.5 GB |
| MySQL | **5.7.44** | `.runtime\mysql-5.7\` | `3307` | ~1.5 GB |
| Redis | **8.10.2**（Windows 移植版） | `.runtime\redis\` | `6380` | ~40 MB |
| Nacos | **3.0.3** | `.runtime\nacos\nacos\` | `8848` / `8849` / `9848` | 187 MB（zip） |
| MongoDB | **7.0.14** | `.runtime\mongodb\` | `27017` | 592 MB（zip） |
| Elasticsearch | **8.18.8** | `.runtime\elasticsearch\` | `9200` | 480 MB（zip） |
| Erlang/OTP | **28.5.0.7** | `.runtime\erlang\` | `4369` (epmd) | 176 MB（zip，解压后 ~466 MB） |
| RabbitMQ | **4.3.6** | `.runtime\rabbitmq\rabbitmq_server-4.3.6\` | `5672` / `15672` | 67 MB（zip） |
| MinIO | **RELEASE.2025-07-23** | `.runtime\minio\minio.exe` | `9000` / `9001` | 107 MB（单文件） |
| mc（MinIO 客户端） | **RELEASE.2025-07-21** | `.runtime\minio\mc.exe` | — | 30 MB（单文件） |
| **Ollama** | **0.34.4** | `.runtime\ollama\ollama.exe` | `11434` | 1393 MB（zip，解压后 1.8 GB） |
| ↳ 模型 `qwen3:0.6b` | — | `.runtime\ollama\models\` | — | 522 MB（chat，**P1 当前默认**） |
| ↳ 模型 `gemma3:1b` | — | 同上 | — | ~815 MB（chat，**不支持 tools**） |
| ↳ 模型 `nomic-embed-text` | — | 同上 | — | ~274 MB（embedding，768 维） |

> **Ollama 是 2026-09-28 新加的**，用途见 `run-p1.md`：
> 给 P1（yu-ai-agent）提供本地 chat + embedding，从而**不需要 DashScope API key** 就能跑。
> 启动器：工作区根目录的 **`run-ollama.cmd`**（和 `run-minio.cmd` / `run-nacos.cmd` 同一套写法）。
>
> **它是 P1 现在唯一的硬依赖** —— 不起 Ollama，P1 起不来。
>
> ⚠️ **两个必须钉死的环境变量**（`run-ollama.cmd` 里已经设好）：
> - `OLLAMA_MODELS` —— 不设的话模型会落到 `%USERPROFILE%\.ollama\models`，
>   跑到工作区外面去（和 Erlang cookie 当年那个问题同一类）。
> - `OLLAMA_HOST=127.0.0.1:11434` —— Ollama **没有任何鉴权**，
>   绑到 `0.0.0.0` 等于把整台机器的算力送给同 Wi-Fi 的人。
>
> ⚠️ **本机 curl 访问回环地址要加 `--noproxy '*'`**。实测
> `curl http://127.0.0.1:11434/api/version` 会超时，加上 `--noproxy '*'` 立刻返回
> `{"version":"0.34.4"}` —— 系统级代理把回环地址也劫持了。
> 这只影响 curl，Java 的 RestClient 默认不读系统代理，不受影响。

> **下载缓存（2026-09-28 已清理，释放约 2.5 GB）**
> 原来有两处缓存，内容全部是「已经解压完毕的安装包」，删掉不影响运行：
>
> | 位置 | 体积 | 内容 |
> |---|---|---|
> | `_dl\` | 2.2 GB | 9 个 zip：es / jdk21 / jdk8 / mongodb / mongosh / mysql57 / mysql80 / nacos / redis |
> | `.runtime\_dl\` | 361 MB | minio.exe、otp_win64(Erlang)、rabbitmq-server、ik 插件 ×2 |
>
> 删除前逐项核对过「解压产物存在 + 关键可执行文件可访问」，13/13 全部命中；
> 删除后 6 个服务端口（5672 / 9200 / 3308 / 27017 / 8848 / 6380）仍在监听，未受影响。
>
> ⚠️ **`svc.sh` / `svc.cmd` 里没有下载逻辑** —— 这两个目录是安装包的**唯一本地副本**。
> 换机器或重装时需要按下面的来源重新下载。
>
> **还留着的**：`.runtime\_dl\ollama-windows-amd64.zip`（1393 MB）+ `sha256sum.txt`。
> 这个**建议保留** —— Ollama 现在是 P1 的硬依赖，zip 留在本地意味着
> 万一 `.runtime\ollama\` 坏了可以离线秒重建，不必联网重下 1.4 GB。
> 确实要腾空间再删：
> ```bash
> rm -f "D:/java-workspace/.runtime/_dl/ollama-windows-amd64.zip" \
>       "D:/java-workspace/.runtime/_dl/sha256sum.txt"
> ```
>
> **Erlang cookie 归档**：`%USERPROFILE%\.erlang.cookie` 与 `.erlang.cookie.moved`
> 已移到 `.runtime\_archive\erlang-cookie-20260928\`（md5 与原值一致）。
> 它们与 RabbitMQ **无关** —— `run-rabbitmq.cmd` 会把 `HOMEDRIVE`/`HOMEPATH`
> 重定向到 `.runtime\data\rabbitmq\`，broker 和 `rabbitmqctl` 都用那里面的 cookie。
> 实测：移走 home 目录的 cookie 后 `run-rabbitmq.cmd ctl status` 依然正常。

来源：
- MySQL：`https://dev.mysql.com/get/Downloads/MySQL-8.0/mysql-8.0.43-winx64.zip`（官方 ZIP Archive，**不是** Installer）
- MySQL 5.7：`https://dev.mysql.com/get/Downloads/MySQL-5.7/mysql-5.7.44-winx64.zip`
- Redis：`https://github.com/redis-windows/redis-windows` 的 `Redis-8.10.2-Windows-x64-msys2.zip`
- Nacos：`https://github.com/alibaba/nacos/releases` 的 `nacos-server-3.0.3.zip`
- MongoDB：`https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-7.0.14.zip`
  （另单独下了 `mongosh` —— **7.0 的 zip 不再自带 `mongosh`**）
- Elasticsearch：`https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-8.18.8-windows-x86_64.zip`
- Erlang：`https://github.com/erlang/otp/releases/download/OTP-28.5.0.7/otp_win64_28.5.0.7.zip`（**免安装 zip，不是 .exe 安装程序**）
- RabbitMQ：`https://github.com/rabbitmq/rabbitmq-server/releases/download/v4.3.6/rabbitmq-server-windows-4.3.6.zip`
- MinIO：`https://dl.minio.org.cn/server/minio/release/windows-amd64/minio.exe`（**中国镜像**，官方源 `dl.min.io` 已 410）
- mc：`https://dl.minio.org.cn/client/mc/release/windows-amd64/mc.exe`
- **Ollama**：`https://github.com/ollama/ollama/releases/download/v0.34.4/ollama-windows-amd64.zip`
  （**免安装 zip，不是 `OllamaSetup.exe`**；下载后 `sha256sum` 已与 release 页的 `sha256sum.txt` 核对一致。
  模型不随包发布，要单独 `ollama pull`。）

> Redis 官方**没有 Windows 版**。这里用的是社区维护的 `redis-windows/redis-windows`，
> 比更常见的 `tporadowski/redis`（停在 Redis 5.0）新得多。
> 选 `msys2` 那个构建而不是 `cygwin`：msys2 的性能和兼容性都更好。

### 为什么 Erlang 选 28.5.0.7 而不是最新的 29.x
RabbitMQ 对 Erlang 版本是**强校验**的，选错了起不来。查官方兼容表得到：

| RabbitMQ | 支持的 Erlang |
|---|---|
| 4.3.6 | 最低 **27.0**，最高 **28.x**（29 从 4.3.6 起才支持，属新边界） |
| 4.3.0 ~ 4.3.5 | 最低 27.0，最高 27.x |
| 4.0.x / 4.1.x / 4.2.0~4.2.8 | 最低 26.2，最高 27.x |

**28.5.0.7 稳稳落在 4.3.6 的区间内**，且 28.5 带了后量子密码支持。
29.1.1 虽然 4.3.6 声称支持，但官方同时提示「并非所有软件包都已把 29 列为受支持版本」，
所以不选它 —— 没必要为了版本号新一点去踩边界。

### 为什么 MinIO 的 root 账号是 `minioadmin/minioadmin`
这是 MinIO 的默认弱口令，本来该改。**但这里故意不改** ——
因为 mall-admin 的配置里写死了这个值：

```yaml
# config/admin/mall-admin-dev.yaml
minio:
  endpoint: http://localhost:9000
  bucketName: mall
  accessKey: minioadmin
  secretKey: minioadmin
```

改了 MinIO 这边而不同步改 Java 那边，上传就会 403。
安全边界靠 `--address 127.0.0.1:9000` 锁在回环地址上。
（MinIO 启动时会对默认口令发 WARN，那是预期的，不用管。）

### 为什么两个 MySQL
MySQL 8 把 `rank` / `groups` / `system` / `window` 变成了**保留字**。
老一代项目（尤其 eladmin 那一代）的建表 SQL 里常有裸用这些词当列名的，在 8.0 上直接语法错误。
与其去改人家的 SQL，不如给 P0 单独一个 5.7 实例 —— 一个实例约 300 MB 内存，换掉一堆玄学问题。

**如果 P0 在 8.0 上跑通了，5.7 这个实例可以整个删掉。**

### Nacos 3.x 的两个坑（和 2.x 的教程完全不一样）
网上绝大多数 Nacos 教程写的是 **2.x**，照抄会踩两个坑：

| | 2.x（网上教程） | **3.x（本工作区）** |
|---|---|---|
| 控制台地址 | `http://localhost:8848/nacos` | **`http://localhost:8849/`**（**根路径**，不是 `/nacos`） |
| 控制台端口 | 复用 8848 | **独立端口**，`nacos.console.port`，默认 8080 |
| 登录接口 | `/nacos/v1/auth/...` | **`/nacos/v3/auth/...`**，且**分端口** |

`nacos.console.port` 默认是 **8080** —— 而工作区里 8080 留给 mall-swarm 的 `mall-admin`，
所以改到了 **8849**。三个端口各管什么：

| 端口 | 用途 | 鉴权 |
|---|---|---|
| `8848` | **客户端 API**（服务注册发现、配置读写） | **无** |
| `8849` | **控制台 Web UI** | 有 |
| `9848` | gRPC（2.x 起客户端走 gRPC 而非 HTTP） | — |

另外 **Nacos 3.0 起有三个鉴权属性必须非空**，否则启动时会**交互式索要**（`set /p`），
非交互脚本直接卡死。已经在 `conf/application.properties` 里填好了。

控制台账号：**`nacos` / `Workspace#2026`**（首次使用需初始化，已初始化过）。

### 为什么 Elasticsearch 必须是 8.x
这个不是随便选的 —— **Java 客户端会强制校验服务端版本**。
mall-swarm 基于 Spring Boot 3.5.14，其 `spring-boot-dependencies-3.5.14.pom` 里写着：

```
elasticsearch-client.version = 8.18.8
```

**8.x 的客户端拒绝连 7.x 的服务端**。一开始按「保守起见装 7.17」的思路下了 7.17.28
（下载地址确实返回 200，能下到），但那个版本到 P2 运行期一定会炸，而且报错信息
不会直接说「版本不匹配」。最后装的 **8.18.8** 和客户端版本严格对齐。

> 8.x 默认开启安全（HTTPS + 账号密码），而 mall-swarm 的配置是裸的 `http://localhost:9200`，
> 所以 `elasticsearch.yml` 里把 `xpack.security.*` 全关了。本机只绑 `127.0.0.1`，
> 这个取舍是可接受的。

### MongoDB 7.0 移除的选项
`storage.journal.enabled` **在 7.0 里被移除了**，写了不是「忽略」而是**直接拒绝启动**：

```
Unrecognized option: storage.journal.enabled
```

而且它退出前**不写日志文件**，所以现象是「服务没起来但日志是空的」——
必须前台跑一次才能看到真正的报错。`mongod.yml` 里已经去掉了这一项。

另外 **7.0 的 Windows zip 不再自带 `mongosh`**，要单独下。

---

## 3. 日常使用

```bash
cd /d/java-workspace

./svc.sh status          # 看 8 个服务谁在跑
./svc.sh start           # 全起（mysql8 + mysql57 + redis）—— 日常用这个
./svc.sh start mysql8    # 只起一个
./svc.sh stop            # 全停（优雅关闭）
./svc.sh cli mysql8      # 开个 mysql 客户端
./svc.sh logs mysql8     # 跟日志
```

### `start` / `stop` 的两个档位（这个区别很重要）

| 命令 | 起哪些 | 什么时候用 |
|---|---|---|
| `start` / `stop`（等价 `all`） | MySQL 8 + MySQL 5.7 + Redis | **每天用这个**。P0 只需要这些 |
| `start full` / `stop full` | `all` + **Nacos + MongoDB + Elasticsearch + RabbitMQ + MinIO** | 跑 P2 时 |

> ⚠️ **P1（yu-ai-agent）不在上面任何一档里** —— 它**一个中间件都不需要**
> （没有数据库、没有 Redis）。它唯一的外部前提是 **Ollama**，
> 而 Ollama **不归 `svc.sh` 管**，要单独用 `run-ollama.cmd` 起。
> 也就是说：跑 P1 时 `svc.sh` 可以完全不动。

**为什么 Nacos 不放进默认的 `all`**：它启动要 ~30 秒、吃 512 MB 内存，
而 P0 和 P1 完全不碰它。默认命令是要天天跑的，保持快才有意义。

`full` 里五个服务的启动耗时差别很大，知道这个能少等冤枉时间：

| 服务 | 大约启动耗时 |
|---|---|
| RabbitMQ | **~4 秒** |
| MinIO | **~4 秒** |
| MongoDB | ~4 秒 |
| Elasticsearch | ~18 秒 |
| Nacos | **~30 秒** |

```bash
./svc.sh start full      # 全套（P2 用），整轮下来约 60 秒
./svc.sh status          # 八个服务的状态一次看完
```

`status` 的输出（实际运行的样子）：

```

  SERVICE          PORT    STATUS       DATA DIR
  --------------------------------------------------------------------------
  MySQL 8.0       3308   LISTENING   D:\java-workspace\.runtime\data\mysql8
  MySQL 5.7       3307   LISTENING   D:\java-workspace\.runtime\data\mysql57
  Redis           6380   LISTENING   D:\java-workspace\.runtime\data\redis
  Nacos           8848   LISTENING   D:\java-workspace\.runtime\nacos\nacos
  MongoDB         27017   LISTENING   D:\java-workspace\.runtime\data\mongodb
  Elasticsearch   9200   LISTENING   D:\java-workspace\.runtime\data\elasticsearch
  RabbitMQ        5672   LISTENING   D:\java-workspace\.runtime\data\rabbitmq
  MinIO           9000   LISTENING   D:\java-workspace\.runtime\data\minio

  Nacos console:  http://127.0.0.1:8849/    (root path -- NOT 8848/nacos)
                  user nacos / Workspace#2026  (admin pw already initialised)
  RabbitMQ mgmt:  http://127.0.0.1:15672/   user mall / mall
                  vhost /mall   (NOT /)
  MinIO console:  http://127.0.0.1:9001/    user minioadmin / minioadmin
                  bucket "mall" (public read)

  Connect with:
    ...
```

判定标准是 **`LISTENING`**，不是「日志里有没有 started」——
Nacos 会先打印 `started successfully` 再因为端口冲突失败（见第 7 节）。

> 服务名是手工补空格对齐的（cmd 的 `echo` 没有 printf 式的补位），
> 所以看起来有点不齐 —— 那是显示问题，不影响 `LISTENING` 这个判断。

Windows cmd 里把 `./svc.sh` 换成 `svc.cmd` 即可，参数完全一样。

> Git Bash 里**直接执行** `./svc.sh` 就行，不需要 `source` ——
> 它不改环境变量，只负责转发给 `svc.cmd`（真正的实现）。

> ⚠️ **`svc.sh` 不能带 `MSYS_NO_PATHCONV=1` 跑。** 它第 52 行的 `cmd //c`
> **依赖** Git Bash 把 `//c` 改写成 `/c`；把路径转换关掉之后，
> cmd 会打印一段 MSYS 风格的横幅然后立刻退出，什么都不做、也不报错。
> （2026-09-28 实测踩到，症状极像"脚本坏了"。）

### Ollama（不归 `svc.sh` 管）

```bash
/d/java-workspace/run-ollama.cmd      # 前台常驻，另开一个窗口
```

它**不在 `svc.sh` 的 8 个服务里**，`status` 也看不到它。单独验证：

```bash
curl --noproxy '*' http://127.0.0.1:11434/api/version   # {"version":"0.34.4"}
curl --noproxy '*' http://127.0.0.1:11434/api/tags      # 已安装模型列表
ollama list                                            # 同上，更好读
ollama show qwen3:0.6b                                 # 看 capabilities 里有没有 tools
```

停：在那个窗口 `Ctrl+C`，或 `taskkill //F //IM ollama.exe`。
> 之所以让 cmd 干脏活：Git Bash 会把 `/min`、`/D` 这类开关当成路径去转换，
> 启动命令会莫名其妙地失败。放在 .cmd 里执行就绕开了。

### 首次初始化（已经做过了，重装时才需要）

```bash
./svc.sh init
```

它做四件事：建数据目录 → 启动三个服务 → 设 root 密码 → 建库建账号。

---

## 4. 连接信息

| | 地址 | 账号 | 密码 |
|---|---|---|---|
| MySQL 8.0 | `127.0.0.1:3308` | `root` / `dev` | `123456` / `dev123456` |
| MySQL 5.7 | `127.0.0.1:3307` | `root` / `dev` | `123456` / `dev123456` |
| Redis | `127.0.0.1:6380` | — | 无 |
| Nacos 客户端 API | `127.0.0.1:8848` | — | **无鉴权** |
| Nacos 控制台 | `127.0.0.1:8849`（根路径 `/`） | `nacos` | `Workspace#2026` |
| MongoDB | `127.0.0.1:27017` | — | **无鉴权** |
| Elasticsearch | `127.0.0.1:9200` | — | **无鉴权** |
| RabbitMQ AMQP | `127.0.0.1:5672`，**vhost `/mall`** | `mall` | `mall` |
| RabbitMQ 管理台 | `127.0.0.1:15672` | `mall` | `mall` |
| MinIO API | `127.0.0.1:9000`，bucket **`mall`** | `minioadmin` | `minioadmin` |
| MinIO 控制台 | `127.0.0.1:9001` | `minioadmin` | `minioadmin` |

**全部只绑 `127.0.0.1`**，同 Wi-Fi 下的其他设备连不上，所以弱口令 / 无鉴权在这个范围内是可接受的。
**但不要把这套配置搬到任何有外网的环境。**

> **这些账号密码不是我随便定的，是照着 mall-swarm 的配置反向对齐的。**
> 改这里而不同步改 Java 配置，就会连不上：
>
> | 服务 | 凭据来源文件 |
> |---|---|
> | RabbitMQ | `config/portal/mall-portal-dev.yaml` → `username: mall` / `password: mall` / `virtual-host: /mall` |
> | MinIO | `config/admin/mall-admin-dev.yaml` → `accessKey: minioadmin` / `secretKey: minioadmin` / `bucketName: mall` |
>
> MongoDB 和 ES 是**故意不开鉴权**的 —— mall-swarm 的配置里
> 既没有 MongoDB 账号密码，ES 也是裸的 `http://localhost:9200`。
> 开了鉴权反而会连不上。安全边界完全靠 `bindIp` / `network.host` 锁在回环地址上。

### 数据库划分

| schema | 归属 | 建在 |
|---|---|---|
| `eladmin` | P0 | 两个实例都有 |
| `yu_ai_agent` | P1 | 两个实例都有 |
| `mall` | P2 / P3 | 两个实例都有 |
| `seckill` | P3 | 两个实例都有 |

四个 schema 在两个实例里都建了 —— 用不到的空着就是了，
省得以后切项目还要回来补建。

### Redis 的库隔离
`redis.conf` 里 `databases 16`。约定：
DB1 eladmin / DB2 mall / DB3 yu_ai_agent / DB4 seckill。
Spring 配置里写 `spring.data.redis.database: 2` 这种即可。

---

## 5. 配置文件

### 自己写的（统一放 `.runtime\conf\`）
| 文件 | 作用 |
|---|---|
| `mysql8.ini` | MySQL 8.0 配置（端口、字符集、兼容性开关、日志路径） |
| `mysql57.ini` | MySQL 5.7 配置 |
| `redis.conf` | Redis 配置（端口、AOF、内存上限） |
| `mongod.yml` | MongoDB 配置（端口、`dbPath`、日志） |

### 放在「默认位置」的（因为放默认位置能绕开一个歧义）
| 文件 | 作用 |
|---|---|
| `.runtime\data\rabbitmq\rabbitmq.conf` | RabbitMQ 配置 —— 这是 `RABBITMQ_BASE` 下的**默认**配置位置，所以不用设 `RABBITMQ_CONFIG_FILE`（避开「要不要带 `.conf` 后缀」那个歧义） |
| `.runtime\data\rabbitmq\enabled_plugins` | RabbitMQ 启用的插件（`[rabbitmq_management].`） |

### 改的是发行包自带的（位置没法选）
| 文件 | 作用 |
|---|---|
| `.runtime\nacos\nacos\conf\application.properties` | Nacos（控制台端口、鉴权密钥）—— 原文件备份为 `application.properties.orig` |
| `.runtime\elasticsearch\config\elasticsearch.yml` | ES（端口、`path.data`、关安全）—— 改动**追加在文件末尾** |

> ES 那个文件有 1000 多行官方注释，改动是**追加在最后一行官方注释之后**的一个
> 「工作区块」，用注释标出来了，好找也好回退。

改完配置要重启对应服务才生效：`./svc.sh restart mysql8`。

> **RabbitMQ 的 `default_user` / `default_pass` / `default_vhost` 只在首次启动生效**
> （mnesia 还是空的时候）。之后改 `rabbitmq.conf` 里这三个键没有任何效果 ——
> 要改就得用 `run-rabbitmq.cmd ctl ...`，或者删掉 `.runtime\data\rabbitmq\db` 重来。

### 里面几个「不设就会出问题」的开关

| 配置 | 值 | 不设会怎样 |
|---|---|---|
| `lower_case_table_names` | `1` | Windows 上不区分表名、Linux 上区分。不统一的话，本地跑得好好的，部署到 Linux 才炸 |
| `default-authentication-plugin` | `mysql_native_password` | MySQL 8 默认 `caching_sha2_password`，老 JDBC 驱动报 `Unable to load authentication plugin` |
| `sql-mode` 去掉 `ONLY_FULL_GROUP_BY` | — | 老项目里「SELECT 了没 GROUP BY 的列」的写法会直接报错 |
| `default-time-zone` | `+08:00` | JDBC 取到的时间差 8 小时 |
| `character-set-server` | `utf8mb4` | emoji / 生僻字存不进去 |
| Redis `maxmemory` | `512mb` | Redis 会一直吃内存直到把机器吃满 |

> `lower_case_table_names` **只能在数据目录初始化时设定**。
> 中途改会让 MySQL 直接起不来。要改就得删掉 `.runtime\data\mysql8` 重新初始化 ——
> 也就是数据全丢。这就是为什么它必须一开始就写对。

---

## 6. 数据在哪 / 怎么重置

| 内容 | 路径 |
|---|---|
| MySQL 8.0 数据 | `.runtime\data\mysql8\` |
| MySQL 5.7 数据 | `.runtime\data\mysql57\` |
| Redis 数据 | `.runtime\data\redis\` |
| Nacos 数据 | `.runtime\nacos\nacos\data\` |
| MongoDB 数据 | `.runtime\data\mongodb\` |
| Elasticsearch 数据 | `.runtime\data\elasticsearch\` |
| **RabbitMQ 数据 + 配置 + 日志** | `.runtime\data\rabbitmq\`（mnesia 在 `db\`，日志在 `log\`） |
| **MinIO 数据** | `.runtime\data\minio\`（bucket `mall` 的对象就在这，另有 `mc\` 存 mc 的配置） |
| Erlang 运行时 | `.runtime\erlang\` |
| **Ollama 程序 + 模型** | `.runtime\ollama\`（模型在 `models\`，约 1.6 GB） |
| 下载包残留 | `.runtime\_dl\`（只剩 Ollama 的 zip，1393 MB，见第 2 节的说明） |
| 日志 | `.runtime\logs\` |
| 归档 | `.runtime\_archive\`（Erlang cookie 等历史文件） |

### 只想清空数据、保留程序
```bash
./svc.sh stop
rm -rf .runtime/data/mysql8 .runtime/data/mysql57 .runtime/data/redis/*
./svc.sh init
```
（`init` 检测到数据目录不存在会重新初始化，这是它幂等的原因）

### 单独重置某一个中间件
```bash
./svc.sh stop mongodb  && rm -rf .runtime/data/mongodb/*   && ./svc.sh start mongodb
./svc.sh stop elasticsearch && rm -rf .runtime/data/elasticsearch/* && ./svc.sh start elasticsearch
./svc.sh stop minio && rm -rf .runtime/data/minio/* && ./svc.sh start minio
```
> Nacos 的数据**不要随手删** —— 里面存着 P2 的 6 个 `*-dev.yaml` 配置，
> 删了要重新跑 `tools/p2-publish-nacos-configs.py` 发布一遍。
>
> RabbitMQ 的 `db\`（mnesia）**也不要随手删** —— 删了 vhost `/mall`、用户 `mall`
> 会一起没（会按 `rabbitmq.conf` 里的 `default_*` 重建，但队列和消息全丢）。
>
> MinIO 的 `mc\` 里存着 `mc` 的 alias 配置。删了不影响 MinIO 本身，
> 但 `mc` 要重新 `alias set`（`tools/p2-minio-test.py` 会自动重建）。

### 彻底删掉整个运行时
```bash
./svc.sh stop full
rm -rf /d/java-workspace/.runtime
```
**没有装服务、没有写注册表、没有改 PATH。** 但有一个例外要说清楚：

> ⚠️ **`%USERPROFILE%\.erlang.cookie`（20 字节）会留下。**
> 这是 Erlang 分布式的 cookie 文件，RabbitMQ 需要它。
> 启动器里已经用 `HOMEDRIVE` / `HOMEPATH` 把它引到了
> `.runtime\data\rabbitmq\.erlang.cookie`（实测有效），
> 但**如果之前用旧版启动器跑过**，用户目录里会残留一个用不上的旧文件。
> 那是可以手动删的（它已经不再被读取）。

---

## 7. 排错

**连不上 / 启动失败**
先看日志，MySQL 的启动错误一定写在 error log 里：
```bash
./svc.sh logs mysql8        # 实时跟
tail -50 .runtime/logs/mysql8-error.log
```

**端口被占**
```bash
netstat -ano | grep ":3308 " | grep LISTENING
```

**`mysqld.exe` 进程杀不掉 / 重复启动**
`svc.cmd` 用端口判断是否在跑，所以正常情况下不会重复启动。
如果确实卡住了：
```bash
taskkill //F //IM mysqld.exe
taskkill //F //IM redis-server.exe
```

**`Access denied for user 'root'@'127.0.0.1'`**
检查 `mysql8.ini` 里**有没有** `skip-name-resolve`。
有的话 MySQL 不做 `127.0.0.1 → localhost` 的反查，
`'root'@'localhost'` 就匹配不上从 127.0.0.1 进来的连接。
本工作区的配置**故意没写**这一项。

**中文乱码**
Java 侧的编码问题见 `docs/jdk-matrix.md`（JDK 8/17 在中文 Windows 上默认 GBK，
`use-jdk` 脚本已经通过 `JAVA_TOOL_OPTIONS` 修掉了）。
MySQL 侧已经统一 utf8mb4，正常不会有问题。

### 所有服务「同时」消失 —— 先怀疑窗口被关，不要怀疑脚本

2026-09-28 实测过一次：19:10 时 12 个进程（mysqld / erl / epmd / mongod / redis /
nacos / elasticsearch / java / ollama）全在，19:31 再看**一个都不剩**，
`svc.sh status` 全红。系统**没有重启**（`uptime` 显示 1035.9 分钟，从 02:15 起）。

**定性证据在 `mongod` 的日志里：**

```
{"t":...,"s":"I","ctx":"consoleTerminate", ...}
{"t":...,"s":"I","ctx":"Shutdown","msg":"Shutdown: going to close listening sockets..."}
{"t":...,"s":"I","ctx":"-","msg":"Now exiting","exitCode":12}
```

`ctx:"consoleTerminate"` 的含义是：**承载这个进程的控制台/窗口被关闭了**，
于是进程收到控制台关闭信号（Windows 的 `CTRL_CLOSE_EVENT`）而退出。

**怎么区分「窗口被关」和「脚本停的」：**

| 特征 | 窗口被关（`consoleTerminate`） | `svc.sh stop` |
|---|---|---|
| 日志里有没有 `consoleTerminate` | **有** | 没有，是正常的 `Shutdown` |
| 退出码 | 12（Windows 控制台关闭） | 0 |
| 时间点 | **所有服务同一秒附近** | 按 `stop` 的顺序逐个 |
| 有没有 `svc.sh stop` 的调用痕迹 | 无 | 有 |

**恢复**：`./svc.sh start full`（+ 单独 `run-ollama.cmd`）。
**预防**：别把服务起在一个随手就会关掉的窗口里；用 `svc.cmd` 的 `start`
拉起（它用 `start` 创建独立子进程），或把窗口留着别关。

> 值得记的是**排查顺序**：一开始怀疑的是「谁跑了 stop」「是不是有并发进程在动我的库」，
> 都查无实据；真正定性的是一行 `ctx:"consoleTerminate"`。
> **进程集体死亡时，先去日志里找"死因关键词"，不要先去猜"谁干的"。**

### Nacos / MongoDB / Elasticsearch / RabbitMQ / MinIO / Ollama 专有的坑

**Nacos 起来后立刻退出，日志里端口是 22407**
`SERVER__PORT` 环境变量劫持。Nacos 3.x 本身就是个 Spring Boot 3.4 应用，**一样会中招**。
完整分析见 `docs/run-p0.md` 第 5 节。

```bash
env | grep -i port        # 看到 SERVER__PORT=22407 就是它
```
`run-nacos.cmd` 里已经写了 `set "SERVER__PORT="` 清掉它。
**但如果你在别的终端里手工 `startup.cmd`，就还是会中招。**

> ⚠️ 这个坑有个特别阴的地方：Nacos 会先打印
> `Nacos started successfully in stand alone mode ... in 6794 ms`，
> **然后**才因为端口绑不上而失败。也就是说 `grep "started successfully"` 会得到
> 「启动成功」的假结论。判断 Nacos 活没活**要看端口，不要看日志关键字**：
> ```bash
> ./svc.sh status          # 或
> netstat -ano | grep -E ":(8848|8849|9848) " | grep LISTENING
> ```

**Nacos 启动时卡住不动，停在等你输入**
Nacos 3.0 起有三个鉴权属性必须非空，为空时它会**交互式索要**（`set /p`）。
非交互脚本会永久卡住。`conf/application.properties` 里已经填好了，别清空它们。

**Nacos 控制台打不开 / 404 / 500**
十有八九是在用 2.x 的地址。3.x 是 **`http://127.0.0.1:8849/`**（根路径），
**不是** `8848/nacos`。见第 2 节。

**`mongod` 起不来，但日志文件是空的**
MongoDB **在解析配置阶段就退出**，这时日志文件还没建出来。
必须前台手工跑一次才能看到真正的报错：
```bash
cd /d/java-workspace/.runtime/mongodb/bin
./mongod.exe --config /d/java-workspace/.runtime/conf/mongod.yml
```
已知的一个例子：`storage.journal.enabled` 在 7.0 被移除，写了会直接
`Unrecognized option:` 退出。

**ES 起不来**
ES 日志在**它自己目录下**，不在 `.runtime\logs\`：
```bash
tail -50 /d/java-workspace/.runtime/elasticsearch/logs/elasticsearch.log
```
它启动要 15–20 秒，别过早判定失败。另外**版本必须是 8.x**（见第 2 节）。

**ES 连不上 / 报 SSL 或 401**
8.x 默认开安全。检查 `elasticsearch.yml` 末尾那个工作区块里的
`xpack.security.*` 四项是不是都被改回 `true` 了。

---

**★ RabbitMQ 起不来，报 `failed to open log file at '<某个目录>'`**

```
BOOT FAILED
===========
failed to open log file at 'd:/java-workspace/.runtime/logs',
reason: illegal operation on a directory
```

**根因：环境变量 `LOGS`。** 不是 `RABBITMQ_LOGS`，就是 **`LOGS`**。
RabbitMQ 会读这个名字，并把它的值当成**日志文件路径**。
一个叫 `LOGS` 的变量装的几乎必然是**目录**，于是它去「打开目录当文件」，直接死。

这个失败特别难查，有三个原因：
1. 它发生在**解析 `rabbitmq.conf` 之前** —— 配置文件里怎么写都救不回来
2. 日志里**不会**出现 `config file(s) :` 那一行（正常启动才有），
   所以完全看不出跟环境变量有关
3. 路径长得像「日志目录配错了」，会把人引向 `log.dir` / `log.file` 去查

**排查方法**（一步定性）：
```bash
env | grep -x "LOGS=.*"      # 有输出就是它
```

**已做的防御**：`run-rabbitmq.cmd` 里所有局部变量加 `JW_` 前缀；
`svc.cmd` 里原来的 `LOGS` 全部改名成 `LOGDIR`。
**但如果你在别的脚本里用了 `LOGS`，还是会被咬。**

> 这个坑的定位过程值得记一下：我一开始归因到「`log.file` 不是布尔值」，
> 那个结论**是错的** —— 两次失败的真因都是启动器里的 `LOGS`。
> 最后是靠一次**受控对照实验**定性的：节点停掉、其余条件完全不变，
> **只加** `LOGS=D:\java-workspace\.runtime\logs` → 复现失败；
> 去掉它、别的都不改 → 正常启动。

**`rabbitmqctl` / `rabbitmq-plugins` 说找不到节点、认证失败**
cookie 不一致。`rabbitmqctl` 必须和 broker 用**同一个** `.erlang.cookie`。
别自己拼命令，走包装器（它会把 `ERLANG_HOME`、`RABBITMQ_BASE`、`HOMEDRIVE` 都设好）：
```bash
./run-rabbitmq.cmd ctl status
./run-rabbitmq.cmd plugins list
```
> 另外注意 **`rabbitmqctl list_queues` 默认查 vhost `/`**，而工作区只有 `/mall`，
> 所以直接跑会「什么都没有」。要加 `-p /mall`：
> `./run-rabbitmq.cmd ctl list_queues -p /mall`

**RabbitMQ 发了消息但收不到 / `access to vhost '/mall' refused`**
vhost 不匹配。mall-portal 用的是 **`/mall`**，不是 `/`。

---

**MinIO 起不来 / 端口一直不变**
正常。MinIO 的**控制台端口默认是随机的**，每次启动都可能不一样。
启动器里用 `--console-address 127.0.0.1:9001` 钉死了，所以是 9001。

**上传 403 / `Access Denied`**
两个常见原因：
1. 账号不对 —— 必须是 `minioadmin` / `minioadmin`（要和 mall-admin 配置一致，见第 2 节）
2. bucket 不存在且没走上传接口 —— `MinioController` 只在**上传**路径里自动建桶，
   `/minio/delete` 不建。预建一下即可：
   ```bash
   .runtime/minio/mc.exe --config-dir .runtime/data/minio/mc mb jw/mall
   ```

**MinIO 控制台打不开 / 直链 403**
检查 bucket 的匿名读策略：
```bash
.runtime/minio/mc.exe --config-dir .runtime/data/minio/mc anonymous get jw/mall
```
Java 侧要求的是 `s3:GetObject` Allow for `Principal *`，
等价于 `mc anonymous set download jw/mall`。

**`mc` 的配置跑到用户目录去了**
`mc` 默认把配置写在 `%HOME%\.mc`。本工作区所有 `mc` 调用都带
`--config-dir .runtime\data\minio\mc`，所以不会污染用户目录。
如果你手工跑 `mc`，记得也带上。

---

**Ollama 明明在跑，`curl http://127.0.0.1:11434/...` 却超时**

**系统代理劫持了回环地址。** 日志里 Ollama 已经打了
`Listening on 127.0.0.1:11434`，但 curl 5 秒 0 字节。加 `--noproxy '*'` 立刻正常：

```bash
curl --noproxy '*' http://127.0.0.1:11434/api/version   # {"version":"0.34.4"}
```

> 本机环境里有 `CODEBUDDY_SERVICE_PROXY_URL=http://127.0.0.1:22407/...`，
> 系统代理设置也指向回环 —— 于是「访问本机的服务」被当成「走代理出去」。
> **Java 的 `RestClient` 不读 Windows 系统代理**，所以 P1 应用本身不受影响；
> 只有 curl / Python `requests` 这类会中招。
> `tools/p1-e2e-test.py` 用 `http.client` 直连，就是为了绕开这个。

**模型下到了用户目录 `%USERPROFILE%\.ollama\models`**

`OLLAMA_MODELS` 没生效。**必须先设环境变量再启动 `ollama serve`**，
运行中改是无效的。`run-ollama.cmd` 已经设好了；手工起的话：

```bash
export OLLAMA_MODELS="D:/java-workspace/.runtime/ollama/models"
export OLLAMA_HOST=127.0.0.1:11434
```

**`ollama show <model>` 报 `model '<x>' not found`**
这个命令**只能查已经拉下来的模型**。没拉过就先 `ollama pull`。
它输出的 `Capabilities` 行是判断能不能做 Agent 的唯一依据 ——
要看到 `tools` 才能给 `ToolCallAgent` 用。

**Agent 接口报 `does not support tools`**
模型能力问题，不是代码问题。`gemma3:1b` 就不支持，换 `qwen3:0.6b`。

---

**`./svc.sh start` 看起来「卡死」不动**
只在**把输出接进管道**时出现（`./svc.sh start | tail`、`$(./svc.sh start)` 之类）。
服务其实全都正常起来了，是命令不返回而已。

> **PowerShell 也一样会中招**：`& svc.cmd start rabbitmq 2>&1 | ForEach-Object {...}`
> 会挂住（实测踩过）。原因是 `|` 同样构成管道。

原因：`svc.cmd` 用 `start` 拉起守护进程，而 `start` 创建子进程用的是
`bInheritHandles = TRUE` —— 子进程继承父进程**整张可继承句柄表**，其中包括 stdout。
于是 `mysqld` / `redis-server` / `java` / `minio` 一直握着管道写端，
管道读端永远等不到 EOF。
（在 `start` 那行写 `>nul 2>&1` 没用：重定向只改 cmd 自己的 std handle，
句柄表里的条目照样被继承。实测过：重定向到**文件**正常，接到**管道**就挂。）

`svc.sh` 已经处理了这种情况：它先把 cmd 的输出写进临时文件，再打到真正的 stdout，
所以 `logs` 和 `cli` 之外的动作都能安全接管道。
`logs` / `cli` 需要实时输出，走的是直连，**这两个不要接管道**。

> 如果你直接在 cmd 里用 `svc.cmd ... | more`，还是会被这个机制挂住 ——
> 那是 cmd 的句柄继承行为，改不掉。用 `> 文件` 代替管道即可。

**改了 `.cmd` 之后行为变得莫名其妙**
先跑这一条：
```bash
grep -cP '[^\x00-\x7F]' svc.cmd
```
必须是 `0`。cmd 用 OEM 代码页（中文 Windows 上是 GBK）读 `.cmd`，而文件是 UTF-8，
任何非 ASCII 字节都会变成乱码 —— **而且乱码会从 `REM` 行漏出来被当成命令执行**。
另外 `REM` 挡不住 `&`，`REM a & b` 里的 `b` 会被执行。

