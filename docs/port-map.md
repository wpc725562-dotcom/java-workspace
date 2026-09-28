# 端口分配表

> **2026-09-28 修订**：中间件已从 Docker 方案改为**便携版**（`D:\java-workspace\.runtime\`），
> 原因见 `runtime.md`（本机 `hypervisorlaunchtype=Off`，Docker 起不来）。
> **同日再修订**：P2 的五个中间件全部装成了便携版，**Docker 已不再是必需品**。
> 本表已按实测结果更新，并修正了原表三处错误。

---

## 1. 中间件端口（便携版，已实测在跑）

| 端口 | 服务 | 位置 | 状态 | 说明 |
|---|---|---|---|---|
| `3307` | MySQL **5.7.44** | `.runtime\mysql-5.7` | ✅ 运行中 | **P0 eladmin-mp 专用** |
| `3308` | MySQL **8.0.43** | `.runtime\mysql-8.0` | ✅ 运行中 | P1 / P2 / P3 共用（按 schema 隔离） |
| `6380` | Redis **8.10.2** | `.runtime\redis` | ✅ 运行中 | 按 DB 隔离：DB1–DB4 |
| `8848` | Nacos **3.0.3** 客户端 API | `.runtime\nacos` | ✅ 运行中 | 服务注册/发现 + 配置中心，**免鉴权** |
| `8849` | Nacos **3.0.3 控制台** | 同上 | ✅ 运行中 | ⚠️ **不是 8848/nacos**，见下方说明 |
| `9848` | Nacos gRPC | 同上 | ✅ 运行中 | 2.x/3.x 客户端注册走它，必须有 |
| `27017` | MongoDB **7.0.14** | `.runtime\mongodb` | ✅ 运行中 | mall-portal 用（库名 `mall-port`），**免鉴权** |
| `9200` | Elasticsearch **8.18.8** | `.runtime\elasticsearch` | ✅ 运行中 | mall-search 用，**免鉴权** |
| `9300` | Elasticsearch 节点间 | 同上 | ✅ 运行中 | single-node 模式也会开 |
| `4369` | **Erlang epmd** | `.runtime\erlang` | ✅ 运行中 | RabbitMQ 的运行时依赖，**别误判成占用** |
| `5672` | RabbitMQ **4.3.6** AMQP | `.runtime\rabbitmq` | ✅ 运行中 | mall-portal 用，**vhost `/mall`** |
| `15672` | RabbitMQ 管理台 | 同上 | ✅ 运行中 | |
| `25672` | RabbitMQ 节点间 | 同上 | ✅ 运行中 | 集群/CLI 通信 |
| `9000` | MinIO API | `.runtime\minio` | ✅ 运行中 | mall-admin 用，bucket `mall` |
| `9001` | MinIO 控制台 | 同上 | ✅ 运行中 | 启动器里用 `--console-address` 钉死的 |
| `11434` | **Ollama** HTTP API | `.runtime\ollama` | 按需启动 | P1 的本地大模型，见下方说明 |
| `6333` / `6334` | Qdrant HTTP / gRPC | — | ⬜ **不需要** | 见下方说明 |
| `5432` | PostgreSQL + pgvector | — | ⬜ **不需要** | 见下方说明 |
| `18080` | phpMyAdmin | — | ❌ 不适用 | 便携版改用 `svc.cmd cli mysql8` 直连 |
| `5540` | RedisInsight | — | ❌ 不适用 | 便携版改用 `svc.cmd cli redis` |

### 修正一：Nacos 控制台是 `8849`，不是 `8848/nacos`

Nacos **3.x 把控制台拆成了独立端口**（`nacos.console.port`，默认 `8080`）。
2.x 时代那个「8848 + `/nacos` 路径」的控制台地址**已经失效**：

| 地址 | 结果 |
|---|---|
| `http://127.0.0.1:8848/nacos` | ❌ 404 / 500（这是客户端 API 端口，不是控制台） |
| `http://127.0.0.1:8849/` | ✅ 控制台（**根路径，无 `/nacos` 前缀**） |

控制台端口默认 `8080`，**正好和 mall-admin 撞**，所以本地已改成 `8849`
（见 `.runtime\nacos\nacos\conf\application.properties`）。

登录 API 的位置也跟着变了，两个都能用：

```bash
# 客户端 API 端口
curl -X POST "http://127.0.0.1:8848/nacos/v3/auth/user/login" -d "username=nacos" -d "password=..."
# 控制台端口
curl -X POST "http://127.0.0.1:8849/v3/auth/user/login"        -d "username=nacos" -d "password=..."
```

首次使用需要初始化管理员密码（Nacos 3.0 起控制台强制鉴权）：

```bash
curl -X POST "http://127.0.0.1:8848/nacos/v3/auth/user/admin" -d "password=Workspace#2026"
```

本工作区已执行过，账号 **`nacos` / `Workspace#2026`**。

### 修正二：Elasticsearch 必须是 **8.x**，不是 7.17

原表只写了「Elasticsearch」没写版本，很容易顺手装 7.17。**那是错的。**

mall-swarm 用 Spring Boot `3.5.14`，其 `spring-boot-dependencies` 里
`elasticsearch-client.version = 8.18.8`。ES 的 Java 客户端**有服务端版本校验**，
8.x 客户端拒绝与 7.x 服务端通信（反向同理），装错版本会在启动时才报错。

⇒ 本地装 **`elasticsearch-8.18.8-windows-x86_64`**。

ES 8.x 默认开启安全（HTTPS + 认证），而 mall-swarm 的配置是裸的 `localhost:9200` 无凭据，
所以本地要显式关掉：`xpack.security.enabled: false`。

### 修正三：MinIO **能装** —— 之前记的「装不了」是错的

原表写的是「官方已归档下架，装不了」。**官方源确实死了，但镜像还活着：**

```
dl.min.io          -> 410 Gone    （官方源，已下架）
dl.minio.org.cn    -> 200         （中国镜像，可用）
```

而且镜像提供 sha256 校验和，能确认拿到的是原版二进制。
实测已装好并跑通上传/下载/匿名直链，详见 `runtime.md` 第 1 节。

### 为什么 Qdrant 和 PostgreSQL 最终不需要

| 服务 | 原计划 | 实际结论 |
|---|---|---|
| Qdrant（6333/6334） | P1 可选向量库 | **不需要** —— P1 默认走 `SimpleVectorStore`（纯内存） |
| PostgreSQL + pgvector（5432） | P1 的 PgVector RAG 路径 | **不需要** —— `PgVectorVectorStoreConfig` 类上的 `@Configuration` **是注释掉的** |

也就是说 P1 的 RAG 链路在默认状态下**不依赖任何外部向量库**。
等真的要启用 PgVector 路径时再装 PostgreSQL 也不迟（那时才需要取消那行注释）。

### 为什么 Redis 用 6380 而不是 6379
6379 太容易撞 —— 任何装过 Redis 的机器、任何其他项目的容器都会抢它。
6380 留出安全距离，同时一眼能看出「这是本工作区的」。

### 为什么 phpMyAdmin 原本是 18080 而不是 8081
`8080–8401` 这段是 **mall-swarm 的地盘**：
`mall-admin 8080` / `mall-search 8081` / `mall-demo 8082` / `mall-portal 8085` /
`mall-monitor 8101` / `mall-gateway 8201` / `mall-auth 8401`。
phpMyAdmin 原本顺手写 8081，**正好和 mall-search 撞**。

> 这条就是端口表存在的意义：**撞端口在 P2 阶段才会暴露**，
> 那时你已经起了一堆服务，排查起来很烦。现在先把坑填了。
> （便携版下 phpMyAdmin 不再需要，但这个结论对 Nacos 控制台同样成立 —— 它默认的 8080 也撞。）

### 为什么 MySQL 要两个实例而不是一个
MySQL 8 把 `rank` / `groups` / `system` / `window` 等变成了**保留字**。
老项目（尤其 eladmin 那一代）的建表 SQL 里常有裸用这些词当列名的，在 8.0 上直接语法错误。
与其去改人家的 SQL，不如给 P0 单独一个 5.7 实例 —— 一个实例 ~400 MB 内存，换掉一堆玄学问题。

实测也确实用上了：eladmin 的 `sql/eladmin.sql` 里有 **1 处 `utf8mb3`**（5.7 不认这个别名），
而 mall 的 `mall.sql` 在 8.0 上零问题。两边各得其所。

---

## 2. 应用端口（各项目自己的，已核对实际配置）

| 阶段 | 项目 | 端口 | 来源 |
|---|---|---|---|
| P0 | eladmin-mp | `8000` | ✅ 实测启动成功 |
| P1 | yu-ai-agent | `8123`（context-path `/api`） | ✅ **实测启动成功，5 个接口全通**（2026-09-28） |
| P1 | yu-image-search-mcp-server | `8127`（独立的嵌套项目） | 项目默认，MCP 客户端配置目前是注释掉的 |
| P1 | yu-ai-agent-frontend | `3000`（Vite dev server） | `vite.config.js` 里写死 |
| P2 | mall-swarm | `8080` `8081` `8082` `8085` `8101` `8201` `8401` | ✅ 逐模块核对过 |
| P3 | seckill | 待定 | 克隆后核对 |
| **P4** | **exam-tracker**（本工作区原创） | **`8090`（context-path `/api`）** | ✅ **实测启动成功，86/86 端到端断言通过**（2026-09-28） |

P2 的端口不是记忆，是实际读出来的：

```
mall-admin 8080 | mall-search 8081 | mall-demo 8082 | mall-portal 8085
mall-monitor 8101 | mall-gateway 8201 | mall-auth 8401
```

### P4 的库与端口为什么这么选

- **端口 `8090`**：`8080–8401` 是 mall-swarm 的地盘，`8000` / `8123` 是 P0 / P1。
  8090 落在它们之间的空档，且和中间件端口集合（3307/3308/6380/8848/8849/9848/
  27017/9200/9300/4369/5672/15672/25672/9000/9001/11434）零交集。
- **库 `exam_tracker`**：建在已有的 **MySQL 3308**（8.0.43）上，按 schema 隔离，
  没有为 P4 单独起实例 —— 一个实例 ~400 MB 内存，P4 不需要 5.7 兼容性。
- **context-path `/api`**：和 P1 保持一致，前端只要记「所有接口都挂在 `/api` 下」。
  注意 Spring Security 的 `requestMatchers` 匹配的是**去掉 context-path 之后**的路径。

### 应用端口与中间件端口是否冲突
**不冲突**，已逐条核对：8000 / 8123 / 8080 / 8081 / 8082 / 8085 / 8101 / 8201 / 8401
没有一个落在中间件端口集合里。

唯一的历史冲突是 **Nacos 控制台默认 8080 ↔ mall-admin 8080**，已通过改控制台到 8849 解决。

---

## 3. 为什么中间件一律绑 `127.0.0.1`

便携版的 `mysql8.ini` / `mysql57.ini` 里写的是 `bind-address=127.0.0.1`。

不写的话 MySQL 会**默认绑 `0.0.0.0`**，也就是监听所有网卡。
配上本工作区用的弱口令（`123456`），
在同一个 Wi-Fi 下的任何设备都能直接连上你的数据库。

本地开发用不到「别的机器能连」，所以一律绑回环地址。
真要临时给别的机器用，再单独改那一条。

（原 Docker 方案里对应的是把 `"3307:3306"` 写成 `"127.0.0.1:3307:3306"`，道理一样。）

---

## 4. 查端口占用

```bash
# 看工作区所有中间件的状态（推荐，比 netstat 直观）
cd /d/java-workspace && bash svc.sh status

# 查某个端口谁占着
netstat -ano | grep ":3308 " | grep LISTENING

# 批量查本表所有端口
for p in 3307 3308 6380 8848 8849 9848 27017 9200 9300 4369 5672 15672 25672 9000 9001 \
         8000 8123 8127 3000 8080 8081 8082 8085 8101 8201 8401; do
  netstat -ano 2>/dev/null | grep -q ":$p .*LISTENING" && echo "$p  占用" || echo "$p  空闲"
done
```

> **注意**：`netstat` 的输出里，**远端**地址也会出现在匹配结果里。
> 例如查 `8000` 时可能匹配到 `[2409:...]:443` 这种出站连接 —— 那不是本机监听。
> 判断本机监听要看 `0.0.0.0:PORT` 或 `127.0.0.1:PORT` 且状态是 `LISTENING`。
>
> **另外**：`grep ":PORT "` 要带上**尾随空格**，否则 `9200` 会匹配到 `92000` 之类。
> 本表脚本已经带上了。
