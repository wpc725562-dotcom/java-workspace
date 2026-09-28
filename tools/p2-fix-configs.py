#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把 P2 (mall-swarm) 的配置适配到 D:\\java-workspace 的本地端口约定。

改三处：
  1. jdbc:mysql://localhost:3306/mall  ->  3308   （工作区 MySQL 8 便携版）
  2. datasource 的 root/root           ->  root/123456（工作区统一 root 密码）
  3. redis port: 6379                  ->  6380   （工作区 Redis 便携版）

为什么是 3308 而不是 3307：
  P0 (eladmin-mp) 是 Spring Boot 2.7 / javax 时代的老项目，配 MySQL 5.7 -> 3307。
  P2 (mall-swarm) 是 Spring Boot 3.5 / jakarta，配 MySQL 8 -> 3308。
  两个实例并存正是为了不用在同一个库里混两套时代的东西。

为什么每处都只改"数据源那一个"：
  mall-portal 里还有 RabbitMQ 的 username/password: mall/mall，
  以及 MongoDB 的 27017。用整文件替换 password 会误伤它们。
  所以按"两行连续序列"精确定位，改完立刻用 YAML 解析器验证。
"""

import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(r"D:\java-workspace\p2-mall-swarm")

FILES = [
    "config/admin/mall-admin-dev.yaml",
    "config/demo/mall-demo-dev.yaml",
    "config/portal/mall-portal-dev.yaml",
    "config/search/mall-search-dev.yaml",
    "mall-admin/src/main/resources/application.yml",
    "mall-demo/src/main/resources/application.yml",
    "mall-portal/src/main/resources/application.yml",
    "mall-search/src/main/resources/application.yml",
]

HEADER = (
    "# ============================================================================\n"
    "#  ⚠️ 本地工作区改动 (2026-09-28) —— 原值见同目录同名 .orig 文件\n"
    "#    MySQL    localhost:3306 -> localhost:3308   (工作区便携版 MySQL 8.0)\n"
    "#    root 密码 root          -> 123456           (工作区统一约定)\n"
    "#    Redis    port 6379      -> 6380             (工作区便携版 Redis)\n"
    "#  端口约定见 D:\\java-workspace\\docs\\port-map.md\n"
    "# ============================================================================\n"
)


def patch(text):
    n = {"jdbc": 0, "pw": 0, "redis": 0}

    text, c = re.subn(r"jdbc:mysql://localhost:3306/mall", "jdbc:mysql://localhost:3308/mall", text)
    n["jdbc"] = c

    # 只匹配「username: root 紧跟着 password: root」这一对，且缩进相同。
    # 这样不会碰到 RabbitMQ 的 mall/mall，也不会碰到别处的 password。
    text, c = re.subn(r"(\n(\s*)username: root\n\2password: )root(\s*\n)", r"\g<1>123456\g<3>", text)
    n["pw"] = c

    # Redis 的 port: 6379 —— 只改带 "Redis" 注释的那行，避免误伤其它 6379
    text, c = re.subn(r"(\n(\s*)port: )6379(\s*#\s*Redis)", r"\g<1>6380\g<3>", text)
    n["redis"] = c

    return text, n


def main():
    total = {"jdbc": 0, "pw": 0, "redis": 0}
    changed, failed = [], []

    for rel in FILES:
        p = ROOT / rel
        if not p.exists():
            print(f"  [SKIP] {rel} 不存在")
            failed.append(rel)
            continue

        raw = p.read_text(encoding="utf-8")
        new, n = patch(raw)

        if new == raw:
            print(f"  [SKIP] {rel} 无需改动")
            continue

        # 先备份（只备份一次，避免反复运行时把改过的值当成"原值"）
        bak = p.with_suffix(p.suffix + ".orig")
        if not bak.exists():
            shutil.copy2(p, bak)

        # 顶部插入说明；若已插入过就不重复
        if not new.startswith("# ===="):
            new = HEADER + new

        # 落盘前先验证 YAML，坏文件绝不写出去
        try:
            yaml.safe_load(new)
        except Exception as e:
            print(f"  [FAIL] {rel} 改完 YAML 解析失败，已放弃写入 -> {str(e)[:100]}")
            failed.append(rel)
            continue

        p.write_text(new, encoding="utf-8")
        for k in total:
            total[k] += n[k]
        changed.append(rel)
        print(f"  [OK]   {rel:56} jdbc={n['jdbc']} pw={n['pw']} redis={n['redis']}")

    print()
    print(f"  合计：MySQL 端口 {total['jdbc']} 处，root 密码 {total['pw']} 处，Redis 端口 {total['redis']} 处")
    print(f"  改动文件 {len(changed)} 个，跳过/失败 {len(failed)} 个")

    # 全量复验：整个仓库的 yml 都要能解析
    print()
    print("  全仓库 YAML 复验：")
    bad = 0
    for p in sorted(ROOT.rglob("*.y*ml")):
        if "target" in p.parts:
            continue
        try:
            yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception as e:
            bad += 1
            print(f"    [FAIL] {p.relative_to(ROOT)} -> {str(e)[:80]}")
    print(f"    检查完毕，解析失败 {bad} 个")
    return 1 if (failed or bad) else 0


if __name__ == "__main__":
    sys.exit(main())
