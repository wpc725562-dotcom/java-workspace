# JDK 矩阵 —— 哪个项目用哪个 JDK

> 2026-09-28 实测。本机系统里**只有 JDK 17**，其余走 `D:\java-workspace\.jdks\` 下的便携版。

---

## 1. 总表

| 阶段 | 项目 | 需要 Java | Spring Boot | 命名空间 | JDK 从哪来 |
|---|---|---|---|---|---|
| P0 | eladmin-mp | **1.8** | 2.7.18 | `javax.*` | `.jdks\corretto-8`（便携版） |
| P1 | yu-ai-agent | **21** | 3.4.4 | `jakarta.*` | `.jdks\corretto-21`（便携版） |
| P2 | mall-swarm | **17** | 3.5.14 | `jakarta.*` | 系统 `C:\Program Files\Amazon Corretto\jdk17.0.20_10` |
| P3 | seckill | 待定 | 待定 | 待定 | 待克隆后核对 |

**关键点：P2 不用装任何东西** —— 系统现成的 JDK 17 正好对上。
所以只需要补 **JDK 8** 和 **JDK 21** 两个便携版。

---

## 2. 为什么必须是三个不同的 JDK

不是「随便一个能跑就行」，而是这三个项目的**源码写法本身**就锁死了版本：

### P0 eladmin-mp 要 Java 8
- 用 `javax.servlet.*` / `javax.persistence.*`。这套命名空间在 **Spring Boot 3 / Java 17+ 里被整体移除**，
  换成了 `jakarta.*`。
- Spring Boot 2.7.18 官方支持范围是 Java 8–19，**不保证**在 21 上正常工作
  （2.7.x 对 21 的字节码和 ASM 版本支持不完整，编译期就可能报 `Unsupported class file major version`）。
- 所以老老实实给 8。

### P1 yu-ai-agent 要 Java 21
- Spring Boot 3.4.x 的**最低要求就是 Java 17**，而项目声明了 21。
- 它大量用**虚拟线程（Virtual Threads，Java 21 正式转正）** 和 **Record Pattern**。
  用 17 编译会直接报语法错误。

### P2 mall-swarm 要 Java 17
- Spring Boot 3.5.x 基线是 17，项目也声明 17。
- **系统里已有的 Corretto 17.0.20.10 正好够用**，无需额外安装。

### 三个版本为什么不能统一
`javax` → `jakarta` 是**硬墙**：这两套包名在同一个 JVM 里**无法共存**，
不是「配置一下就行」，而是要把成千上万个 `import` 改掉。
改完之后它就不再是原来那个开源项目了 —— 拿它当学习样本、面试时讲，
都会失去「我看过真实的 xxx 项目」这个价值。

所以**正确做法是三个 JDK 并存，各自编译各自的项目**，而不是硬凑一个版本。

---

## 3. 便携版 JDK 的安装位置

```
D:\java-workspace\.jdks\
├── corretto-8\     ← Amazon Corretto 8.504.01.1  (Windows x64, 约 101 MB 压缩包)
│   └── bin\java.exe, bin\javac.exe, ...
└── corretto-21\    ← Amazon Corretto 21.0.12.12.1 (Windows x64, 约 193 MB 压缩包)
    └── bin\java.exe, bin\javac.exe, ...
```

来源：`https://corretto.aws/downloads/latest/amazon-corretto-{8,21}-x64-windows-jdk.zip`
（Amazon 官方免费发行版，OpenJDK 的合规构建，无许可问题，可商用）

**为什么用 Corretto 而不是 Oracle JDK**：
- Oracle JDK 有商用许可限制，Corretto 是 GPLv2+CE，随便用。
- Corretto 8 / 17 / 21 都有，且 8 会**持续打安全补丁**（很多发行版早就不维护 8 了）。
- 系统里已经装的就是 Corretto 17，保持同一家，行为一致。

**为什么用 zip 便携版而不是安装包（.msi）**：
- `.msi` 安装包会往注册表写东西、抢改系统 `JAVA_HOME` 和 `PATH`，
  三个版本互相覆盖，卸载还经常清不干净。
- zip 版解压即用，**系统环境变量一个字节都不动**。删目录 = 完全卸载。

---

## 4. 怎么切换

### Git Bash（本项目的主要 shell）

```bash
source /d/java-workspace/use-jdk.sh 8      # 切到 JDK 8
source /d/java-workspace/use-jdk.sh 21     # 切到 JDK 21
source /d/java-workspace/use-jdk.sh 17     # 切到系统 JDK 17
source /d/java-workspace/use-jdk.sh list   # 看有哪些可用
java -version                              # 验证
```

必须 `source`（或 `. `）而不是直接执行 —— 直接执行的话脚本在子进程里改环境变量，
父进程看不到，等于没切。

### Windows cmd

```bat
D:\java-workspace\use-jdk.cmd 8
```

`use-jdk.cmd` 用的是 `endlocal & set ...` 这个惯用法：
`set` 作用在**调用方的环境**上，所以切完当前窗口就生效。

### IDEA / VS Code

不要依赖脚本。直接在 IDE 里配：

- **IntelliJ IDEA**：`File → Project Structure → SDK` 加三个 JDK，
  然后在每个项目的 `Project SDK` 里选对应的；Maven 的 `Runner → JRE` 也要一起选，
  否则会出现「编译用 8、跑测试用 17」这种诡异问题。
- **VS Code**：在 workspace 的 `.vscode/settings.json` 里写
  `"java.configuration.runtimes"`，按项目路径区分。

---

## 5. 验证清单

装完跑这三条，全绿才算好：

```bash
# ① 便携版 JDK 8
/d/java-workspace/.jdks/corretto-8/bin/java.exe -version
# 期望：openjdk version "1.8.0_504"

# ② 便携版 JDK 21
/d/java-workspace/.jdks/corretto-21/bin/java.exe -version
# 期望：openjdk version "21.0.12"

# ③ 系统 JDK 17 没被动过
"C:/Program Files/Amazon Corretto/jdk17.0.20_10/bin/java.exe" -version
# 期望：openjdk version "17.0.20"
```

再加一条**回归检查**，确认系统环境变量确实没被改：

```bash
echo "JAVA_HOME=$JAVA_HOME"
which java
```

如果 `JAVA_HOME` 还指向 `C:\Program Files\Amazon Corretto\jdk17.0.20_10`，说明便携版策略成功。

---

## 6. 常见问题

**Q: 编译时报 `Unsupported class file major version 65`？**
A: 用错 JDK 了。65 = Java 21，61 = Java 17，52 = Java 8。
说明你在拿低版本 JDK 编高版本项目。`source use-jdk.sh` 切一下。

**Q: `mvnw` 用的是哪个 JDK？**
A: Maven Wrapper 用 `JAVA_HOME`。所以切完 JDK 再跑 `./mvnw` 就对了。
想确认的话跑 `./mvnw -version`，输出里会写 `Java version: x.x.x`。

**Q: 能不能把三个 JDK 都塞进系统 PATH，靠顺序选？**
A: 不行。`java` 只会找到第一个匹配的，而且不同项目来回切会很痛苦。
便携版 + 脚本是明确的做法。

**Q: `.jdks` 会不会被提交进 git？**
A: 不会，`.gitignore` 里已经排除了。
