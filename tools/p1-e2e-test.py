#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
p1-e2e-test.py —— P1 (yu-ai-agent) 端到端验证

跑之前必须满足：
  1) Ollama 在跑      D:\\java-workspace\\run-ollama.cmd
  2) P1 应用在跑      java -jar target/yu-ai-agent-0.0.1-SNAPSHOT.jar --spring.profiles.active=local

用法：
  python tools/p1-e2e-test.py
  python tools/p1-e2e-test.py --log D:/java-workspace/logs/p1-final.log

为什么要有这个脚本：
  这个项目的「起不来」不是端口/数据库问题，而是模型 provider 的装配问题
  （详见 docs/run-p1.md 第 3 节）。所以验证必须**同时**看两件事：
    · 接口能不能返回真实模型输出
    · 日志里有没有 provider 相关的异常
  只看接口 200 是不够的 —— 200 也可能是一段错误提示文本。

⚠️ 本机访问回环地址必须绕过系统代理，否则 curl / requests 会超时。
   本脚本用 http.client 直连（不走代理），等价于 curl --noproxy '*'。
"""

import argparse
import json
import re
import sys
import time
import http.client
from pathlib import Path

BASE_HOST = "127.0.0.1"
BASE_PORT = 8123
CTX = "/api"
OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434

DEFAULT_LOG = Path("D:/java-workspace/logs/p1-final.log")

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"  —— {detail}" if detail else ""))


def http_get(host, port, path, timeout=300):
    """直连，不经过任何代理。返回 (status, body_text)。"""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", errors="replace")
    finally:
        conn.close()


def http_post_json(host, port, path, payload, timeout=300):
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        body = json.dumps(payload).encode("utf-8")
        conn.request("POST", path, body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", errors="replace")
    finally:
        conn.close()


def q(s):
    """极简 URL 编码（够用，避免引入依赖）。"""
    from urllib.parse import quote
    return quote(s, safe="")


# ---------------------------------------------------------------------------
# 1. 前置：Ollama 必须在跑
# ---------------------------------------------------------------------------
def check_ollama():
    print("\n[1] Ollama 服务")
    try:
        st, body = http_get(OLLAMA_HOST, OLLAMA_PORT, "/api/tags", timeout=10)
        record("Ollama /api/tags 可达", st == 200, f"HTTP {st}")
        if st == 200:
            models = [m["name"] for m in json.loads(body).get("models", [])]
            record("gemma3:1b 已安装", any("gemma3:1b" in m for m in models))
            record("qwen3:0.6b 已安装（Agent 需要 tools）",
                   any("qwen3:0.6b" in m for m in models),
                   "，".join(models) or "无模型")
            record("nomic-embed-text 已安装",
                   any("nomic-embed-text" in m for m in models))
    except Exception as e:
        record("Ollama /api/tags 可达", False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 2. 应用基础可用性
# ---------------------------------------------------------------------------
def check_basic():
    print("\n[2] 应用基础")
    try:
        st, body = http_get(BASE_HOST, BASE_PORT, f"{CTX}/health", timeout=15)
        record("/api/health 返回 ok", st == 200 and body.strip() == "ok",
               f"HTTP {st} body={body.strip()[:40]!r}")
    except Exception as e:
        record("/api/health 返回 ok", False, f"{type(e).__name__}: {e}")

    for path, label in [(f"{CTX}/doc.html", "knife4j UI"),
                        (f"{CTX}/v3/api-docs", "OpenAPI JSON")]:
        try:
            st, body = http_get(BASE_HOST, BASE_PORT, path, timeout=20)
            record(f"{label} 可访问", st == 200 and len(body) > 100,
                   f"HTTP {st} {len(body)} 字节")
        except Exception as e:
            record(f"{label} 可访问", False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 3. 对话接口 —— 必须返回**真实模型输出**，不是错误文本
# ---------------------------------------------------------------------------
ERROR_SIGNS = ("处理时遇到了错误", "InvalidApiKey", "does not support tools",
               "No @Tool annotated", "Connection refused", "500", "404")


def looks_like_real_answer(text):
    if not text or len(text.strip()) < 8:
        return False, "回复过短"
    for sign in ERROR_SIGNS:
        if sign in text:
            return False, f"回复里含错误标志 {sign!r}"
    return True, f"{len(text)} 字符"


def check_chat_sync():
    print("\n[3] 对话接口 /ai/love_app/chat/sync")
    t0 = time.time()
    try:
        st, body = http_get(
            BASE_HOST, BASE_PORT,
            f"{CTX}/ai/love_app/chat/sync?message={q('用一句话安慰我')}&chatId=e2e-sync",
            timeout=300)
        ok, why = looks_like_real_answer(body)
        record("同步对话返回真实模型输出", st == 200 and ok,
               f"HTTP {st}，{why}，{time.time()-t0:.1f}s")
        print(f"         回复片段: {body.strip()[:80]!r}")
    except Exception as e:
        record("同步对话返回真实模型输出", False, f"{type(e).__name__}: {e}")


def check_chat_stream():
    print("\n[4] 流式接口（SSE）")
    for path, label in [
        (f"{CTX}/ai/love_app/chat/sse", "chat/sse"),
        (f"{CTX}/ai/love_app/chat/server_sent_event", "server_sent_event"),
    ]:
        try:
            st, body = http_get(
                BASE_HOST, BASE_PORT,
                f"{path}?message={q('说两个字')}&chatId=e2e-{label}",
                timeout=300)
            chunks = re.findall(r"^data:(.*)$", body, re.M)
            record(f"{label} 返回 SSE 分片", st == 200 and len(chunks) >= 2,
                   f"HTTP {st}，{len(chunks)} 个 data: 事件")
        except Exception as e:
            record(f"{label} 返回 SSE 分片", False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 5. Agent 接口 —— 必须真实调用工具
# ---------------------------------------------------------------------------
def check_manus():
    print("\n[5] Agent 接口 /ai/manus/chat（工具调用）")
    try:
        st, body = http_get(
            BASE_HOST, BASE_PORT,
            f"{CTX}/ai/manus/chat?message={q('把 hello 写进文件 e2e-check.txt，然后读出来告诉我')}",
            timeout=300)
        called = "工具 writeFile 返回的结果" in body
        record("Agent 真实调用了工具", st == 200 and called,
               f"HTTP {st}，{'检测到 writeFile 结果' if called else '未检测到工具调用'}")
        if called:
            m = re.search(r'工具 readFile 返回的结果：(.{0,60})', body, re.S)
            if m:
                record("工具返回内容可读", "hello" in m.group(1),
                       f"readFile -> {m.group(1).strip()[:40]!r}")
    except Exception as e:
        record("Agent 真实调用了工具", False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 6. 日志体检 —— 只看接口 200 是不够的
# ---------------------------------------------------------------------------
LOG_CHECKS = [
    ("应用已启动", r"Started YuAiAgentApplication", True),
    ("端口正确 8123", r"Tomcat started on port 8123", True),
    ("profile = local", r'profile is active: "local"', True),
    ("已走 Ollama（不是 DashScope）", r"org\.springframework\.ai\.ollama", True),
    ("无 DashScope 调用", r"dashscope", False),
    ("无 InvalidApiKey", r"InvalidApiKey", False),
    ("无 'does not support tools'", r"does not support tools", False),
    ("无 'No @Tool annotated'", r"No @Tool annotated", False),
    ("无 UnsatisfiedDependency", r"UnsatisfiedDependencyException", False),
    ("无 APPLICATION FAILED TO START", r"APPLICATION FAILED TO START", False),
]


def check_log(log_path):
    print(f"\n[6] 日志体检  {log_path}")
    if not log_path.exists():
        record("日志文件存在", False, str(log_path))
        return
    text = log_path.read_text(encoding="utf-8", errors="replace")
    record("日志文件存在", True, f"{len(text)} 字符")
    for label, pattern, should_match in LOG_CHECKS:
        hit = re.search(pattern, text) is not None
        ok = hit == should_match
        record(label, ok, "" if ok else ("意外命中" if hit else "缺失"))
    # 被客户端打断连接不算真错误
    real_err = re.findall(
        r"ERROR.*?(?:\n(?!\d{4}-).*)*", text)
    noise = [e for e in real_err
             if "ClientAbortException" not in e and "中止了一个已建立的连接" not in e
             and "AsyncRequestNotUsableException" not in e]
    record("无真实 ERROR（已排除客户端断连噪声）", len(noise) == 0,
           f"{len(noise)} 条" if noise else "")
    for e in noise[:3]:
        print(f"         {e.splitlines()[0][:130]}")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(DEFAULT_LOG),
                    help="P1 启动日志路径")
    args = ap.parse_args()

    print("=" * 72)
    print("P1 (yu-ai-agent) 端到端验证")
    print("=" * 72)

    check_ollama()
    check_basic()
    check_chat_sync()
    check_chat_stream()
    check_manus()
    check_log(Path(args.log))

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 72)
    print(f"结果：{passed}/{total} PASS")
    if passed != total:
        print("\n失败项：")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}  {detail}")
    print("=" * 72)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
