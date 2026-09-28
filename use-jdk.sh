#!/usr/bin/env bash
# =============================================================================
#  use-jdk.sh —— 切换当前 shell 的 JDK
#  -----------------------------------------------------------------------------
#  ⚠️ 必须 source（或 `.`）来用，不能直接执行：
#       source /d/java-workspace/use-jdk.sh 8
#     直接执行的话，脚本跑在子进程里，改完的环境变量随子进程一起消失，
#     父进程（你的终端）看不到任何变化 —— 表现就是「执行了但没生效」。
#
#  用法：
#     source use-jdk.sh 8       # JDK 8  → P0 eladmin-mp
#     source use-jdk.sh 17      # JDK 17 → P2 mall-swarm（用系统已装的那个）
#     source use-jdk.sh 21      # JDK 21 → P1 yu-ai-agent
#     source use-jdk.sh list    # 列出所有可用 JDK 及是否就绪
#     source use-jdk.sh status  # 看当前生效的是哪个
#     source use-jdk.sh --help
#
#  设计要点：
#    · JAVA_HOME 用 **Windows 风格路径**（D:\...）—— Maven / Gradle / IDEA 这些
#      Java 系工具都是原生 Windows 程序，喂 Unix 路径（/d/...）给它们容易出岔子。
#    · PATH 里塞的是 **Unix 风格路径**（/d/...）—— Git Bash 的 `which java`
#      和命令查找认的是 Unix 路径。
#      两者分开设置，各取所需。Git Bash 能正确处理 D:\.../bin/java 这种混合写法。
#    · 只影响当前 shell，系统环境变量一个字节都不动。
# =============================================================================

# ---- 检测是否被 source（而不是被直接执行）----------------------------------
if [ -n "${BASH_SOURCE[0]}" ] && [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  printf '\033[33m[警告]\033[0m 这个脚本需要 source 才能生效：\n'
  printf '        source %s <8|17|21|list|status>\n\n' "${BASH_SOURCE[0]}"
  printf '    直接执行只会改子进程的环境变量，你的终端看不到变化。\n'
  exit 1
fi

# ---- JDK 注册表 ------------------------------------------------------------
# 格式： 版本号|显示名|Windows 路径|Unix 路径
_JDK_ENTRIES=(
  '8|Amazon Corretto 8|D:\java-workspace\.jdks\corretto-8|/d/java-workspace/.jdks/corretto-8'
  '17|Amazon Corretto 17 (系统已装)|C:\Program Files\Amazon Corretto\jdk17.0.20_10|/c/Program Files/Amazon Corretto/jdk17.0.20_10'
  '21|Amazon Corretto 21|D:\java-workspace\.jdks\corretto-21|/d/java-workspace/.jdks/corretto-21'
)

# 把 Windows 路径转成 Unix 路径（用于 PATH 与存在性检查）
_win2unix() {
  local p="$1"
  p="${p//\\//}"                 # 反斜杠 → 正斜杠
  p="${p/#C:/\/c}"               # C: → /c
  p="${p/#D:/\/d}"               # D: → /d
  p="${p/#E:/\/e}"
  printf '%s' "$p"
}

_jdk_lookup() {
  local want="$1" e
  for e in "${_JDK_ENTRIES[@]}"; do
    if [ "${e%%|*}" = "$want" ]; then
      printf '%s' "$e"
      return 0
    fi
  done
  return 1
}

_jdk_ok() {
  local entry="$1"
  local unix_path="${entry##*|}"
  [ -x "$unix_path/bin/java" ] || [ -x "$unix_path/bin/java.exe" ]
}

# ---- list ------------------------------------------------------------------
_jdk_list() {
  printf '\n可用 JDK：\n'
  printf '  %-4s %-32s %-10s %s\n' '版本' '名称' '状态' '路径'
  printf '  %s\n' '----------------------------------------------------------------------------------------------------'
  local e ver name win unix status mark
  for e in "${_JDK_ENTRIES[@]}"; do
    IFS='|' read -r ver name win unix <<< "$e"
    if _jdk_ok "$e"; then status='就绪'; mark=''
    else status='缺失'; mark='  ← 需要安装'; fi
    printf '  %-4s %-32s %-10s %s%s\n' "$ver" "$name" "$status" "$win" "$mark"
  done
  printf '\n  当前生效：'
  _jdk_status
  printf '\n'
}

# ---- status ----------------------------------------------------------------
_jdk_status() {
  if [ -z "$JAVA_HOME" ]; then
    printf '\033[33mJAVA_HOME 未设置\033[0m\n'
    return
  fi
  local e ver name win unix
  for e in "${_JDK_ENTRIES[@]}"; do
    IFS='|' read -r ver name win unix <<< "$e"
    if [ "$win" = "$JAVA_HOME" ]; then
      printf 'JDK %s（%s）\n' "$ver" "$name"
      return
    fi
  done
  printf '\033[33m%s（不在注册表里）\033[0m\n' "$JAVA_HOME"
}

# ---- switch ----------------------------------------------------------------
_jdk_switch() {
  local want="$1" entry
  if ! entry="$(_jdk_lookup "$want")"; then
    printf '\033[31m[错误]\033[0m 不认识的版本 "%s"。可选：8 / 17 / 21\n' "$want" >&2
    _jdk_list >&2
    return 1
  fi

  local ver name win unix
  IFS='|' read -r ver name win unix <<< "$entry"

  if ! _jdk_ok "$entry"; then
    printf '\033[31m[错误]\033[0m JDK %s 还没装好，找不到 %s/bin/java\n' "$ver" "$win" >&2
    return 1
  fi

  # 从 PATH 里剔除旧的 JDK bin，避免切来切去堆一长串
  local cleaned='' seg
  local IFS_BAK="$IFS"; IFS=':'
  for seg in $PATH; do
    case "$seg" in
      */Amazon\ Corretto/*/bin) continue ;;
      /d/java-workspace/.jdks/*/bin) continue ;;
    esac
    if [ -z "$cleaned" ]; then cleaned="$seg"; else cleaned="$cleaned:$seg"; fi
  done
  IFS="$IFS_BAK"

  export JAVA_HOME="$win"
  export PATH="$unix/bin:$cleaned"

  # ---- 编码修正（只对 8 / 17 做，21 不需要）--------------------------------
  # 实测：JDK 8 和 17 在中文 Windows 上 `platform encoding` 是 **GBK**，
  #       而 JDK 21 是 UTF-8。原因是 JEP 400（Java 18 起）把 file.encoding
  #       的默认值统一成了 UTF-8，18 之前跟随系统区域设置，中文系统就是 GBK。
  #
  # 后果：eladmin / mall 这些项目的日志、异常堆栈、控制台输出全是中文，
  #       在 GBK 下会变成乱码 —— 而且**不报错**，只是你看到的东西是坏的。
  #       这种「看起来能跑但内容是错的」比直接报错更难发现。
  #
  # 顺带一个坑：Maven 会用 file.encoding 去读源码，
  #       项目 pom 里写了 <sourceEncoding>UTF-8</sourceEncoding> 还好，
  #       没写的项目会按 GBK 读 UTF-8 源文件，中文注释直接解析成乱码字符串。
  #
  # JAVA_TOOL_OPTIONS 的作用域仅限当前 shell（因为是 export 的），
  # 代价是每次启动 JVM 会往 stderr 打一行 "Picked up JAVA_TOOL_OPTIONS: ..."，
  # 无害，看着烦的话用 MAVEN_OPTS 那套，但那样就盖不到 `java -jar` 了。
  if [ "$ver" = "8" ]; then
    # JDK 8 还要单独管 sun.jnu.encoding —— 它决定文件名怎么解码，
    # 不设的话中文路径的文件操作会出问题。
    export JAVA_TOOL_OPTIONS="-Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8"
  elif [ "$ver" = "17" ]; then
    export JAVA_TOOL_OPTIONS="-Dfile.encoding=UTF-8"
  else
    unset JAVA_TOOL_OPTIONS
  fi

  # ---- 清掉宿主注入的环境变量（会劫持 server.port）-------------------------
  # WorkBuddy 客户端会往它启动的**每一个**子进程里塞 SERVER__HOST / SERVER__PORT，
  # 值是它自己后端服务的地址（实测 22407）。
  #
  # Spring Boot 的松散绑定会把 SERVER__PORT 当成 server.port 读走，
  # 于是任何从这里启动的 Spring 应用都会去抢 22407 —— 也就是 WorkBuddy 自己的端口：
  #
  #     Tomcat initialized with port 22407 (http)
  #     APPLICATION FAILED TO START ... PortInUseException
  #
  # 已经实测撞了两次：eladmin（P0）和 Nacos 本身（Nacos 3.x 就是个 Spring Boot 3.4 应用，
  # 一样躲不过）。症状特别误导人 —— 配置文件里明明写着 server.port: 8000，
  # 日志里却是 22407，很容易怀疑错方向。
  #
  # 在你的普通终端里跑不会有这两个变量（是宿主注入的），但在这里跑必然有。
  # 统一在这里清掉，让所有 Spring 应用回到配置文件里写的端口。
  unset SERVER__PORT SERVER__HOST

  printf '\033[32m✔\033[0m 已切到 JDK %s —— %s\n' "$ver" "$name"
  printf '   JAVA_HOME = %s\n' "$JAVA_HOME"
  if [ -n "$JAVA_TOOL_OPTIONS" ]; then
    printf '   编码修正  = %s\n' "$JAVA_TOOL_OPTIONS"
  fi
  printf '   %s\n' "$("$unix/bin/java" -version 2>&1 | grep -i 'version' | head -1)"
}

# ---- 入口 ------------------------------------------------------------------
case "${1:-}" in
  ''|-h|--help|help)
    sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    ;;
  list|ls)
    _jdk_list
    ;;
  status|st|cur)
    _jdk_status
    ;;
  8|1.8|java8)
    _jdk_switch 8
    ;;
  17|java17)
    _jdk_switch 17
    ;;
  21|java21)
    _jdk_switch 21
    ;;
  *)
    printf '\033[31m[错误]\033[0m 不认识的参数 "%s"。\n' "$1" >&2
    printf '用法：source %s <8|17|21|list|status>\n' "${BASH_SOURCE[0]}" >&2
    return 1
    ;;
esac

# 清掉内部函数，别污染你的 shell 命名空间（只留 JAVA_HOME / PATH 的改动）
unset -f _win2unix _jdk_lookup _jdk_ok _jdk_list _jdk_status _jdk_switch 2>/dev/null
unset _JDK_ENTRIES 2>/dev/null
