# 项目工作台（dashboard）

把 P0–P4 五个项目集中到一个页面里：**看状态、按条件筛、一键启停、一键打开**。

```bash
cd /d/java-workspace
python dashboard/server.py          # 打开 http://127.0.0.1:8990/
```

---

## 1. 它解决什么问题

工作区里有五个项目，各自的启动方式都不一样：

| 项目 | 怎么起 | 依赖 |
|---|---|---|
| P0 eladmin-mp | JDK 8 + `java -jar` | MySQL 5.7、Redis |
| P1 yu-ai-agent | JDK 21 + `java -jar` | MySQL 8、Redis、**Ollama** |
| P2 mall-swarm | `./p2.sh start`（7 个模块） | 6 个中间件 |
| P3 seckill | — | 还没有代码 |
| P4 exam-tracker | JDK 17 + `java -jar` | MySQL 8 |

也就是说，想跑起任何一个项目，你都得先记住「用哪个 JDK、要不要先起中间件、端口是多少」。
这份记忆分散在 6 份文档里，而且**忘了一步不会报「你忘了一步」，只会报一堆看不懂的错**。

工作台把这些收进一份声明式清单（`projects.json`），并且**真的能替你把这些步骤跑完**。

---

## 2. 文件构成

```
dashboard/
├── projects.json     声明式项目清单 —— 加项目只改这个文件
├── server.py         零依赖本地服务（标准库 http.server）
├── web/
│   ├── index.html
│   ├── style.css     深浅色 + 响应式，无 CSS 框架
│   └── app.js        无框架、无构建步骤
└── verify-ui.js      用真浏览器跑 55 项界面断言
```

合计约 3,200 行，其中 `server.py` 1,244 行、`projects.json` 243 行、前端 1,412 行。

**没有第三方依赖，是有意为之**：这个工作区从头到尾的卖点是「删掉 `D:\java-workspace` 就等于完全回滚」。
引入 Flask 或 Vite 就等于引入一个 `pip install` / `npm install` 步骤，
回滚时还得记得清理 site-packages 或 node_modules —— 那就不叫「零残留」了。
标准库够用，因为这个服务的并发量是 1（你自己）。

---

## 3. 界面能做什么

### 3.1 看

每张卡片上：阶段号、**来源（原创 / 克隆学习 / 计划中）**、类别、项目名、一句话标题、
简介、技术栈、标签、**实时状态**、端口、以及「打开 / 停止 / 详情」按钮。

顶部四条筛选（状态 / 类别 / 来源 / 标签）+ 一个搜索框，搜索范围包括项目名、简介、
技术栈、标签、路径。卡片和列表两种视图。

点「详情」开右侧抽屉，里面有：完整简介、运行状态（含每个端口的监听情况**和占用它的进程名**）、
来源与仓库地址、绝对路径、构建产物是否存在、前置中间件、技术栈、标签、**启动命令原文**、
相关文档、以及两个日志视图（启动过程逐步日志 + 应用日志）。

### 3.2 启停

点「启动」之后，工作台会依次做：

1. 检查前置中间件，缺的自动起（`svc.sh` 或对应的启动器）
2. 检查构建产物在不在（不在就立刻报错，不会让你等 120 秒再超时）
3. `source use-jdk.sh <版本>` 切 JDK，然后 `exec java -jar ...`
4. 轮询端口直到就绪，全程把每一步写进「启动过程」日志

这个过程是**异步**的 —— 接口立刻返回，页面轮询进度，不会转圈转两分钟。

### 3.3 中间件面板

页面底部可以展开，看到 9 个中间件的端口、版本、运行状态和占用端口的进程名，
`svc.sh` 管得到的可以直接启停（Ollama 走 `run-ollama.cmd`，工作台也能代启）。

---

## 4. 加一个新项目

只改 `projects.json`，不用动代码。页面右上角「＋ 新增项目」会把一份模板和步骤显示出来，
可以直接复制。

最小配置长这样：

```json
{
  "id": "p5-my-project",
  "stage": "P5",
  "name": "my-project",
  "title": "一句话标题",
  "summary": "2-3 行简介。",
  "category": "api",
  "tags": ["标签一"],
  "origin": { "kind": "original", "repo": "https://github.com/你/仓库", "note": "来源说明" },
  "path": "p5-my-project",
  "ports": [{ "port": 8099, "label": "HTTP" }],
  "stack": ["Java 17", "Spring Boot 3.5"],
  "middleware": ["mysql8"],
  "launch": {
    "type": "jar", "jdk": "17", "cwd": "p5-my-project",
    "jar": "target/my-project-1.0.0.jar",
    "args": ["--server.port=8099"],
    "logFile": "dashboard-p5.log", "readyTimeoutSec": 120
  }
}
```

改完点右上角**「重载配置」**，页面立刻生效，服务不用重启。

### 几个字段的取值规则

- **`origin.kind`** 三选一：`original`（自己手写的）/ `clone`（克隆来学习的）/ `planned`（还没代码）。
  这一项**必须如实填**，界面上会直接显示成徽标。理由见第 6 节。
- **`category`** 必须是文件里 `categories` 数组里的某个 id，否则卡片会显示原始值。
- **`launch.type`**：
  - `jar` —— 用 `java -jar` 起，需要 `jdk` / `cwd` / `jar`
  - `script` —— 调工作区里的 `.sh`，需要 `script` / `startArgs` / `stopArgs`
  - `none` —— 不支持启动，只写 `reason`
- **`launch.strictMiddleware`** 默认 `true`：缺中间件就拒绝启动。
  P2 设成了 `false` —— 它有 7 个模块、依赖各不相同，能起几个是几个，起不来的如实报出来。
- **`ports[].optional`** 标了 `true` 的端口不参与「算不算起来了」的判定，
  但没起来时会在卡片上明确报出来。P2 的 `8085 / 8082 / 8101` 就是这一类。
- **`launch.logGlob`** 日志分散在多个文件时用它。P2 的每个模块各写一份 `logs/p2-*.log`，
  `p2.sh` 自己只输出一张状态表，只看 `dashboard-p2.log` 等于什么都没看到。

---

## 5. 验证

```bash
# 界面（真浏览器，55 项断言，含三个断点的响应式截图）
NODE_PATH="C:/Users/Administrator/.workbuddy-ai/binaries/node/workspace/node_modules" \
  "C:/Users/Administrator/.workbuddy-ai/binaries/node/versions/22.22.2-3/node.exe" \
  dashboard/verify-ui.js
```

跑完会往 `docs/screenshots/` 写 5 张图（桌面 / 平板 / 手机 / 手机卡片 / 深色），
失败时往 `target/` 写诊断图（不进仓库）。

### 实测结果（2026-09-29）

| 项目 | 启动耗时 | 结果 |
|---|---|---|
| P4 exam-tracker | 12.8s（含自动起 MySQL 8） | ✅ 运行中，`/api/` 返回真实前端页 |
| P0 eladmin-mp | 11.6s（含自动起 MySQL 5.7 + Redis） | ✅ 运行中，`/auth/code` 返回真实验证码 |
| P1 yu-ai-agent | 32.6s（含自动起 Ollama） | ✅ 运行中，AI 对话接口返回真实模型输出 |
| P2 mall-swarm | 166s（含自动起 5 个中间件） | ✅ 7 个模块全部就绪 |
| P3 seckill | — | 拒绝启动并说明原因 |

界面：**55/55 断言通过**。

---

## 6. 设计上踩过的坑（都不是猜的）

### 6.1 「端口在听」≠「服务起来了」

最初 `running` 的判定就是「端口在监听」。然后发现 **`5672` 被 `WorkBuddyAI.exe` 占着** ——
宿主客户端自己也用了这个端口。于是工作台理直气壮地显示「RabbitMQ 运行中」，
而 RabbitMQ 一个字节都没跑起来。

`svc.sh status` 也踩了同一个坑（它输出 `RabbitMQ 5672 LISTENING`）。

**修法**：加一层 `tasklist` 核验 —— 端口在听之后，再问一次「监听它的是哪个进程」，
和 `processHint` 对不上就标成「端口被占用」，并且**不算作运行中**。

这不是理论问题。P2 的 `mall-portal` 启动日志里是这么写的：

```
Attempting to connect to: [localhost:5672]
java.lang.IllegalStateException: Frame body is too large (1345270062)
```

RabbitMQ 客户端正在跟 WorkBuddy AI 说话。**要跑完整的 P2，得先关掉 WorkBuddy 客户端，
或者把 RabbitMQ 换一个端口。**

### 6.2 `svc.sh start` 只接受一个 target

`svc.cmd` 里是 `set "TARGET=%~2"` —— 第二个参数之后的一律丢弃。

踩法：工作台最初调 `svc.sh start mysql57 redis`，结果只起了 mysql57，
redis 被**静默忽略**，然后工作台老老实实等了 180 秒才报「Redis 没起来」。
退出码还是 0，看上去一切正常。

**修法**：一个服务一次调用。顺带好处是 `svc.cmd` 会等每个服务自己的端口就绪，
返回时就带上了精确的成败信息。

### 6.3 启动命令不自己拼环境变量

工作区里 `use-jdk.sh` 干的不只是切 `JAVA_HOME`，它还：

- `unset SERVER__PORT SERVER__HOST` —— WorkBuddy 会往每个子进程注入这两个变量，
  Spring Boot 的松散绑定会把 `SERVER__PORT` 当成 `server.port`，
  应用会去抢宿主端口然后 `PortInUseException` 死掉
- 给 JDK 8 / 17 设 `JAVA_TOOL_OPTIONS` 修编码（中文 Windows 下默认 GBK，
  日志和异常堆栈会变成乱码，而且**不报错**）

这些逻辑在工作台里重写一遍就会两边漂移。所以启动是这么拼的：

```bash
bash -c 'source use-jdk.sh 17 && cd <cwd> && exec java -jar <jar> <args>'
```

实测证据（`logs/dashboard-p0.log`）：

```
[launcher] JAVA_HOME=D:\java-workspace\.jdks\corretto-8
Picked up JAVA_TOOL_OPTIONS: -Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8
```

### 6.4 别为「等不到的东西」浪费时间

RabbitMQ 的端口被别的进程占着时，等多久都不会变成 RabbitMQ。
最初没排除这种情况，白等了整整 120 秒。

**修法**：等待列表里先把「端口已被别的进程占住」的剔除掉，并且日志里明确写
`⏭ 不等 RabbitMQ 了 —— 它的端口已经被别的进程占住，等也不会变`。

同理，`run-ollama.cmd` 不在 `svc.sh` 的管理范围内，最初被当成「管不了」直接跳过，
又白等 90 秒。现在它作为 `launcher` 类型由工作台代启（3 秒起好）。

### 6.5 「必需端口齐了就显示运行中」是假绿灯

P2 有 7 个模块。最初的判定是「必需端口（网关/后台/认证/搜索）齐了 = 运行中」，
于是 `mall-portal` 挂了的那次，卡片显示的是**运行中** —— 界面上完全看不出少了两个模块。

**修法**：必需端口全绿 **且没有可选模块掉队** 才算「运行中」，否则显示「部分运行」
并列出掉队的是谁、为什么。

### 6.6 可选端口只是「慢」，不是「挂」

`mall-portal` / `mall-demo` 实测比必需端口晚约 60 秒（要等 Nacos 配置拉完才起 Tomcat）。
不等一下就报「8085 没起来」是假警报。现在必需端口就绪后会再等 75 秒给可选端口。

### 6.7 筛选中的标签必须出现在卡片上

卡片上只放得下 6 个标签。按 `Java 17` 筛选时，`Java 17` 在 P2/P4 的标签列表里都排在第 7 位以后 ——
筛出来的卡片上根本找不到匹配项，看起来就像筛选坏了。

**修法**：筛选中的标签被顶到第一位并高亮，被截断的标签显示成 `+N`。

### 6.8 `waitForFunction` 的参数位置

`page.waitForFunction(fn, {timeout: N})` 里的 `{timeout: N}` 会被当成 `arg` 吃掉，
实际用默认的 30 秒。必须写 `page.waitForFunction(fn, null, {timeout: N})`。

---

## 7. 安全边界

- **只绑 `127.0.0.1`**。这个服务能启动本机进程，绝不能对局域网暴露。
- 静态文件服务限制在 `web/` 目录内，`../` 穿越返回 403（已实测）。
- `/api/system` 只返回 JDK 路径、中间件端口这类环境信息，**不含任何凭据**。
- 停止中间件时会先核对占用端口的进程名，对不上就拒绝结束（409），
  避免误杀别人的进程。

---

## 8. 已知限制

- **P1 离不了 Ollama**。`loveAppVectorStore` 这个 Bean 在 Spring 上下文初始化时就会去调
  `11434/api/chat`，连不上直接 `Error starting ApplicationContext`。
  工作台会先把 Ollama 起起来，但这也意味着 P1 的启动时间受 Ollama 影响。
- **P2 跑不全**。`mall-portal` 的 RabbitMQ 监听器连的是被 `WorkBuddyAI.exe` 占着的 5672，
  会持续报 `Frame body is too large`。HTTP 端口最终会起来，但「订单超时取消」那条链路是坏的。
- **状态是轮询的**（空闲 8 秒 / 有任务 1.5 秒一次）。它不是事件驱动的，
  所以「你在别的终端手工起了个服务」最多 8 秒后才反映到界面上。
- 工作台自己重启后，内存里的「启动过程日志」会清空（应用日志不受影响，那是落盘的）。
