# P0 — eladmin-mp 启动手册

> 状态：**✅ 端到端验证通过**（2026-09-28）
> 编译成功 → 启动成功 → 真实登录成功 → 业务接口返回数据

---

## 1. 一句话配方

```bash
cd /d/java-workspace/p0-eladmin-mp/eladmin
source /d/java-workspace/use-jdk.sh 8        # 必须：项目是 Java 1.8
mvn -DskipTests -B clean package             # 首次约 2 分钟（要拉依赖），之后 ~5 秒
java -jar eladmin-system/target/eladmin-system-1.1.jar
# 浏览器打开 http://localhost:8000   账号 admin / 123456
```

前置条件：中间件要在跑。

```bash
cd /d/java-workspace && bash svc.sh start all    # MySQL 5.7(3307) + MySQL 8(3308) + Redis(6380)
bash svc.sh status
```

---

## 2. 这个项目依赖什么

| 项 | 值 | 为什么 |
|---|---|---|
| JDK | **8** | `pom.xml` 里 `<java.version>1.8</java.version>`；Spring Boot **2.7.18** |
| 数据库 | **MySQL 5.7 @ 3307**，schema **`eladmin`** | 见下方「为什么是 5.7 而不是 8」 |
| Redis | **6380**，**DB 1** | 项目原本用 6379；`database: 1` 保留未改 |
| 端口 | **8000** | 项目默认 |
| 账号 | `admin / 123456`（种子数据） | `README.md` 里写的 |
| 构建 | 系统 Maven 3.9.16 | ⚠️ **这个项目没有 `mvnw`**，只能用系统 mvn |
| 模块数 | 5 | common / logging / system / tools / generator |

### 为什么是 MySQL 5.7 而不是 8.0
eladmin 是 Spring Boot 2.7 时代的老项目。它的 `sql/eladmin.sql` 里有 **1 处 `utf8mb3`**
（第 718 行）—— 那是 MySQL 8 才引入的 `utf8` 别名，5.7 不认。
反过来，MySQL 8 把 `rank`/`groups`/`system` 等变成保留字，老 SQL 里裸用会直接语法错误。

所以工作区准备了两个 MySQL 实例：**P0 走 5.7（3307）**，P1/P2 走 8.0（3308）。
加载 eladmin 的 SQL 时用 `sed` 在管道里把 `utf8mb3` 换成 `utf8`，**不改仓库里的原文件**：

```bash
sed 's/utf8mb3/utf8/g' p0-eladmin-mp/eladmin/sql/eladmin.sql | mysql ... --database=eladmin
```

---

## 3. 改了哪两个配置（原值都保留在注释里）

只改了 2 个文件、3 个值。改之前先 `grep` 全仓库确认过没有别处要动：

```bash
grep -rn "3306\|eladmin-mp\|6379" p0-eladmin-mp --include="*.yml"
# 只有下面这两处命中
```

### ① `eladmin-system/src/main/resources/config/application-dev.yml`

```yaml
url: jdbc:p6spy:mysql://localhost:3307/eladmin?serverTimezone=Asia/Shanghai&characterEncoding=utf8&useSSL=false
#                      ^^^^ 3306→3307              ^^^^^^^ eladmin-mp→eladmin
```

原值是 `localhost:3306/eladmin-mp`。
**`p6spy:` 前缀没动** —— 那是 SQL 监控代理，删了 Druid 的监控页就没数据了。
**`root/123456` 没动** —— 正好和工作区的 root 密码一致。

### ② `eladmin-system/src/main/resources/config/application.yml`

```yaml
port: ${REDIS_PORT:6380}     # 原值 6379
```

`database: ${REDIS_DB:1}` **没动** —— 正好和工作区「DB1 = eladmin」的约定一致。

### 为什么用 `dev` 而不是 `prod`
`application-prod.yml` 确实已经用了环境变量占位符（`${DB_NAME:eladmin}`，默认值还正好是我建的 schema），
但 **prod 关掉了 swagger 和代码生成器** —— 那俩正是学习阶段最该看的东西。
所以走 dev，改两个值。

---

## 4. 验证清单（实际做过的）

```bash
# 1) 编译
mvn -DskipTests -B clean package
#    → BUILD SUCCESS，6 个模块全绿，首次 1:49

# 2) 启动
java -jar eladmin-system/target/eladmin-system-1.1.jar
#    → Started AppRun in 10.382 seconds

# 3) 端到端冒烟测试（脚本会自动还原验证码 + RSA 加密密码）
cd /d/java-workspace
"C:\Users\Administrator\.workbuddy-ai\binaries\python\envs\default\Scripts\python.exe" tools/p0-login-test.py
```

冒烟测试的实际输出：

```
  [OK]   1) GET /auth/code            -> 200, uuid=captcha_code:ba8ec179...
  [OK]   2) Redis DB1 取验证码答案     -> '24'
  [OK]   3) RSA 加密密码             -> zCDyQ9iaMUQtjMW0SbN3pMwowvcTkA6KN1YQAjot...（88 字符）
  [OK]   4) POST /auth/login          -> 200, 拿到 JWT（205 字符）
  [OK]   5) GET /auth/info            -> 200, 用户=admin
  [OK]   6) GET /api/menus/build      -> 200, 顶级菜单 6 个

结果：全部通过 —— P0 端到端可用（Web / MySQL 3307 / Redis 6380-DB1 / JWT 全通）
```

这 6 步各自证明了什么：

| 步骤 | 证明了 |
|---|---|
| 1 | Web 层（Tomcat）起来了 |
| 2 | **Redis 6380 + DB1 隔离正确**（验证码 key 落在 DB1，DB0 是空的） |
| 3 | 配置里的 `rsa.private_key` 可用 |
| 4 | **MySQL 3307 的 `eladmin` 库通了**（要查用户表才知道密码对不对） |
| 5 | JWT 签发 + 鉴权链路 |
| 6 | 业务表查询（`sys_menu` 有 70 行，返回 6 个顶级菜单） |

### 为什么需要这个脚本，curl 不行
eladmin 的登录**密码是 RSA 公钥加密后传输的**（后端 `RsaUtils.decryptByPrivateKey` 解密），
手写 curl 生成不了密文。脚本用配置里的私钥反推出公钥，复现了前端的加密：

```python
key = load_der_private_key(base64.b64decode(priv_b64), password=None)
ct = key.public_key().encrypt(b"123456", padding.PKCS1v15())   # RSA/ECB/PKCS1Padding
```

顺带一个便利：**验证码答案是以明文存在 Redis 里的**（`captcha_code:<uuid>`），
所以脚本能直接读出来，不需要 OCR。

---

## 5. ⚠️ 踩过的坑（两个都很难自己看出来）

### 坑 1：`SERVER__PORT` 环境变量劫持 `server.port` —— 日志里端口是 22407

**症状**：配置文件里明写 `server.port: 8000`，日志里却是

```
Tomcat initialized with port 22407 (http)
APPLICATION FAILED TO START ... PortInUseException: Port 22407 is already in use
```

`22407` 这个数字**在整个仓库里搜不到**，很容易怀疑到配置没生效、profile 选错、Maven 缓存等等方向上去。

**根因**：WorkBuddy 客户端会往它启动的**每一个**子进程里注入 `SERVER__HOST` / `SERVER__PORT`，
值是它自己后端服务的地址（22407 正是它自己在监听的端口）。
Spring Boot 的**松散绑定**把 `SERVER__PORT` 当成了 `server.port`，
于是应用去抢宿主自己的端口，撞车。

**验证方法**（一步定性）：

```bash
env | grep -i port          # 看到 SERVER__PORT=22407
env -u SERVER__PORT java -jar ...   # 端口立刻回到 8000
```

**已做的防御**：`use-jdk.sh` / `use-jdk.cmd` 在切换 JDK 时会 `unset SERVER__PORT SERVER__HOST`。
只要启动前 `source use-jdk.sh <版本>`，这个坑就不会再出现。

> 这个坑不是 eladmin 特有的 —— **Nacos 3.x 自己也中招了**（它就是个 Spring Boot 3.4 应用）。
> 凡是 Spring Boot 应用，从这个环境里启动都要注意。

### 坑 2：YAML 缩进写错，`driverClassName` 变成了 `db-type` 的子键

**症状**：

```
org.yaml.snakeyaml.scanner.ScannerException: mapping values are not allowed here
 in 'reader', line 6, column 24:
            driverClassName: com.p6spy.engine.spy.P6SpyDriver
                           ^
```

**根因**：手工编辑时把 `driverClassName` 和 `url` 写成了 8 空格缩进（应为 6 空格）：

```yaml
    druid:
      db-type: com.alibaba.druid.pool.DruidDataSource
        driverClassName: ...   # ← 多缩进了 2 格，成了 db-type 的子键
        url: ...
      username: root           # ← 这行是对的（6 空格），所以错误很隐蔽
```

**教训**：改完 YAML **立刻用解析器验一遍**，别等启动时才炸：

```bash
"C:\Users\Administrator\.workbuddy-ai\binaries\python\versions\3.13.12\python.exe" -c "
import yaml,glob
for f in sorted(glob.glob('**/*.yml',recursive=True)):
    try: yaml.safe_load(open(f,encoding='utf-8')); print('OK  ',f)
    except Exception as e: print('FAIL',f,'->',e)
"
```

### 坑 3（非本项目，但会咬人）：改了源码里的配置，**要重新打包**才生效

eladmin 的配置在 `src/main/resources/config/` 下，会被**打进 jar**。
改完源码里的 YAML 如果直接跑旧 jar，改动完全不生效 —— 而且不会有任何提示。

重建很快（依赖已缓存，约 5 秒）：

```bash
mvn -DskipTests -B package
```

想避免反复打包，可以外挂配置目录（优先级高于 jar 内的）：

```bash
java -jar eladmin-system/target/eladmin-system-1.1.jar \
  --spring.config.additional-location=file:D:/java-workspace/p0-eladmin-mp/eladmin/eladmin-system/src/main/resources/config/
```

---

## 6. 数据库现状（已灌好，不用再动）

| 项 | 值 |
|---|---|
| 实例 | MySQL 5.7.44 @ `127.0.0.1:3307` |
| schema | `eladmin` |
| 表数量 | **37**（26 张业务表 + 11 张 Quartz 表） |
| 数据 | `eladmin.sql`（198 条 INSERT）+ `quartz.sql` |
| 账号 | `root/123456`、`dev/dev123456` |
| 字符集 | `utf8mb4_unicode_ci`，时区 `+08:00` |
| 关键行 | `sys_menu` 70 行、`sys_role` 2、`sys_dept` 7、`sys_job` 4 |

> 11 张 Quartz 表正好是标准 Quartz schema 的表数，这是灌库成功的旁证。
> 另外 `sys_user` 的 `enabled` 字段是 `bit(1)`，直接 `SELECT` 会显示成空白 ——
> 那是二进制位不是空值，别误判成数据有问题。

---

## 7. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `Unsupported class file major version 65` | 用了 JDK 21 编译 | `source use-jdk.sh 8` |
| 日志中文乱码 | JDK 8/17 在中文 Windows 上默认 GBK | `use-jdk.sh` 已自动设 `-Dfile.encoding=UTF-8` |
| 端口是 22407 | `SERVER__PORT` 注入 | 用 `use-jdk.sh`（已自动清） |
| `Port 8000 already in use` | 上次的进程没退 | `netstat -ano \| grep ":8000 "` 然后 `taskkill //F //PID <pid>` |
| `Communications link failure` | 中间件没起 | `bash svc.sh status` / `bash svc.sh start all` |
| `Access denied for user 'root'` | 密码不是 123456 | 检查 `application-dev.yml` |
| `Table 'eladmin.xxx' doesn't exist` | 库灌漏了 | 见第 6 节 |
| 改动配置后无效果 | 配置在 jar 里 | 重新 `mvn package`，或用 `--spring.config.additional-location` |
