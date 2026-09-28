#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P0 (eladmin) 端到端冒烟测试 —— 真实走完「取验证码 -> 解密答案 -> RSA 加密密码 -> 登录 -> 取用户信息」。

为什么需要脚本而不是 curl：
  eladmin 的登录密码用 RSA 公钥加密传输（后端 RsaUtils.decryptByPrivateKey 解密），
  手写 curl 没法生成密文。这里用配置里的私钥反推出公钥，复现前端的加密。

用法：
  python p0-login-test.py                       # 默认 admin/123456
  python p0-login-test.py admin 123456
"""

import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_der_private_key

BASE = "http://localhost:8000"
REDIS_CLI = r"D:\java-workspace\.runtime\redis\redis-cli.exe"
REDIS_PORT = "6380"
REDIS_DB = "1"
APP_YML = Path(r"D:\java-workspace\p0-eladmin-mp\eladmin\eladmin-system\src\main\resources\config\application.yml")

OK = "  [OK]  "
NG = "  [NG]  "


def http(path, method="GET", body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def redis_get(key):
    """直接用 redis-cli 读，避免额外依赖。"""
    out = subprocess.run(
        [REDIS_CLI, "-h", "127.0.0.1", "-p", REDIS_PORT, "-n", REDIS_DB, "GET", key],
        capture_output=True, text=True, timeout=10,
    )
    return out.stdout.strip().strip('"')


def load_rsa_private_key():
    """从 eladmin 的 application.yml 里抠出 rsa.private_key。"""
    text = APP_YML.read_text(encoding="utf-8")
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("private_key:"):
            return s.split(":", 1)[1].strip()
    raise RuntimeError("application.yml 里没找到 rsa.private_key")


def encrypt_password(plain, priv_b64):
    """复现前端的 RSA/ECB/PKCS1Padding + Base64。"""
    key = load_der_private_key(base64.b64decode(priv_b64), password=None)
    ct = key.public_key().encrypt(plain.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(ct).decode()


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    password = sys.argv[2] if len(sys.argv) > 2 else "123456"
    failures = []

    # --- 1) 取验证码 ---
    status, resp = http("/auth/code")
    if status == 200 and resp.get("uuid"):
        uuid = resp["uuid"]
        print(f"{OK} 1) GET /auth/code            -> 200, uuid={uuid}")
    else:
        print(f"{NG} 1) GET /auth/code            -> {status} {resp}")
        return 1

    # --- 2) 从 Redis 还原验证码答案（证明 Redis 6380 / DB1 通） ---
    code = redis_get(uuid)
    if code:
        print(f"{OK} 2) Redis DB{REDIS_DB} 取验证码答案     -> {code!r}")
    else:
        print(f"{NG} 2) Redis DB{REDIS_DB} 里没有 key {uuid}")
        failures.append("redis")

    # --- 3) RSA 加密密码 ---
    try:
        enc = encrypt_password(password, load_rsa_private_key())
        print(f"{OK} 3) RSA 加密密码             -> {enc[:40]}...（{len(enc)} 字符）")
    except Exception as e:
        print(f"{NG} 3) RSA 加密失败             -> {e}")
        return 1

    # --- 4) 登录 ---
    status, resp = http("/auth/login", "POST", {"username": username, "password": enc, "code": code, "uuid": uuid})
    if status == 200 and resp.get("token"):
        token = resp["token"]
        print(f"{OK} 4) POST /auth/login          -> 200, 拿到 JWT（{len(token)} 字符）")
    else:
        print(f"{NG} 4) POST /auth/login          -> {status} {resp}")
        return 1

    # --- 5) 带 token 取用户信息（证明 JWT 鉴权 + 数据库读通） ---
    status, resp = http("/auth/info", token=token)
    if status == 200 and resp.get("user"):
        u = resp["user"]
        print(f"{OK} 5) GET /auth/info            -> 200, 用户={u.get('username')}, 角色={[r.get('name') for r in (u.get('roles') or [])]}")
    else:
        print(f"{NG} 5) GET /auth/info            -> {status} {resp}")
        failures.append("info")

    # --- 6) 菜单接口（证明业务表查询正常） ---
    status, resp = http("/api/menus/build", token=token)
    if status == 200:
        n = len(resp) if isinstance(resp, list) else "-"
        print(f"{OK} 6) GET /api/menus/build      -> 200, 顶级菜单 {n} 个")
    else:
        print(f"{NG} 6) GET /api/menus/build      -> {status} {str(resp)[:120]}")

    print()
    if failures:
        print(f"结果：有 {len(failures)} 项异常 -> {failures}")
        return 1
    print("结果：全部通过 —— P0 端到端可用（Web / MySQL 3307 / Redis 6380-DB1 / JWT 全通）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
