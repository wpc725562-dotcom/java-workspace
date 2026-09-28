# P2 — mall-swarm 启动手册

> 状态：**7 个模块已全部启动并逐个验证通过；端到端业务链路（网关 → auth → admin → MySQL → ES → MongoDB）已跑通；
> 下单全链路含延迟取消闭环（TTL → 死信 → 消费者关单 → 库存回滚）已实测通过**
> 2026-09-28（当日更新：中间件 8 件补齐 → 9 模块构建通过 → 7 模块全部 UP → 下单闭环跑通，见 §9）

---

## 0. 先读这一段：P2 比 P0/P1 复杂在哪

P0 是单模块、配置写死在仓库里。**P2 是 7 个模块 + 一个配置中心**，多出两层依赖：

| 层 | 依赖 | 说明 |
|---|---|---|
| 中间件 | Nacos / MySQL / Redis / MongoDB / RabbitMQ / Elasticsearch | 见第 3 节，按模块分 |
| **配置中心** | **Nacos 里必须有对应 dataId 的配置** | ⚠️ 见第 2 节，这是最容易卡住的地方 |
| 服务发现 | 各模块启动后互相注册 | mall-auth 靠 Feign 调 mall-admin/mall-portal |

---

## 1. 一句话配方

```bash
# ① 起中间件（8 件；ES 约 18s、Nacos 约 30s，其余各约 4s，全套约 60s）
cd /d/java-workspace && bash svc.sh start full
bash svc.sh status          # 8 行全绿才算齐

# ② 构建 + 启停模块（p2.sh 已把下面这些坑全包好了，见第 8 节）
./p2.sh build               # ≈30s，9 个模块全部 SUCCESS
./p2.sh start               # 7 个模块并行起，约 90s 内全部就绪
./p2.sh status              # 端口 + /actuator/health 一览
./p2.sh logs admin          # 跟某个模块的日志
./p2.sh stop                # 全部停止
```

`p2.sh` 里已经固化了两件**不加就必然失败**的事，手动敲命令时别忘：

| 必须加 | 不加会怎样 |
|---|---|
| `-Ddocker.skip=true` | 6 个模块在 `package` 阶段挂掉，报 `192.168.3.101:2375 failed to respond` |
| `--spring.cloud.nacos.discovery.ip=127.0.0.1` | 多网卡机器上注册到不可达的地址，Feign 调用超时 |
| 先清 `SERVER__PORT` | 应用去抢宿主端口，`PortInUseException` |

| 项 | 值 |
|---|---|
| JDK | **17**（`pom.xml` 里 `<java.version>17</java.version>`） |
| Spring Boot | 3.5.14 + Spring Cloud 2025.0.2 + Alibaba 2025.0.0.0 |
| Nacos 客户端 | **3.0.3** ⇒ 服务端必须是 **Nacos 3.x**（已装 3.0.3） |
| 模块数 | 9（admin / auth / common / demo / gateway / mbg / monitor / portal / search） |
| 可运行模块 | 7（`common` / `mbg` 是被依赖的库，不单独启动） |
| 构建 | 系统 Maven 3.9.16 | ⚠️ **没有 `mvnw`** |
| 构建耗时 | 全量 `clean install` 约 30 秒（依赖已缓存） |

---

## 2. ⚠️ 最关键的一节：配置在 Nacos 里，不在仓库里

每个模块的 `application-dev.yml` 长这样：

```yaml
spring:
  config:
    import:
      - nacos:mall-admin-dev.yaml?refreshEnabled=true
```

**注意没有 `optional:` 前缀。** 这意味着：配置在 Nacos 里找不到 → 模块直接启动失败
（`ConfigDataResourceNotFoundException`），连端口都不会去监听。

仓库里的 `config/` 目录就是给导入用的原始素材，但官方没提供导入脚本 ——
只能手动在控制台一条条粘，或者用本工作区写的脚本：

```bash
cd /d/java-workspace
"C:\Users\Administrator\.workbuddy-ai\binaries\python\envs\default\Scripts\python.exe" tools/p2-publish-nacos-configs.py
```

实测输出：

```
  [OK]   登录 Nacos 成功（nacos），拿到 accessToken

  [OK]   mall-admin-dev.yaml      已发布并读回校验一致（1469 字符，md5=2a835f36e9ea52506c315e963649519d）
  [OK]   mall-auth-dev.yaml       已发布并读回校验一致（1299 字符，md5=a2bb17c9674c5c030ecf9dbac5748a9a）
  [OK]   mall-demo-dev.yaml       已发布并读回校验一致（735 字符，md5=9e7a31a613b1bfe6e63a87b8a32f4c4b）
  [OK]   mall-gateway-dev.yaml    已发布并读回校验一致（610 字符，md5=7be764ea445f7ab35c3a923be8b04dab）
  [OK]   mall-portal-dev.yaml     已发布并读回校验一致（1334 字符，md5=7b3cd794f4acf3d3b0ac078e1640c755）
  [OK]   mall-search-dev.yaml     已发布并读回校验一致（764 字符，md5=766bb1da82b0120b231ddeac5dc2b542）

  成功 6 个，失败 0 个
```

**这 6 个已经发布好了**，重启 Nacos 后仍在（Nacos standalone 用内嵌存储，数据在 `.runtime\nacos\nacos\data\`）。

### 发布时踩到的两个坑

**坑 A：响应体形状和直觉不一样**

Nacos 3.x 的客户端读接口返回的是

```json
{"code":0,"message":"success","data":{"content":"...","md5":"...","success":true}}
```

也就是说正文在 **`data.content`** 里，`data` 本身是个对象，不是字符串。
配置不存在时才是 `{"code":20004,"message":"resource not found","data":null}`。
按 `data` 直接比字符串会把「发布成功」误判成「读回为空」。

**坑 B：客户端读接口不是立即可见的**

刚发布完立刻读，可能读到**上一次的旧值**。实测：连发两次不同内容，第二次读回的还是第一次的。
所以校验必须轮询重试，不能读一次就下结论。

### 仓库自身的缺口：`mall-auth-dev.yaml` 不存在

`config/` 目录下只有 `admin` / `demo` / `gateway` / `portal` / `search` ——
但 `mall-auth` 声明了要 `nacos:mall-auth-dev.yaml`。**这是仓库的问题，不是本地环境问题。**

已按其它模块的结构补了一份 `config/auth/mall-auth-dev.yaml`，依据是：

- mall-auth 的 pom 里有 `spring-boot-starter-data-redis` → **需要 Redis**
- mall-common **没有** jdbc / mybatis 依赖 → **不需要数据源**
- 登录校验走 OpenFeign 调 mall-admin / mall-portal，mall-auth 自己只签发和校验 token

---

## 3. 各模块需要哪些中间件

下表是**读 pom + 读 Java 代码 + 读配置**核出来的，不是凭印象：

| 模块 | 端口 | MySQL | Redis | Nacos | MongoDB | RabbitMQ | ES |
|---|---|---|---|---|---|---|---|
| mall-gateway | 8201 | — | ✅ | ✅ | — | — | — |
| mall-admin | 8080 | ✅ | ✅ | ✅ | — | **—** | — |
| mall-auth | 8401 | — | ✅ | ✅ | — | — | — |
| mall-portal | 8085 | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| mall-search | 8081 | ✅ | **—** | ✅ | — | — | ✅ |
| mall-demo | 8082 | ✅ | ✅ | ✅ | — | — | — |
| mall-monitor | 8101 | — | — | ✅ | — | — | — |

> ⚠️ **`mall-admin` 原来被我标成需要 RabbitMQ，那是错的。** 核查依据：
> ```bash
> grep -i "amqp\|rabbit" mall-admin/pom.xml                      # 无命中
> grep -rn "RabbitTemplate\|@RabbitListener" mall-admin/src      # 无命中
> grep -rn "rabbitmq" config/admin/ mall-admin/ --include=*.yml  # 无命中
> ```
> **全仓库只有 `mall-portal` 需要 RabbitMQ。** 这条修正的实际意义是：
> 只跑 gateway+admin+auth+demo+monitor 的话，RabbitMQ 完全不用启。

> ⚠️ **还有两处是启动之后才发现的，已按实测改正**（见 §8 坑 7 / 坑 8）：
>
> | 模块 | 原写法 | 实测结论 | 判据 |
> |---|---|---|---|
> | mall-search | Redis ✅ | **Redis —** | `mall-search/pom.xml` 里对 `mall-mbg` 显式 **exclude** 了 `spring-boot-starter-data-redis`；运行期 `/actuator/health` 里**没有** redis 组件 |
> | mall-demo | `(继承)` | **Redis ✅** | 运行期 health 里**有** redis 组件，且不补配置就是 `DOWN` |
>
> 教训：**光读 pom 不够，最终判据是运行期 `/actuator/health` 里到底有没有那个组件。**

### 依赖是怎么传递的（决定了「为什么几乎每个模块都要 Redis」）

```
mall-common    ← spring-boot-starter-data-redis          （Redis 客户端在这）
    ↑
mall-mbg       ← mall-common + mybatis + druid + mysql-connector-j   （MySQL 在这）
    ↑
mall-admin / mall-portal / mall-search / mall-demo
```

- **MySQL**：只有依赖 `mall-mbg` 的模块才有 ⇒ admin / portal / search / demo 四个
- **Redis**：`mall-common` 就带 ⇒ gateway / auth 直接依赖它；
  admin / portal / demo 通过 `mall-mbg` 间接带上。
  **唯独 `mall-search` 是例外** —— 它在 pom 里对 `mall-mbg` 显式排除了这个 starter，
  所以 search 是全套里唯一「有 MySQL 但没有 Redis」的模块
- **mall-monitor 是干净的**：只依赖 `nacos-discovery` + `spring-boot-admin-server`，
  既不碰 mall-common 也不碰 mall-mbg ⇒ **只需要 Nacos**

⇒ 想跑「最小可用集」（gateway + admin + auth + demo + monitor），
只需要 **MySQL + Redis + Nacos**。

---

## 4. 改了哪些配置

用脚本批量改的（`tools/p2-fix-configs.py`），**每处原值都备份成同名 `.orig` 文件**：

| 改动 | 处数 | 说明 |
|---|---|---|
| `jdbc:mysql://localhost:3306/mall` → `:3308` | 8 | P2 用 MySQL **8**，不是 P0 那个 5.7 |
| datasource `password: root` → `123456` | 8 | 工作区统一 root 密码 |
| Redis `port: 6379` → `6380` | 5 | 含 `config/gateway/` 和 `mall-gateway/application.yml` |

涉及的 9 个文件：
`config/{admin,auth,demo,gateway,portal,search}/mall-*-dev.yaml` +
`mall-{admin,demo,portal,search,gateway}/src/main/resources/application.yml`

### 为什么不用整文件替换 `password`
`mall-portal` 里还有 **RabbitMQ 的 `username: mall` / `password: mall`** 和 **MongoDB 的 27017**。
整文件替换 `password` 会误伤它们。所以脚本按「`username: root` 紧跟 `password: root`」这个
**两行连续序列**精确定位，且要求两行缩进相同。

改完立刻用 YAML 解析器全仓库复验（8 个文件改动，0 个解析失败）。

### `config/*-prod.yaml` 故意没改
它们用的是 Docker 主机名（`jdbc:mysql://db:3306/mall`、`nacos-registry:8848`），本地不加载。

---

## 5. 数据库

| 项 | 值 |
|---|---|
| 实例 | MySQL **8.0.43** @ `127.0.0.1:3308` |
| schema | `mall` |
| 表数量 | **76** |
| 数据 | `document/sql/mall.sql`（76 CREATE TABLE + 1653 INSERT） |
| 账号 | `root/123456`、`dev/dev123456`（对 `mall` 有全部权限） |
| 中文 | 已抽查 `pms_product_category`：`服装` / `手机数码` / `家用电器` 正常 |

这个 SQL 在 MySQL 8 上**零不兼容**（`utf8mb3` / `Aria` / `SEQUENCE` 等特征全为 0），
和 P0 那个需要 `sed` 处理的 eladmin 形成对比。

---

## 6. 中间件现状

> **全部就绪。** 八个中间件都装好并各自做过端到端验证，
> `./svc.sh start full` 一条命令起全套。

| 中间件 | 端口 | 状态 | 备注 |
|---|---|---|---|
| Nacos | 8848 / 8849 / 9848 | ✅ 已装并验证 | 见 `runtime.md` |
| MySQL 8 | 3308 | ✅ | 76 张表已灌 |
| Redis | 6380 | ✅ | |
| MongoDB | 27017 | ✅ 已装并验证 | 库名 `mall-port`，读写往返含中文已验 |
| Elasticsearch | 9200 | ✅ 已装并验证 | **8.18.8**（不是 7.17），索引写入/读回含中文已验 |
| **ES 插件 `analysis-ik`** | — | ✅ **必须单独装** | 8.18.8；不装则 **mall-search 起不来**，见 §8 坑 7 |
| RabbitMQ | 5672 / 15672 | ✅ 已装并验证 | Erlang 28.5.0.7 + RabbitMQ 4.3.6，见下 |
| MinIO | 9000 / 9001 | ✅ 已装并验证 | 走中国镜像装上的，见下 |
| Erlang/OTP | 4369 (epmd) | ✅ | RabbitMQ 的运行时 |

> ⚠️ **`analysis-ik` 是最容易被漏掉的一个。** 它不在 `svc.sh` 的服务清单里
> （不是独立进程，而是 ES 的插件目录里多一个 `plugins/ik/`），
> 所以「8 个服务全绿」并不代表它装了。缺它的症状是 **mall-search 启动失败**，
> 报 `analyzer [ik_max_word] has not been configured in mappings`。
> 校验一条命令：
> ```bash
> curl -s http://127.0.0.1:9200/_cat/plugins?v      # 应出现 analysis-ik 8.18.8
> ```

### RabbitMQ 的三个要点

**① 只有 `mall-portal` 需要它。** 这不是猜的 —— 全仓库 `spring-boot-starter-amqp`
只有 `mall-portal/pom.xml` 一处命中：

```
$ grep -rl "spring-boot-starter-amqp" --include="pom.xml" .
./mall-portal/pom.xml
```

所以想省内存的话，不跑 mall-portal 就可以不启 RabbitMQ。

**② 凭据和 vhost 必须对得上**（来自 `config/portal/mall-portal-dev.yaml`）：

```yaml
rabbitmq:
  host: localhost
  port: 5672
  virtual-host: /mall      # ← 注意是 /mall，不是 /
  username: mall
  password: mall
```

`rabbitmq.conf` 里用 `default_user` / `default_pass` / `default_vhost`
在首次启动时创建了这些。**vhost 写错的现象很有欺骗性** ——
启动不报错，一发消息才 `access to vhost '/mall' refused`。

**③ 验证脚本**：`tools/p2-rabbitmq-test.py`
跑的是 mall-portal 真正的订单超时取消链路（TTL 队列 + 死信转发），
不是「端口通了」这种浅层检查。实测 **11/11 通过**。

### MinIO：之前记的「装不了」是错的

**官方源确实死了**，`dl.min.io` 对所有开源构建返回 **410 Gone**：

```
410 Gone
The open-source MinIO Server, MinIO Client (mc) and MinIO KES projects are
archived and no longer maintained. ... These files are no longer served from
this site. This applies to all community releases and to all hotfix builds.
```

**但中国镜像还活着**：

```
https://dl.minio.org.cn/server/minio/release/windows-amd64/minio.exe   -> 200
https://dl.minio.org.cn/client/mc/release/windows-amd64/mc.exe         -> 200
```

而且镜像提供 sha256 校验和，并且校验和文件里写明了对应的上游版本号，
所以能确认拿到的是原版二进制（`minio.exe` 和 `mc.exe` 两个校验和都已核对一致）。

已装好并配齐：

| 项 | 值 |
|---|---|
| endpoint | `http://127.0.0.1:9000` |
| 控制台 | `http://127.0.0.1:9001` |
| accessKey / secretKey | `minioadmin` / `minioadmin`（照 mall-admin 配置对齐） |
| bucket | `mall`，已设公开读 |

> **bucket 其实是「可预建可不预建」的**：`MinioController.upload` 里
> 有 `bucketExists` → `makeBucket` 的逻辑，首次上传会自动建桶。
> 但 `/minio/delete` **不建桶**，所以还是预建更稳。
>
> **验证脚本**：`tools/p2-minio-test.py`，实测 **13/13 通过**
> （上传 → 读回 → 匿名 HTTP 直链 → 列举 → 删除，含中文文件名与内容）。

> **教训**：一条下载路径失败 ≠ 这个软件不存在。
> 当时只试了 `dl.min.io` 就下结论「拿不到」，没去试镜像站。

---

## 7. 启动顺序

服务发现和配置中心就绪后，模块之间**没有严格的启动顺序要求**（都是去 Nacos 注册），
但按这个顺序起，日志里的报错最少：

```
1. gateway   (8201)  —— 入口
2. admin     (8080)  —— 被 auth 通过 Feign 调用
3. auth      (8401)  —— 依赖 admin/portal
4. portal    (8085)
5. search    (8081)
6. demo      (8082)  —— 可选，纯演示
7. monitor   (8101)  —— 可选，监控台
```

---

## 8. ⚠️ 已知坑

### 坑 0：不加 `-Ddocker.skip=true` 就构建不过（最容易误判的一个）

根 pom 的 `<pluginManagement>` 把 fabric8 的 `docker-maven-plugin` 的 `build` 目标
**绑到了 `package` 阶段**，而且 `<docker.host>` 写死成**原作者的内网地址**：

```xml
<docker.host>http://192.168.3.101:2375</docker.host>
```

`admin / auth / gateway / monitor / portal / search` 这 6 个模块都显式声明了这个插件，
于是只要本机没有那个 Docker 守护进程，`mvn package` 就在 `package` 阶段失败：

```
[INFO] --- spring-boot:3.5.14:repackage (repackage) @ mall-admin ---   ← 这行是成功的
[INFO] --- docker:0.45.1:build (build-image) @ mall-admin ---          ← 这行挂了
[ERROR] DOCKER> Cannot create docker access object [192.168.3.101:2375 failed to respond]
```

**为什么特别容易误判**：报错发生在编译和 repackage **都成功之后**，
日志里最后一条成功信息是 `spring-boot:repackage`，很自然会怀疑是打包环节坏了。
（我第一轮就把它错读成 `repackage` 报 `zip END header not found`，方向完全跑偏。）

**为什么失败位置看起来「随机」**：`mall-demo` 和 `mall-mbg` 没声明这个插件，
所以它们能过、其它模块过不去。哪一轮先撞上，取决于当时哪个模块的 jar 被占用。

**正确做法**：

```bash
mvn -DskipTests -B -Ddocker.skip=true clean install
```

`docker.skip` 是 fabric8 插件官方的跳过开关，比改 pom 干净。
本工作区的 `./p2.sh build` 已经内置。

### 坑 0.5：残留 JVM 会锁住 `target/*.jar`，让 `clean` 失败

现象：

```
Failed to clean project: Failed to delete ...\mall-admin\target\mall-admin-1.0-SNAPSHOT.jar:
另一个程序正在使用此文件，进程无法访问。
```

原因：上一次启动的模块还在跑，Windows 下运行中的 jar 被独占。
**这个坑和上面那个会互相伪装** —— 我第一轮看到的 `zip END header not found`
就是「jar 正在被另一个 JVM 读写」的副作用，不是 repackage 的 bug。

排查与处置：

```bash
# 找出是谁占着端口（顺带就是占用 jar 的那个进程）
netstat -ano | grep LISTENING | grep -E ":(8201|8080|8401|8085|8081|8082|8101) "
# 或者直接看 java 进程
tasklist //FI "IMAGENAME eq java.exe"

# 用脚本停干净（按端口找 PID 并 taskkill /T，连带子进程）
./p2.sh stop
```

**教训**：构建失败时先确认「没有残留实例」，再去看 Maven 的报错。
反过来做，就会像我一样对着一个假的 `repackage` 报错查半天。

### 坑 0.6：Nacos 3.x 里 v1 目录接口已下线

想查「有哪些服务注册上来了」，用 v1 的目录接口会拿到：

```
HTTP 410  {"message":"Current API is deprecated, please use the new API"}
  /nacos/v1/ns/catalog/services
```

**但实例查询接口还是好的**，直接用这个（不需要 token）：

```bash
curl -s "http://127.0.0.1:8848/nacos/v1/ns/instance/list?serviceName=mall-admin"
```

返回 `hosts[].ip/port/healthy`，能确认注册地址是 `127.0.0.1` 还是网卡地址 ——
排查 Feign 超时时这条最有用。

⚠️ 注意 `nacos.server.main.port` 是 **8848**（客户端 API），
不是 8849（控制台）。带 `/nacos/v3/client/...` 的路径是不存在的，会 404。

### 坑 1：`SERVER__PORT` 劫持 `server.port`（和 P0 同源）
见 `run-p0.md` 第 5 节。**P2 有 7 个模块，这个坑会一次咬 7 次**，而且日志里的
`Tomcat initialized with port 22407` 会让人以为是端口配置写错了。

启动前 `source use-jdk.sh 17` 即可（该脚本已自动 `unset SERVER__PORT SERVER__HOST`）。

### 坑 2：改配置中心的东西不会自动生效到已启动的模块
`?refreshEnabled=true` 只对**标了 `@RefreshScope` 的 Bean** 生效。
改完 Nacos 里的配置，最省心的做法还是重启模块。

### 坑 3：Nacos 控制台不是 `8848/nacos`
见 `port-map.md` 的「修正一」。Nacos 3.x 控制台是**独立端口 8849、根路径**。

### 坑 4：模块名和端口很容易记混
`mall-admin` 是 8080（管理后台），`mall-portal` 是 8085（用户端），
`mall-search` 是 8081 —— **8081 不是管理后台**。
拿不准就跑一遍：

```bash
grep -rn "^  port:" /d/java-workspace/p2-mall-swarm --include="application.yml"
```

### 坑 5：环境变量 `LOGS` 会让 RabbitMQ 起不来（和 P2 配置无关）

`mall-portal` 依赖 RabbitMQ，而 RabbitMQ 读的是一个名字就叫 **`LOGS`** 的环境变量
（**不是** `RABBITMQ_LOGS`），并把它当成**日志文件路径**。叫 `LOGS` 的变量通常存的是**目录**，
于是 broker 在 prelaunch 阶段、**还没读到 `rabbitmq.conf`** 就崩：

```
BOOT FAILED
failed to open log file at 'd:/java-workspace/.runtime/logs',
reason: illegal operation on a directory
```

判据是报错里的路径**是个目录**。

已做的处置：工作区所有启动脚本里日志目录变量统一改名（`svc.cmd` 里叫 `LOGDIR`，
`run-rabbitmq.cmd` 里叫 `JW_LOGDIR`）。**注意 `svc.cmd` 是用 `start` 拉起子进程的，
父进程的整个环境会被继承** —— 所以只要父脚本里出现名为 `LOGS` 的变量，同样会毒到 RabbitMQ。

如果你自己另写脚本起 RabbitMQ，**别在任何一层设 `LOGS`**。详见 `runtime.md` 的 ★ 块。

### 坑 6：`rabbitmqctl` 的两个小陷阱

- **cookie 认 `HOMEDRIVE` + `HOMEPATH`，不认 `HOME`**（Windows 上，实测只设 `HOME` 无效）。
  启动脚本已把 cookie 落到 `.runtime\data\rabbitmq\` 内；另外这个 cookie 文件的时间戳
  **恒为 `00:00:00`**，不能拿它判断新旧。
- **默认 vhost 是 `/mall` 不是 `/`**，查权限要带 `-p /mall`。
- ★ **`-p /mall` 会被 Git Bash 当成路径改写掉。** 直接这样写会失败：
  ```bash
  bash svc.sh ctl rabbitmq list_queues -p /mall name messages
  # 实际发出去的是：list_queues -p C:/Users/Administrator/.workbuddy-ai/.../mall
  #   → Listing queues for vhost C:/Users/.../mall ...
  ```
  Git Bash 在把参数交给原生 Windows 程序时会做「路径自动转换」，
  以 `/` 开头的参数一律被当成 Unix 绝对路径改写成 `C:/...`。
  **正确写法**（二选一）：
  ```bash
  MSYS_NO_PATHCONV=1 bash svc.sh ctl rabbitmq list_queues -p /mall name messages
  bash svc.sh ctl rabbitmq list_queues -p //mall name messages     # 双斜杠也能挡住改写
  ```
  这个坑和 `svc.sh` 顶部注释里说的「为什么用 cmd 做实现、bash 只做转发」是同一族问题。

---

### 坑 7：mall-search 起不来 —— 缺 IK 中文分词器插件

**现象**：search 编译、启动日志都正常，最后却在建索引时炸掉，`APPLICATION FAILED TO START`：

```
Caused by: co.elastic.clients.elasticsearch._types.ElasticsearchException:
  [es/indices.create] failed: [mapper_parsing_exception]
  Failed to parse mapping: analyzer [ik_max_word] has not been configured in mappings
```

**根因**：`EsProduct.java` 里三个字段标了 `@Field(analyzer = "ik_max_word")`：

```java
@Field(analyzer = "ik_max_word", type = FieldType.Text)
private String name;
```

`ik_max_word` 是 **IK 中文分词器**提供的 analyzer，而 Elasticsearch 官方发行包**不带**它，
必须单独装 `analysis-ik` 插件。Spring Data ES 在启动时会用实体上的映射去创建索引
（`EsProductRepository` 的构造过程里就 `indices.create`），
ES 发现 analyzer 不认识 → 拒绝建索引 → Bean 创建失败 → 应用退出。

**注意这一步说明 ES 连接本身是通的** —— 请求已经走到 `indices.create` 了。
所以看到这个错不要往「ES 连不上」或「版本不匹配」的方向查。

**修法**（工作区已装好，记录在这里以便重建）：

```bash
# ① 下载：必须和 ES 版本严格一致
curl -L -o .runtime/_dl/ik-8.18.8.zip \
  https://release.infinilabs.com/analysis-ik/stable/elasticsearch-analysis-ik-8.18.8.zip

# ② 解压到 plugins/ 下的一个子目录（目录名随意，习惯叫 ik）
mkdir -p .runtime/elasticsearch/plugins/ik
python -c "import zipfile; zipfile.ZipFile('.runtime/_dl/ik-8.18.8.zip').extractall('.runtime/elasticsearch/plugins/ik')"

# ③ 重启 ES
bash svc.sh stop elasticsearch && bash svc.sh start elasticsearch
```

**校验**（三条都要过）：

```bash
# ① 插件被加载
curl -s http://127.0.0.1:9200/_cat/plugins?v
#   name   component   version
#   node-1 analysis-ik 8.18.8

# ② 分词器真的能用
curl -s -X POST http://127.0.0.1:9200/_analyze -H 'Content-Type: application/json' \
  -d '{"analyzer":"ik_max_word","text":"小米手机旗舰店"}'
#   ik_max_word -> 小米 / 手机 / 旗舰店 / 旗舰 / 店     （细粒度，全切）
#   ik_smart    -> 小米 / 手机 / 旗舰店                 （粗粒度，少切）

# ③ 索引建出来了
curl -s "http://127.0.0.1:9200/_cat/indices?v"
#   green open pms ...
```

**踩坑提示**：`plugin-descriptor.properties` 里的 `elasticsearch.version` 必须和 ES 完全一致
（这里是 `8.18.8`），差一个小版本 ES 会直接拒绝启动。
GitHub 上的 `medcl/elasticsearch-analysis-ik` 与 `infinilabs/analysis-ik` 的 releases
都**没有** v8.18.8 这个 tag（404），但 `release.infinilabs.com` 上有 —— 别因为 GitHub 404 就以为装不了。

---

### 坑 8：mall-demo 的 `/actuator/health` 是 DOWN —— 上游配置本身缺 Redis 块

**现象**：demo 端口在听、`Started MallDemoApplication` 也打出来了，但健康检查整体是 `DOWN`：

```json
{"status":"DOWN","components":{
  "db":{"status":"UP"},
  "redis":{"status":"DOWN","details":{
    "error":"org.springframework.data.redis.RedisConnectionFailureException: Unable to connect to Redis"}}
}}
```

**根因**：`mall-demo` 通过 `mall-mbg → mall-common` 拿到了 `spring-boot-starter-data-redis`，
所以 Spring Boot 会自动装配 Redis 连接工厂并挂上 redis 健康指示器；
但 `config/demo/mall-demo-dev.yaml` 里**根本没有 `spring.data.redis` 配置块**，
于是走默认值 **`localhost:6379`** —— 而工作区的 Redis 在 **6380**。

**这是上游仓库自身的缺口，不是我们改坏的**：`mall-demo-dev.yaml.orig`（改动前备份）里也没有 redis 块。
上游用 Docker 起 Redis 时 6379 是默认端口，所以原作者没暴露这个问题；
我们把端口改成 6380 之后它才显形。

**修法**：给 `config/demo/mall-demo-dev.yaml` 补上 redis 块（与其它模块对齐），再重新发布：

```yaml
spring:
  datasource:
    url: jdbc:mysql://localhost:3308/mall?...
    username: root
    password: 123456
  data:
    redis:
      host: localhost
      database: 0
      port: 6380
      password:
      timeout: 3000ms
```

```bash
python tools/p2-publish-nacos-configs.py     # 重新发布到 Nacos
./p2.sh stop demo && ./p2.sh start demo      # 重启 demo
curl -s http://127.0.0.1:8082/actuator/health   # 应为 UP，且 redis 组件 UP（version 8.10.2）
```

**顺带说明「为什么这个错值得查」**：端口在听 + `Started ...` 打出来了，
很容易以为「起来了就行」。但 actuator 聚合状态是 DOWN 意味着**至少一个健康指示器在报错**，
对 demo 来说是 Redis、对 search 来说当初是 ES。**每次启动完都应该看一眼 `/actuator/health`**，
而不是只看端口。

---

### 坑 9：延迟队列「消息到期了却不转发」—— per-message TTL 的队头阻塞

**现象**：订单 77 在 `normal_order_overtime=120` 时下单，消息进了 `mall.order.cancel.ttl`。
随后把超时临时改成 1 分钟、又下了订单 78，**等 80 秒后订单 78 状态仍是 0（没被取消）**，
而且队列消息数**不降反升**（2 → 3）。

**根因**：`mall.order.cancel.ttl` 是 **classic 队列 + 逐消息 TTL**（`expiration` 设在消息属性上，
不是队列的 `x-message-ttl`）。classic 队列**只从队头淘汰消息** —— 队头那条 120 分钟 TTL 的消息
没过期，排在它后面的 1 分钟消息**永远轮不到被淘汰**，也就不会死信转发。

队列声明参数可以自证：

```
mall.order.cancel.ttl  arguments =
  [{"x-dead-letter-exchange","mall.order.direct"},
   {"x-dead-letter-routing-key","mall.order.cancel"},
   {"x-queue-type","classic"}]        ← 没有 x-message-ttl，说明 TTL 是逐消息设的
```

绑定也是对的（`mall.order.direct.ttl → mall.order.cancel.ttl`、
`mall.order.direct → mall.order.cancel`）—— **所以「绑定正确」并不能推出「消息会转发」**。

这是 RabbitMQ 官方文档写明的 TTL 语义，**不是 mall 的 bug，也不是环境问题**。
mall 上游固定用 120 分钟、队列里所有消息 TTL 一致，所以永远撞不上队头阻塞；
只有我们为了做验证去动态改超时，才会造出「长 TTL 排在短 TTL 前面」这种组合。

**复现/验证延迟队列的正确姿势**（要么清空队列，要么让 TTL 单调递增）：

```bash
# ① 清空队列，消除队头阻塞
MSYS_NO_PATHCONV=1 ./run-rabbitmq.cmd ctl purge_queue -p /mall mall.order.cancel.ttl

# ② 把超时改成 1 分钟，下一单；下单后立刻确认队列里恰好 1 条
MSYS_NO_PATHCONV=1 ./run-rabbitmq.cmd ctl list_queues -p /mall name messages
#   mall.order.cancel.ttl  1        ← 必须是 1，多了就说明还有别的消息在队头

# ③ 等 75 秒，队列应回到 0，订单 status 0 → 4
```

**教训**：

- **「消息没转发」先看队头那条的 TTL，再看绑定。** 绑定、死信参数全对，也可能一条都不动。
- 生产上做延迟队列，**不要用「classic 队列 + 逐消息 TTL」**。三个正确选择：
  ① `x-queue-type=quorum` + **队列级** `x-message-ttl`；
  ② 装 `rabbitmq_delayed_message_exchange` 插件用延迟交换机；
  ③ 按延迟档位拆成多个队列（每档 TTL 相同，天然没有队头阻塞）。
- 排查时**不要用 `messages` 一个数字判断**，要连 `consumers` 和队列 `arguments` 一起看。

---

## 9. 启动验证结果（2026-09-28 实测）

**一条命令复验全部结论**（推荐以后每次改完配置都跑一遍）：

```bash
cd /d/java-workspace
"C:/Users/Administrator/.workbuddy-ai/binaries/python/envs/default/Scripts/python.exe" \
    tools/p2-e2e-test.py --rabbit-ctl "D:\\java-workspace\\run-rabbitmq.cmd"
```

它不看端口，而是**用业务动作把每件中间件打一遍**：7 个模块的 `/actuator/health`、
Nacos 注册表、管理端登录+查商品、ES 导入+中文检索、会员登录+浏览记录读写、
加购物车→算钱→下单→查队列深度。**当前 27/27 通过。**

### 9.1 构建

```bash
./p2.sh build
```

```
mall-swarm .......... SUCCESS      mall-search ......... SUCCESS
mall-common ......... SUCCESS      mall-portal ......... SUCCESS
mall-mbg ............ SUCCESS      mall-monitor ........ SUCCESS
mall-demo ........... SUCCESS      mall-gateway ........ SUCCESS
mall-admin .......... SUCCESS      mall-auth ........... SUCCESS
BUILD SUCCESS   （10 个模块，约 30 秒）
```

### 9.2 七个模块逐个启动

```bash
./p2.sh start
```

| 模块 | 端口 | 启动耗时 | 日志中的证据 | health |
|---|---|---|---|---|
| mall-gateway | 8201 | 32.976 s | `Started MallGatewayApplication` | UP |
| mall-admin | 8080 | 40.119 s | `Started MallAdminApplication` | UP（db + redis） |
| mall-auth | 8401 | 23.600 s | `Started MallAuthApplication` | UP |
| mall-portal | 8085 | 38.536 s | `Started MallPortalApplication` | UP（db + redis） |
| mall-search | 8081 | 32.933 s | `Started MallSearchApplication` | UP（db） |
| mall-demo | 8082 | 34.070 s | `Started MallDemoApplication` | UP（db + redis） |
| mall-monitor | 8101 | 27.462 s | `Started MallMonitorApplication` | UP |

**7/7 UP，0 个 `APPLICATION FAILED TO START`。**

### 9.3 Nacos 注册表

```bash
curl -s "http://127.0.0.1:8848/nacos/v1/ns/service/list?pageNo=1&pageSize=20"
```

7 个服务全部注册：`mall-admin` `mall-auth` `mall-demo` `mall-gateway` `mall-monitor` `mall-portal` `mall-search`。

### 9.4 端到端业务链路

| # | 链路 | 请求 | 结果 |
|---|---|---|---|
| 1 | 网关 → auth → Feign → admin → MySQL | `POST /mall-auth/auth/login?clientId=admin-app&username=macro&password=macro123` | `code=200`，返回 183 字符 JWT |
| 2 | 网关 → admin → MySQL → RBAC | `GET /mall-admin/product/list?pageNum=1&pageSize=2`（带 token） | `code=200`，`total=20`，中文商品名正常 |
| 3 | 网关 → portal → MySQL | `GET /mall-portal/product/search?keyword=小米` | `code=200`，命中 6 条 |
| 4 | portal 会员登录 → Redis（sa-token） | `POST /mall-portal/sso/login?username=test&password=123456` | `code=200`，返回 JWT |
| 5 | portal → MongoDB 写 | `POST /mall-portal/member/readHistory/create`（JSON body） | `code=200, data=1`；MongoDB 自动建出 `mall-port` 库 |
| 6 | portal → MySQL（购物车） | `POST /mall-portal/cart/add`（JSON body，必须带 `price`） | `code=200`；落库 `oms_cart_item` |
| 7 | portal → MongoDB 读 | `GET /mall-portal/member/readHistory/list?pageNum=1&pageSize=5` | `code=200`，能读回刚写的记录 |
| 8 | search → ES + IK | `POST /mall-search/esProduct/importAll` → `GET /mall-search/esProduct/search?keyword=小米` | `data=20` 导入；检索命中 6 条，中文名完整 |

**测试账号**

| 端 | 账号 | 密码 | 说明 |
|---|---|---|---|
| 管理后台 | `macro` | `macro123` | 超级管理员，登录时 `clientId=admin-app` |
| 用户端 | `test` / `windy` / `lisi` | `123456` | 种子数据里的会员，密码是 BCrypt |

> 管理端登录：`POST /mall-auth/auth/login?clientId=admin-app&username=macro&password=macro123`
> 用户端登录：`POST /mall-portal/sso/login?username=test&password=123456`
> 两者的 token 用法一样：`Authorization: Bearer <token>`。

### 9.5 完整下单链路（一次请求串起 4 个中间件）

这是最有说服力的一条 —— 一个真实业务动作同时用到了 **MySQL + Redis + RabbitMQ + 服务发现**：

```bash
# ① 会员登录（Redis 存 sa-token 会话）
MT=$(curl -s -X POST "http://127.0.0.1:8201/mall-portal/sso/login?username=test&password=123456" \
     | python -c "import json,sys;print(json.load(sys.stdin)['data']['token'])")

# ② 生成订单（校验库存/优惠券 → 写 oms_order → 发延迟消息）
curl -s -X POST "http://127.0.0.1:8201/mall-portal/order/generateOrder" \
  -H "Authorization: Bearer $MT" -H "Content-Type: application/json" \
  -d '{"memberReceiveAddressId":4,"useIntegration":0,"payType":1,"cartIds":[115]}'
```

**结果**：

```json
{"code":200,"message":"下单成功","data":{
  "order":{"id":77,"orderSn":"202609280101000001","memberUsername":"test", ...},
  "orderItemList":[{"orderId":77,"productId":27,"productQuantity":4,
                    "realAmount":2024.2500,"giftIntegration":2699, ...}]}}
```

**四个中间件各自的证据**：

| 中间件 | 证据 |
|---|---|
| MySQL | `oms_order` 出现 `id=77, order_sn=202609280101000001, pay_amount=8097.00, status=0`；`oms_order_item` 出现对应行；购物车行 `115` 被软删（`delete_status=1`） |
| Redis | 登录 token 的 sa-token 会话写在 6380，后续请求靠它鉴权 |
| RabbitMQ | `mall.order.cancel.ttl` 队列从 **0 条变成 1 条** —— 延迟取消消息发出去了 |
| Nacos | 请求经 8201 网关按 `lb://mall-portal` 路由过去 |

延迟时长来自数据库，不是写死的：`oms_order_setting.normal_order_overtime = 120`（分钟），
代码里 `delayTimes = orderSetting.getNormalOrderOvertime() * 60 * 1000`。
所以这条消息会在 `mall.order.cancel.ttl` 里**待 120 分钟**，到期后死信转发到
`mall.order.cancel`，由消费者把订单关掉（`status` 0 → 4）。

> 想立刻看到死信转发，不用等 120 分钟 —— 改小 `normal_order_overtime` 再下一次单，
> 或者直接用 `tools/p2-rabbitmq-test.py`（那个脚本把 TTL 设成秒级，11/11 通过）。

### 9.6 现象记录：中间件会被外部整批杀掉

验证过程中遇到过一次「8 个中间件**同时**从 LISTENING 变 stopped」，
而 7 个 P2 模块**依然在听**（它们是 `nohup` 脱离的，中间件是 `cmd start` 拉起的）。
Redis 日志里最后一条是**成功的** BGSAVE，之后没有任何 shutdown 记录 ⇒ 是被外部强杀，不是崩溃。

当时的表现是业务接口突然报：

```
{"code":500,"message":"Redis command timed out"}
```

**处置**：一条命令恢复全部中间件，P2 模块会自己重连（不用重启模块）：

```bash
bash svc.sh status        # 先确认到底哪些没了（不要只看端口，也不要凭印象）
bash svc.sh start full    # 全部拉起，约 60 秒
./p2.sh health            # 模块侧复查
```

**教训**：
- **不要假设「刚才还在跑」就现在还在跑。** 每次开始干活前先 `svc.sh status` + `./p2.sh status`。
- **报错先怀疑基础设施，再怀疑代码。** `Redis command timed out` 的第一反应应该是
  「Redis 还在不在」，而不是去读业务代码。
- 中间件和模块的**存活策略不一样**：模块用 `nohup` 脱离会话，比中间件活得久。
  所以会出现「模块在听、但中间件没了」这种半死状态 —— 端口在听不代表健康。

### 9.7 已知的非环境问题

`POST /mall-portal/order/generateConfirmOrder` 传**手工塞进去的**购物车行
（`price` 为 NULL 的那种）会 500：

```
java.lang.NullPointerException: Cannot invoke "java.math.BigDecimal.subtract(...)"
because the return value of "CartPromotionItem.getPrice()" is null
    at UmsMemberCouponServiceImpl.calcTotalAmount(UmsMemberCouponServiceImpl.java:217)
```

这是**上游代码对脏数据不设防**（没有价格就直接做减法），不是环境配置问题。

注意 `/cart/add` **不会自己算价格** —— `OmsCartItemServiceImpl.add` 只把传进来的
`OmsCartItem` 存下去，价格由前端给。所以用 curl 手工造购物车时**必须带 `price`**，
否则后续下单流程会在算钱那一步 NPE。补一条 SQL 就能继续：

```sql
UPDATE oms_cart_item SET price = 2699.00 WHERE id = 115;
```

### 9.8 延迟取消闭环（TTL 到期 → 死信转发 → 消费者关单 → 库存回滚）

§9.5 只证明了「消息发出去了」。这一节证明**后半段也通了** —— 这是整个 P2 里
唯一需要「等时间」才能看到的链路，也是 RabbitMQ 能力真正的落点。

**实验设计**：为了不等 120 分钟，把 `oms_order_setting.normal_order_overtime` 临时改成 `1`，
并按坑 9 的要求**先清空 TTL 队列**（否则长 TTL 消息会堵住短 TTL 消息），
使队列中只有本单这一条消息。

**① 下单瞬间**（`generateOrder`，17:39:01）

```json
{"code":200,"orderId":80,"orderSn":"202609280101000004","pay":18893.0,"status":0}
```

```
mall.order.cancel.ttl   messages=1  consumers=0     ← 延迟消息入队，恰好 1 条
mall.order.cancel       messages=0  consumers=1     ← 消费者在等
```

**② TTL 到期后**（17:40:01，正好 60 秒，误差 <1s）

```
mall.order.cancel.ttl   messages=0  consumers=0     ← 消息已死信转发走
mall.order.cancel       messages=0  consumers=1     ← 被消费者取走并处理
```

订单状态：

```
id  order_sn              status
80  202609280101000004    4        ← 0(待付款) → 4(已关闭)
```

**③ mall-portal 日志（决定性证据）**

```
17:40:01.324 [tContainer#0-15] OmsOrderMapper.selectByExample
             WHERE (id=? and status=? and delete_status=?)   → 80, 0, 0
17:40:01.333 [tContainer#0-15] updateByPrimaryKeySelective oms_order
             ... status = 4 ...                               <== Updates: 1
17:40:01.344 [tContainer#0-15] PortalOrderDao.releaseSkuStockLock
             UPDATE pms_sku_stock SET lock_stock = lock_stock - ? WHERE id IN (?) → 7, 225
17:40:01.347 [tContainer#0-15] CancelOrderReceiver : process orderId:80
```

**这条链路证明了四件事**：

| # | 结论 | 证据 |
|---|---|---|
| 1 | 延迟消息按 TTL 精确到期 | 17:39:01 入队 → 17:40:01 转发，TTL=60s 严丝合缝 |
| 2 | 死信按 `x-dead-letter-*` 正确路由 | `.ttl` 队列 1→0，`mall.order.cancel` 消费掉 |
| 3 | 消费者真的在监听并执行业务 | 线程名 `tContainer#0-15` 是 Spring AMQP 监听容器；日志打 `process orderId:80` |
| 4 | 关单会**回滚库存锁** | `lock_stock - 7`，且 SQL 里 `WHERE status=0` 保证只取消未支付订单 |

> 顺带解释了 §9.5 里 `oms_cart_item.price` 为什么必须是手动补的：
> `OmsCartItemServiceImpl.add()` 是**原样 insert**，不查商品表补价格/商品名。
> 真实前端是先调商品详情接口拿到 `price` 再一起提交的。所以 curl 手工造购物车
> 必须自己带 `price`，否则 `handleRealAmount` / `calcTotalAmount` 会 NPE。

**实验后已复原**：`normal_order_overtime` 改回 `120`；订单 77/78/80 用
`POST /order/cancelUserOrder?orderId=X` 关掉（它们的取消消息在清队列时被 purge 了，
不会再有延迟消息兜底）；队列最终 `messages=0`。

