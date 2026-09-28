# P1 — yu-ai-agent 启动手册

> 状态：**构建 ✅ / 启动 ✅ / 5 个接口全部实测通过**（2026-09-28 最终验证）
> 走的是**本地 Ollama** 路线 —— 离线、零 API key、不花钱。
> 唯一的外部前提是先把 `run-ollama.cmd` 起来（见第 1 节）。
>
> 原始路线（阿里云 DashScope）也保留着，随时可切回，见第 3.4 节。

---

## 1. 一句话配方

```bash
# ① 先起本地大模型服务（前台常驻，另开一个窗口）
/d/java-workspace/run-ollama.cmd

# ② 起应用
cd /d/java-workspace/p1-yu-ai-agent
source /d/java-workspace/use-jdk.sh 21       # 必须：项目是 Java 21
./mvnw -DskipTests -B clean package          # 首次约 2:35，之后 ~5 秒
java -jar target/yu-ai-agent-0.0.1-SNAPSHOT.jar
# 浏览器打开 http://localhost:8123/api/doc.html
```

**前置条件：只有 Ollama。** 不需要数据库、不需要 Redis、不需要任何中间件
（`svc.sh start` 都不用跑）—— 详见第 4 节。

> ⚠️ 改了 `application-local.yml` 之后**必须重新打包** —— 它是打进 jar 里的。
> 直接改源码目录下的文件、不重新 `mvnw package`，跑起来还是旧配置。
> 这是第 7 节的坑 3，本项目上已经踩过一次。

---

## 2. 这个项目依赖什么

| 项 | 值 | 为什么 |
|---|---|---|
| JDK | **21** | `pom.xml` 里 `<java.version>21</java.version>`；Spring Boot **3.4.4** |
| 构建 | **`./mvnw`**（自带 wrapper） | 本机没有 Gradle，也不需要用系统 Maven |
| 端口 | **8123** | 项目默认 |
| context-path | **`/api`** | ⚠️ 所有接口前面都带 `/api`，忘了就会 404 |
| 数据库 | **无** | 实测启动日志里 `datasource` / `jdbc` / `hikari` **零匹配** |
| Redis | **无** | pom 里 redis / mybatis / sa-token 零命中 |
| 大模型 | **Ollama**（当前生效）/ DashScope（可切回） | 见第 3 节 |
| 外部服务 | SearchAPI（可选，只在联网搜索工具里用） | 见第 3.5 节 |
| 模块数 | **1**（单模块，`<module>` 数为 0） | 但有 2 个「额外可运行物」，见第 5 节 |

### 产物
```
target/yu-ai-agent-0.0.1-SNAPSHOT.jar   61 MB
```

### 技术栈版本（都来自 pom）
| | 版本 |
|---|---|
| `spring-boot-starter-parent` | 3.4.4 |
| `spring-ai-alibaba-bom` | （DashScope 那套） |
| `spring-ai-bom` | 1.0.x |
| 关键 starter | `spring-ai-alibaba-starter-dashscope`、`spring-ai-starter-model-ollama`、`spring-ai-starter-mcp-client`、`spring-ai-pgvector-store`、`spring-ai-markdown-document-reader` |

---

## 3. 两条路线：本地 Ollama（当前生效）/ DashScope（可切回）

这个项目的模型 provider 是可以换的，而**换起来比想象中麻烦**（见 3.3）。
下面按「当前生效 → 备选 → 踩过的坑 → 怎么切回」的顺序写。

### 3.1 当前路线：本地 Ollama —— 零 API key、离线、不花钱

**动机**：DashScope 那条路**必须有真实 key 才能启动**（见 3.2），而拿 key 要注册
阿里云账号。Ollama 完全本地，不需要任何外部凭据，也不需要联网。

**做法：只改 `application-local.yml`，不动 `pom.xml`、不动任何 `.java`。**

```yaml
spring:
  autoconfigure:
    exclude:                                    # ← 把 DashScope 的 7 个自动配置全排除
      - com.alibaba.cloud.ai.autoconfigure.dashscope.DashScopeChatAutoConfiguration
      - com.alibaba.cloud.ai.autoconfigure.dashscope.DashScopeAgentAutoConfiguration
      - com.alibaba.cloud.ai.autoconfigure.dashscope.DashScopeImageAutoConfiguration
      - com.alibaba.cloud.ai.autoconfigure.dashscope.DashScopeAudioSpeechAutoConfiguration
      - com.alibaba.cloud.ai.autoconfigure.dashscope.DashScopeAudioTranscriptionAutoConfiguration
      - com.alibaba.cloud.ai.autoconfigure.dashscope.DashScopeRerankAutoConfiguration
      - com.alibaba.cloud.ai.autoconfigure.dashscope.DashScopeEmbeddingAutoConfiguration
  ai:
    model:
      chat: ollama
      embedding: ollama
    ollama:
      base-url: http://localhost:11434
      chat:
        model: qwen3:0.6b
      embedding:
        model: nomic-embed-text
```

**为什么这招能成 —— 靠的是 `@Resource` 的「按名找不到就退化成按类型」。**

代码里到处是这种写法：

```java
@Resource private ChatModel dashscopeChatModel;                        // AiController / MyKeywordEnricher
VectorStore loveAppVectorStore(EmbeddingModel dashscopeEmbeddingModel) // LoveAppVectorStoreConfig
```

把 DashScope 排掉之后，容器里 `ChatModel` 只剩 `ollamaChatModel`、
`EmbeddingModel` 只剩 `ollamaEmbeddingModel`，**按类型唯一** ⇒ 照样注入成功。
所以代码一个字都不用改。

> ⚠️ 这条「侥幸」有边界：一旦容器里出现**两个**同类型的 bean，上面两处就退化成歧义。
> 所以以后加 provider 时要当心 —— 这也正是 3.3 里 `spring.autoconfigure.exclude`
> 必须「全部 7 个一起排」的原因。

**模型选择（实测数据，2026-09-28 本机 CPU）**

| 模型 | 体积 | tools | 启动耗时 | 主对话 |
|---|---|---|---|---|
| **`qwen3:0.6b`** ← 当前 | 522 MB | ✅ | 17.9 s | ~1 s |
| `gemma3:1b` | 815 MB | ❌ | 5.6 s | ~8 s（首次含加载） |
| `nomic-embed-text` | 274 MB | — | — | 仅 embedding，768 维 |

`gemma3:1b` **不支持工具调用**，调 `/ai/manus/chat` 会直接报：

```
400 - {"error":"registry.ollama.ai/library/gemma3:1b does not support tools"}
```

所以想要 5 个接口全通，只能用 `qwen3:0.6b`。代价是 qwen3 默认开 thinking，
启动时要对 3 个文档分片各抽一次关键词，启动从 5.6 s 变成 17.9 s。
**只跑 love_app 对话、不用 Agent 的话，换回 `gemma3:1b` 更划算。**

> Ollama 服务用工作区根目录的 `run-ollama.cmd` 启动，
> 详见 `runtime.md` 的 Ollama 一节（含 `OLLAMA_MODELS` / `OLLAMA_HOST` 两个必须钉死的变量）。

### 3.2 备选路线：DashScope —— 为什么「没有 key 就起不来」

一般项目「key 没填」的表现是：服务能起来，用到那个功能时才报错。
**P1 不是这样。key 无效 = 容器初始化失败 = 进程退出，退出码 1。**

#### 实测的失败链

```
Tomcat initialized with port 8123 (http)          ← 端口是对的，profile local 也是对的
...
WARN  SpringAiRetryAutoConfiguration : Retry error. Retry count: 1,
      Exception: HTTP 401 - {"code":"InvalidApiKey",...}
WARN  ConfigServletWebServerApplicationContext :
      Exception encountered during context initialization - cancelling refresh attempt:
      BeanCreationException: Error creating bean with name 'loveApp':
      Injection of resource dependencies failed
Caused by: Factory method 'loveAppVectorStore' threw exception with
      message: HTTP 401 - {"code":"InvalidApiKey",...}

APPLICATION FAILED TO START
```

#### 根因
`LoveAppVectorStoreConfig.loveAppVectorStore()` 这个 `@Bean` 在**容器初始化阶段**
就调用 `MyKeywordEnricher.enrichDocuments()`，而它内部要调 DashScope 的 chat 接口
给文档抽关键词。所以：

```
loveApp  →  loveAppVectorStore  →  MyKeywordEnricher.enrichDocuments  →  HTTP 401
```

**「起不来」和「端口/数据库」一点关系都没有。** 第一次遇到很容易往
「端口没生效」「profile 选错了」「要配数据库」这些方向查，会白花很多时间。

#### 2026-09-28 复测：边界已钉死 —— 唯一缺口就是 key

重跑一次（`logs/p1-run2.log`，198 行）逐项确认：

| 检查项 | 实测 | 结论 |
|---|---|---|
| `Tomcat initialized with port 8123 (http)` | ✅ | 端口没被 `SERVER__PORT` 劫持 |
| `The following 1 profile is active: "local"` | ✅ | profile 生效 |
| 依赖 / 类路径 / 编码 | ✅ | 无 `ClassNotFound`、无乱码 |
| 数据库 / JDBC / Hikari | 0 匹配 | 确实不需要数据库 |
| `loveAppVectorStore` 工厂方法 | ❌ `HTTP 401 InvalidApiKey` | **唯一的失败点** |

#### 为什么「只有一个失败点」值得单独记一笔

`LoveApp` 上有 3 个 `@Resource` 字段注入，看起来都像隐患，实际都自动化解了：

| 字段 | 声明的 bean | 实际解析 | 为什么没炸 |
|---|---|---|---|
| `ChatModel dashscopeChatModel` | DashScope 提供 | 按名命中 | 正常 |
| `VectorStore loveAppVectorStore` | 本类提供 | 按名命中 | 正常 |
| `VectorStore pgVectorVectorStore` | **不存在**（`PgVectorVectorStoreConfig` 的 `@Configuration` 被作者注释掉了） | **退化成按类型**，撞上唯一的 `VectorStore` | 侥幸 |
| `Advisor loveAppRagCloudAdvisor` | `LoveAppRagCloudAdvisorConfig` 提供 | 按名命中 | 正常 |

⇒ **`pgVectorVectorStore` 那一行是「靠 `@Resource` 的按类型兜底侥幸活着」。**
如果哪天有人把 `PgVectorVectorStoreConfig` 的注解取消注释，容器里就会同时出现
两个 `VectorStore` bean，这个字段**立刻**报 `NoUniqueBeanDefinitionException`。
不是现在的 bug，但值得知道它悬在那里。

⇒ **顺带结论（这条一开始写错了，2026-09-28 修正）**：
最初我以为「换 provider 必须连代码一起改，因为按名命中的注入会退化成按类型歧义」。
**这个推断是错的。** 实测只要**把旧 provider 的自动配置整个排干净**（3.1 的做法），
容器里同类型就只剩一个 bean，按类型兜底照样唯一 ⇒ **纯配置就能换 provider，代码一个字不用改。**

真正的风险在别处：如果哪天有人把 `PgVectorVectorStoreConfig` 的注解取消注释，
容器里就会出现两个 `VectorStore`，上面那张表里的 `pgVectorVectorStore` 字段
**立刻**报 `NoUniqueBeanDefinitionException`。不是现在的 bug，但它悬在那里。

### 3.3 ⚠️ 换 provider 时踩的三个坑（这一段是本文最有价值的部分）

#### 坑 A：`spring.ai.dashscope.chat.enabled: false` 是**死属性**

这个属性看起来很对，`spring-configuration-metadata.json` 里也确实有它：

```
spring.ai.dashscope.chat.enabled       default=True
spring.ai.dashscope.embedding.enabled  default=True
```

**实测完全无效** —— 改成 `false` 后启动照样 401，而且日志里没有任何提示。
反编译 `spring-ai-alibaba-autoconfigure-dashscope-1.0.0.2.jar` 才看清：

- `DashScopeChatProperties` 里确实有 `private boolean enabled` + `isEnabled()`
- 但 `DashScopeChatAutoConfiguration` 类上只有
  `@AutoConfiguration` / `@ConditionalOnClass` / `@ImportAutoConfiguration` / `@EnableConfigurationProperties`
  —— **没有 `@ConditionalOnProperty`**
- `dashscopeChatModel()` 这个 `@Bean` 方法上也**没有任何条件注解**

⇒ **属性存在 ≠ 属性生效。** 配置元数据里有它，不代表代码读它。

#### 坑 B：DashScope 的自动配置之间有**隐式 properties 依赖**，不能只挑着关

只排除 `DashScopeChatAutoConfiguration` + `DashScopeEmbeddingAutoConfiguration` 时，启动报：

```
UnsatisfiedDependencyException: Error creating bean with name 'dashscopeAgentApi'
  ... No qualifying bean of type 'DashScopeChatProperties' available
```

原因：`DashScopeChatProperties` 这个 bean 是靠 `DashScopeChatAutoConfiguration` 上的
`@EnableConfigurationProperties` 注册的。排掉 chat 自动配置 ⇒ properties 也没了 ⇒
`DashScopeAgentAutoConfiguration` 的 `@Bean` 方法依赖它 ⇒ 连锁失败。

⇒ **必须 7 个一起排**（清单见 3.1）。

#### 坑 C：`ChatClient.tools()` 和 `toolCallbacks()` 不是一回事 —— 这是项目里一个真 bug

`ToolCallAgent.java` 里原本写的是：

```java
.tools(availableTools)          // ❌ availableTools 是 ToolCallback[]
```

而 `ChatClient` 的签名是：

```java
tools(Object...)                     // 传「带 @Tool 注解的普通对象」，Spring AI 会反射去扫
toolCallbacks(ToolCallback...)       // 传已经构建好的回调  ← 应该用这个
```

Java 把 `ToolCallback[]` 原样展开成 varargs，于是每个 `ToolCallback` 被当成 POJO 反射，
报：

```
No @Tool annotated methods found in MethodToolCallback{toolDefinition=DefaultToolDefinition[name=readFile,...]}.
Did you mean to pass a ToolCallback or ToolCallbackProvider?
If so, you have to use .toolCallbacks() instead of .tool()
```

**证据表明这是漏改的笔误**：同一个项目里 `LoveApp.doChatWithTools()` 用的就是
`.toolCallbacks(allTools)`，写法是对的。

已在 2026-09-28 改成 `.toolCallbacks(availableTools)`，`No @Tool` 报错从 15+ 条降到 **0**，
`/ai/manus/chat` 随后实测能真实调用工具（见第 6 节）。

> 注意这个 bug **与用哪个模型无关** —— 只要模型发出工具调用就会炸。
> 也就是说用 DashScope 的 qwen-plus 也一样会踩到，只是之前没有 key 根本走不到这一步。

### 3.4 怎么切回 DashScope（拿到 key 之后，改 2 处）

1. **删掉** `application-local.yml` 里的 `spring.autoconfigure.exclude` 那一整段
2. 把 `spring.ai.dashscope.api-key` 换成你自己的：

```yaml
spring:
  ai:
    dashscope:
      api-key: sk-你的真实key        # ← 改这里
```

key 从阿里云百炼拿：<https://bailian.console.aliyun.com/> → API-KEY 管理 → 创建。
形如 `sk-xxxxxxxxxxxxxxxxxxxxxxxx`。**qwen-plus 有免费额度**，学习用够了。

> 别改 `application.yml` —— 那是仓库里的文件，改了会污染 `git status`。
> `application-local.yml` 是 `.gitignore` 第 2 行忽略掉的，改它不脏仓库。
>
> 注意：DashScope 和 Ollama 同时在容器里时**DashScope 会赢**（代码里的字段名就叫
> `dashscopeChatModel`，`@Resource` 按名匹配先命中它）。所以想让 Ollama 生效，
> 就必须把 DashScope 的自动配置整个排除；反过来想让 DashScope 生效，只要不排除它就行，
> 不用动 Ollama 的配置。

### 3.5 SearchAPI（可选）

只在「联网搜索」工具里用到：<https://www.searchapi.io/> → API Key。

注意措辞：**这个键本身必须存在，但值不需要有效**。
`ToolRegistration` 是 `@Configuration`，用 `@Value("${search-api.api-key}")` 做**字段注入** ——
键完全缺失会在启动时报 `Could not resolve placeholder 'search-api.api-key'`。
不过基础 `application.yml` 里已经给了占位值，所以实际上不会缺键。
填假值的后果只是：启动正常，调用联网搜索工具时才失败。

---

## 4. 本工作区已确认**不需要**的东西（都实测过，别白折腾）

这一节是为了防止照着网上教程去装一堆用不上的东西。

| 看起来需要 | 实际 | 依据 |
|---|---|---|
| **MySQL** | ❌ 不需要 | 启动日志 `datasource\|jdbc\|hikari` 零匹配，`DataSourceAutoConfiguration` 没介入 |
| **Redis** | ❌ 不需要 | pom 里 redis 零命中 |
| **PostgreSQL + pgvector** | ❌ 默认不需要 | `PgVectorVectorStoreConfig` 类上的 `@Configuration` **是注释掉的**；RAG 默认走 `LoveAppVectorStoreConfig` 的 `SimpleVectorStore`（纯内存） |
| **Ollama** | ✅ **当前必须** | 现在它就是 `ChatModel` / `EmbeddingModel` 的唯一来源。不起它，P1 启动会失败（连不上 11434）。启动方式见第 1 节 |
| **MCP server** | ⚠️ 可选 | `application.yml` 里的 `spring.ai.mcp.client` 段**整段被注释掉了**（原注释写着「临时注释掉，便于大家开发调试和部署」） |

> 工作区里确实建了 `yu_ai_agent` 这个 schema（两个 MySQL 实例都有），
> 那是**为「万一要启用 PgVector 路径」预留的**，目前是空的。

### 想启用 PgVector RAG 路径的话
要同时做三件事，缺一不可：
1. 装 PostgreSQL 并装上 `pgvector` 扩展
2. 取消 `PgVectorVectorStoreConfig` 类上 `@Configuration` 的注释
3. 取消 `application-local.yml` 底部那段 `datasource` + `vectorstore.pgvector` 的注释并填对连接

---

## 5. 目录结构 —— 这里有**三个**可运行物，不是一个

```
p1-yu-ai-agent/
├── src/                          ← ① 主应用（单模块，本手册的主角）
├── pom.xml, mvnw
├── yu-image-search-mcp-server/   ← ② 独立的 MCP server 项目（有自己的 pom + mvnw！）
│   ├── pom.xml, mvnw
│   └── src/main/resources/
│       ├── application.yml       ← profiles.active: sse, port 8127
│       ├── application-sse.yml
│       └── application-stdio.yml
└── yu-ai-agent-frontend/         ← ③ 独立的 Vue 前端项目（有自己的 package.json）
    ├── package.json, vite.config.js   ← dev server 端口 3000
    └── src/
```

### ② `yu-image-search-mcp-server` —— 独立的 MCP server
- **必须单独构建、单独运行**，它不在主 `pom.xml` 的 `<modules>` 里（`<module>` 数为 0）。
- 端口 **8127**，profile 默认 `sse`。
- 两种运行模式（由 profile 决定，不是由参数）：

| profile | 模式 | 说明 |
|---|---|---|
| `sse` | HTTP SSE | 起在 8127，主应用通过 `http://localhost:8127` 连它 |
| `stdio` | 标准输入输出 | `main.web-application-type: none`，不起 Web 容器，由父进程管道通信 |

```bash
cd /d/java-workspace/p1-yu-ai-agent/yu-image-search-mcp-server
source /d/java-workspace/use-jdk.sh 21
./mvnw -DskipTests -B package
java -jar target/yu-image-search-mcp-server-0.0.1-SNAPSHOT.jar     # 默认 sse，起在 8127
```

**当前状态：主应用的 MCP 客户端配置是注释掉的，所以这个 MCP server 不启动也不影响 P1 跑。**
等你要学 MCP 那一章时再开：取消 `application.yml` 里 `spring.ai.mcp.client` 段的注释。

### ③ `yu-ai-agent-frontend` —— Vue 3 + Vite 前端
```bash
cd /d/java-workspace/p1-yu-ai-agent/yu-ai-agent-frontend
npm install          # 本机 Node 22.22.2 ✅
npm run dev          # http://localhost:3000
```
端口 3000 在 `vite.config.js` 里写死。**前端不是必须的** ——
只调后端的话用 Swagger（`/api/doc.html`）就够了。

---

## 6. 验证清单

### 6.1 一键验证：`tools/p1-e2e-test.py`

**别手动 curl 一个个试。** 本工作区有现成的端到端脚本：

```bash
cd /d/java-workspace
C:/Users/Administrator/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe tools/p1-e2e-test.py
# 换日志路径：
#   ... tools/p1-e2e-test.py --log D:/java-workspace/logs/p1-final.log
```

它跑 **24 项断言**，覆盖 6 组：

| 组 | 断言数 | 查什么 |
|---|---|---|
| `[1]` Ollama 服务 | 4 | `/api/tags` 可达 + `qwen3:0.6b` / `gemma3:1b` / `nomic-embed-text` 三个模型都在 |
| `[2]` 应用基础 | 3 | `/api/health` == `ok`、knife4j UI、OpenAPI JSON |
| `[3]` 同步对话 | 1 | `/ai/love_app/chat/sync` 返回**真实模型文本**（不是错误串） |
| `[4]` 流式 SSE | 2 | `chat/sse`、`server_sent_event` 都真的在推 `data:` 分片 |
| `[5]` Agent 工具调用 | 2 | `/ai/manus/chat` **真的调用了** `writeFile` → `readFile` |
| `[6]` 日志体检 | 12 | 启动成功的 4 条必须出现 + provider 异常的 6 条必须不出现 + ERROR 计数 |

**为什么脚本还要查日志**：这个项目的「起不来」是**装配问题**，不是端口问题。
接口返回 200 也可能是**一段错误提示文本**（比如模型回一句"处理时遇到了错误"）。
所以脚本里内置了 `ERROR_SIGNS`（`处理时遇到了错误` / `InvalidApiKey` /
`does not support tools` / `No @Tool annotated` / `Connection refused` / `500` / `404`）
和 `looks_like_real_answer()`，**200 + 文本像人话**才算过。

> ⚠️ 脚本用 `http.client` 直连，**故意不走代理** —— 本机系统代理会劫持回环地址，
> 用 `requests` / `curl` 不绕过代理会直接超时（等价写法：`curl --noproxy '*'`）。

### 6.2 最近一次实测结果（2026-09-28，两次复跑均通过）

```
[1] Ollama 服务
  [PASS] Ollama /api/tags 可达  —— HTTP 200
  [PASS] gemma3:1b 已安装
  [PASS] qwen3:0.6b 已安装（Agent 需要 tools）
  [PASS] nomic-embed-text 已安装
[2] 应用基础
  [PASS] /api/health 返回 ok  —— HTTP 200 body='ok'
  [PASS] knife4j UI 可访问  —— HTTP 200 1892 字节
  [PASS] OpenAPI JSON 可访问  —— HTTP 200 2955 字节
[3] 对话接口 /ai/love_app/chat/sync
  [PASS] 同步对话返回真实模型输出  —— HTTP 200，41 字符，0.9s
         回复片段: "无论你此刻处于哪个状态，都是人生独特旅程的节点。…"
[4] 流式接口（SSE）
  [PASS] chat/sse 返回 SSE 分片  —— HTTP 200，61 个 data: 事件
  [PASS] server_sent_event 返回 SSE 分片  —— HTTP 200，94 个 data: 事件
[5] Agent 接口 /ai/manus/chat（工具调用）
  [PASS] Agent 真实调用了工具  —— HTTP 200，检测到 writeFile 结果
  [PASS] 工具返回内容可读  —— readFile -> "hello"
[6] 日志体检  D:\java-workspace\logs\p1-final.log
  [PASS] 日志文件存在  —— 1092142 字符
  [PASS] 应用已启动 / 端口正确 8123 / profile = local / 已走 Ollama
  [PASS] 无 DashScope 调用 / 无 InvalidApiKey / 无 'does not support tools'
  [PASS] 无 'No @Tool annotated' / 无 UnsatisfiedDependency / 无 APPLICATION FAILED TO START
  [PASS] 无真实 ERROR（已排除客户端断连噪声）
========================================================================
结果：24/24 PASS
========================================================================
```

> SSE 的 `data:` 分片数**每次都不一样**（模型逐 token 输出，分片边界不固定），
> 所以脚本只断言「有分片且能拼出完整回答」，不断言具体条数。
> 上面这次是 61 / 94，上一次是 60 / 23 —— **都算过**。

关键日志证据（`logs/p1-final.log`）：
- `Started YuAiAgentApplication in 20.134 seconds`
- `Tomcat started on port 8123 (http)`
- `The following 1 profile is active: "local"`
- `modelOptions=org.springframework.ai.ollama.api.OllamaOptions`
- `dashscope` 出现次数 = **0**

### 6.3 手动验证（不想跑脚本时）

```bash
# 编译（依赖已缓存，约 5 秒）
source /d/java-workspace/use-jdk.sh 21
./mvnw -DskipTests -B clean package
#    → BUILD SUCCESS
#    → target/yu-ai-agent-0.0.1-SNAPSHOT.jar  61 MB

# 确认 application-local.yml 真的进了 jar（第 7 节坑 3）
unzip -l target/yu-ai-agent-0.0.1-SNAPSHOT.jar | grep application-local
#    → BOOT-INF/classes/application-local.yml   ✅

# 起应用（Ollama 必须已在跑）
java -jar target/yu-ai-agent-0.0.1-SNAPSHOT.jar
#    → Started YuAiAgentApplication in ~20 seconds

# 冒烟
curl --noproxy '*' http://localhost:8123/api/health            # ok
curl --noproxy '*' -o /dev/null -w "%{http_code}\n" \
     http://localhost:8123/api/doc.html                        # 200
```

---

## 7. ⚠️ 踩过的坑

### 坑 1：`SERVER__PORT` 环境变量劫持 `server.port`

**和 P0 是同一个坑**（`docs/run-p0.md` 第 5 节有完整分析）。
WorkBuddy 客户端会往它启动的每个子进程注入 `SERVER__PORT=22407`，
Spring Boot 松散绑定把它当成 `server.port`，于是应用去抢宿主自己的端口：

```
Tomcat initialized with port 22407 (http)      ← 配置里明写 8123
APPLICATION FAILED TO START ... PortInUseException
```

**症状极具误导性**：配置文件写 8123、日志说 22407，而 `grep -rn 22407` 在整个仓库里搜不到。

**已做的防御**：`use-jdk.sh` / `use-jdk.cmd` 在切 JDK 时会 `unset SERVER__PORT SERVER__HOST`。
**只要启动前 `source use-jdk.sh 21`，这个坑就不会出现。**

> 这个坑已经在一个 Spring Boot 2.7 应用（eladmin）、一个 Spring Boot 3.4 应用（Nacos）
> 和一个 Spring Boot 3.4 应用（P1）上分别复现过 —— 它是**通用的**，
> 跟具体项目、具体 Spring Boot 版本都无关。

### 坑 2：`application-local.yml` 在原仓库里**根本不存在**

`.gitignore` 第 2 行就是 `application-local.yml`，而 `application.yml` 里写着
`spring.profiles.active: local` —— 也就是说**这个 profile 的配置文件得你自己建**，
官方仓库里没有模板、README 里也没给。

**所以「clone 下来跑不起来」不是你的问题，是仓库就没给。**
本工作区已经建好了 `src/main/resources/application-local.yml`，
里面写了完整说明和所有已知注意事项。

好处是：改它**不污染仓库**（git 看不见），`git status` 依然干净。

### 坑 3：改了源码里的配置，**要重新打包**才生效

配置在 `src/main/resources/` 下，会被打进 jar。改完直接跑旧 jar，改动完全不生效，
**而且没有任何提示**。（P0 也踩过同样的坑：改好的配置没进 jar，启动用的还是旧的错误配置。）

重建很快（依赖已缓存，约 5 秒）：
```bash
./mvnw -DskipTests -B package
```

想避免反复打包，可以外挂配置目录（优先级高于 jar 内）：
```bash
java -jar target/yu-ai-agent-0.0.1-SNAPSHOT.jar \
  --spring.config.additional-location=file:D:/java-workspace/p1-yu-ai-agent/src/main/resources/
```

### 坑 4：忘了 `/api` 前缀

`server.servlet.context-path: /api`。所以：
- Swagger 是 `http://localhost:8123/api/doc.html`（**不是** `8123/doc.html`）
- 接口是 `http://localhost:8123/api/ai/love_app/chat/sse`

### 坑 5 / 6 / 7：换模型 provider 时的三个坑

这三个坑是 2026-09-28 把 provider 从 DashScope 换成 Ollama 时踩出来的，
**完整分析在第 3.3 节**，这里只列症状方便检索：

| # | 症状 | 根因 | 一句话解法 |
|---|---|---|---|
| **坑 5** | 设了 `spring.ai.dashscope.chat.enabled: false`，**毫无效果、也不报警告**，照样 401 | 这是个**死属性** —— `DashScopeChatProperties` 里有 `enabled` 字段、元数据里也有，但 `DashScopeChatAutoConfiguration` 的类和 `@Bean` 方法上**都没有 `@ConditionalOnProperty`** | 别用它，改用 `spring.autoconfigure.exclude`。**属性存在 ≠ 属性生效** |
| **坑 6** | 只排了 Chat + Embedding 两个自动配置 → `UnsatisfiedDependencyException: 'dashscopeAgentApi' ... No qualifying bean of type 'DashScopeChatProperties' available` | DashScope 的自动配置之间有隐式 `@EnableConfigurationProperties` 串联，`DashScopeChatProperties` 是被 Chat 那个类注册的，排掉它属性类就没了 | **7 个必须一起排**（清单见 3.1） |
| **坑 7** | `/ai/manus/chat` 跑 20 步「思考完成 - 无需行动」，然后 `No @Tool annotated methods found in MethodToolCallback{...}` | `ToolCallAgent.java:72` 把 `ToolCallback[]` 传给了 `.tools(Object...)`，Java 把数组展开成 varargs，于是每个 `ToolCallback` 被当成 POJO 去反射扫 `@Tool` | 改成 `.toolCallbacks(availableTools)`。**同一项目里 `LoveApp.doChatWithTools()` 写的就是 `.toolCallbacks(allTools)`，这处是漏改的笔误** |

> 坑 7 是**项目自身的真 bug**，跟换不换 provider 无关 —— 走 DashScope 也一样会炸，
> 只是之前一直卡在 key 上、没跑到这一步而已。已经改掉并验证：
> `No @Tool annotated` 在日志里出现次数 **15+ → 0**。

---

## 8. 常见问题

### 8.1 当前路线（Ollama）

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动很慢（~20 s） | `qwen3:0.6b` 默认开 thinking，启动时要对 3 个文档分片各抽一次关键词 | 正常。只跑对话不用 Agent 的话换 `gemma3:1b`（5.6 s），见 3.1 |
| `Connection refused: localhost:11434` | Ollama 没起 | 先跑 `/d/java-workspace/run-ollama.cmd`（前台常驻，另开窗口） |
| `curl http://127.0.0.1:11434/api/version` 卡住不返回 | **系统代理劫持了回环地址** | 加 `--noproxy '*'`。Java 的 `RestClient` 不读系统代理，所以**应用本身不受影响** |
| `400 ... does not support tools` | 当前 chat 模型不支持工具调用 | 换成 `qwen3:0.6b`（用 `ollama show <model>` 看 capabilities 里有没有 `tools`） |
| `model 'xxx' not found` | 模型没拉下来 | `ollama pull xxx`。注意 `OLLAMA_MODELS` 必须钉死到 `.runtime\ollama\models`，否则会落进 `%USERPROFILE%\.ollama` |
| 模型/embedding 换不了、改了没反应 | 配置在 jar 里 | 重新 `./mvnw package`，见坑 3 |
| `No @Tool annotated methods found` | 坑 7，代码笔误 | 确认 `ToolCallAgent.java` 用的是 `.toolCallbacks(...)` 不是 `.tools(...)` |
| `NoUniqueBeanDefinitionException: ChatModel` | 容器里出现了**两个**同类型 bean（比如 DashScope 没排干净） | 检查 `spring.autoconfigure.exclude` 那 7 行是否齐全（坑 6） |

### 8.2 通用 / DashScope 路线

| 现象 | 原因 | 处理 |
|---|---|---|
| `HTTP 401 InvalidApiKey` → 起不来 | DashScope key 是占位值（**当前路线已不受影响**） | 要么填真 key，要么走 Ollama 路线；见第 3 节 |
| `Could not resolve placeholder 'search-api.api-key'` | 键完全缺失 | 正常情况下不会（`application.yml` 有占位值）；检查是否误删了 `search-api:` 段 |
| 端口是 22407 | `SERVER__PORT` 注入 | 启动前 `source use-jdk.sh 21`（已自动清） |
| `Port 8123 already in use` | 上次的进程没退 | `netstat -ano \| grep ":8123 "` → `taskkill //F //PID <pid>` |
| 404 | 忘了 `/api` 前缀 | 见坑 4 |
| `Unsupported class file major version` | 用了 JDK 17 或 8 | `source use-jdk.sh 21` |
| 日志中文乱码 | JDK 21 默认就是 UTF-8，**正常不会出现** | 若出现，检查是不是误用了 JDK 8/17 |
| 改动配置后无效果 | 配置在 jar 里 | 重新 `./mvnw package`，或用 `--spring.config.additional-location` |
| 前端 `npm install` 慢 | 默认走 npm 官方源 | 可换国内镜像，但**别把镜像写进项目文件** |

---

## 9. 相关文档

| 文档 | 内容 |
|---|---|
| **`tools/p1-e2e-test.py`** | **本项目的 24 项端到端验证脚本（第 6 节）** |
| `docs/port-map.md` | 全工作区端口分配（P1 占 8123 / 8127 / 3000，Ollama 占 11434） |
| `docs/jdk-matrix.md` | 四个项目各用哪个 JDK、编码问题怎么修 |
| `docs/runtime.md` | 便携版中间件 + **Ollama 的安装/启动/两个必须钉死的环境变量** |
| `docs/run-p0.md` | P0 eladmin-mp 启动手册（`SERVER__PORT` 坑的完整分析在这） |
| `docs/run-p2.md` | P2 mall-swarm 启动手册（`tools/p2-e2e-test.py` 在那边） |
| `p1-yu-ai-agent/src/main/resources/application-local.yml` | 配置本体，注释里写了 3.1 / 3.2 / 3.3 的全部细节 |

### 工作区启动器一览（都在 `D:\java-workspace\` 根目录）

| 脚本 | 起什么 |
|---|---|
| `run-ollama.cmd` | **Ollama（P1 当前唯一必需的外部前提）** |
| `run-minio.cmd` / `run-nacos.cmd` / `run-rabbitmq.cmd` | 便携版中间件（P1 **不需要**） |
| `svc.sh` / `svc.cmd` | 全量中间件启停（P1 **不需要**） |
| `use-jdk.sh` / `use-jdk.cmd` | 切 JDK 8 / 17 / 21，**并清掉 `SERVER__PORT`** |

> ⚠️ `svc.sh` **不能**带 `MSYS_NO_PATHCONV=1` 运行 —— 它第 52 行的 `cmd //c`
> 依赖 Git Bash 把 `//c` 改写成 `/c`，屏蔽路径转换会让它打印一段 MSYS 横幅就退出。
