#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把 p2-mall-swarm/config/ 下的 dev 配置发布到本地 Nacos 配置中心。

为什么必须做这一步：
  mall-swarm 每个模块的 application-dev.yml 里都有
      spring.config.import:
        - nacos:mall-admin-dev.yaml?refreshEnabled=true
  没有 optional: 前缀。配置在 Nacos 里找不到 -> 模块直接启动失败
  （ConfigDataResourceNotFoundException）。仓库里的 config/ 目录就是给导入用的，
  但官方没提供自动导入脚本，只能手动在控制台一条条粘，或者跑这个。

用法：
  python p2-publish-nacos-configs.py
  python p2-publish-nacos-configs.py --check      # 只读回校验，不发布
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8848"
NACOS_USER = "nacos"
NACOS_PASS = "Workspace#2026"
GROUP = "DEFAULT_GROUP"

ROOT = Path(r"D:\java-workspace\p2-mall-swarm")

# dataId 必须和 application-dev.yml 里 spring.config.import 写的那个字符串完全一致
CONFIGS = [
    ("mall-admin-dev.yaml",   "config/admin/mall-admin-dev.yaml"),
    ("mall-auth-dev.yaml",    "config/auth/mall-auth-dev.yaml"),
    ("mall-demo-dev.yaml",    "config/demo/mall-demo-dev.yaml"),
    ("mall-gateway-dev.yaml", "config/gateway/mall-gateway-dev.yaml"),
    ("mall-portal-dev.yaml",  "config/portal/mall-portal-dev.yaml"),
    ("mall-search-dev.yaml",  "config/search/mall-search-dev.yaml"),
]


def post(path, data, token=None):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if token:
        req.add_header("accessToken", token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def get(path, params, token=None):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("accessToken", token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def login():
    status, resp = post("/nacos/v3/auth/user/login",
                        {"username": NACOS_USER, "password": NACOS_PASS})
    if status == 200 and resp.get("accessToken"):
        return resp["accessToken"]
    print(f"  [FAIL] 登录失败 -> {status} {resp}")
    return None


def main():
    check_only = "--check" in sys.argv

    token = login()
    if not token:
        return 1
    print(f"  [OK]   登录 Nacos 成功（{NACOS_USER}），拿到 accessToken\n")

    ok = fail = 0
    for data_id, rel in CONFIGS:
        p = ROOT / rel
        if not p.exists():
            print(f"  [FAIL] {data_id:24} 源文件不存在: {rel}")
            fail += 1
            continue

        content = p.read_text(encoding="utf-8")

        if not check_only:
            status, resp = post("/nacos/v3/admin/cs/config",
                                {"dataId": data_id, "groupName": GROUP, "content": content},
                                token=token)
            if not (status == 200 and str(resp.get("code")) == "0"):
                print(f"  [FAIL] {data_id:24} 发布失败 -> {status} {str(resp)[:120]}")
                fail += 1
                continue

        # 读回校验：Nacos 存回来的内容必须和源文件逐字节一致
        #
        # 注意响应形状。Nacos 3.x 的客户端读接口返回的是
        #     {"code":0,"message":"success","data":{"content":"...","md5":"...",...}}
        # 也就是说 data 是一个**对象**，正文在 data.content 里 —— 不是 data 本身。
        # 配置不存在时则是 {"code":20004,"message":"resource not found","data":null}。
        # 早先按 data 直接比字符串，把「发布成功」误判成了「读回为空」。
        #
        # 还要注意：客户端读接口不是立即可见的，刚发布完可能读回上一次的旧值
        # （实测：连发两次不同内容，第二次读回的还是第一次的）。所以这里轮询重试，
        # 不能读完一次就下结论。
        got, d = None, None
        for attempt in range(6):
            status, resp = get("/nacos/v3/client/cs/config",
                               {"dataId": data_id, "groupName": GROUP})
            d = resp.get("data") if isinstance(resp, dict) else None
            got = d.get("content") if isinstance(d, dict) else None
            if got == content:
                break
            time.sleep(1)

        if got == content:
            note = "" if attempt == 0 else f"，第 {attempt + 1} 次读回才一致"
            print(f"  [OK]   {data_id:24} 已发布并读回校验一致（{len(content)} 字符，md5={d.get('md5')}{note}）")
            ok += 1
        elif got is None:
            print(f"  [FAIL] {data_id:24} 读回为空 -> {status} {str(resp)[:100]}")
            fail += 1
        else:
            print(f"  [FAIL] {data_id:24} 读回内容与源文件不一致（源 {len(content)} / 读回 {len(got)}）")
            fail += 1

    print()
    print(f"  成功 {ok} 个，失败 {fail} 个")
    if not check_only:
        print("  mall-swarm 各模块现在可以从 Nacos 拉到配置了。")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
