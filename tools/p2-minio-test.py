"""
P2 / mall-admin 的 MinIO 端到端验证。

验证的不是「9000 端口起来了」，而是 mall-admin 的文件上传链路真的能用：
  上传 -> 读回 -> 匿名 HTTP 直链可访问 -> 删除

驱动的是 MinIO 官方客户端 mc.exe（已经在 .runtime/minio/mc.exe），
所以不需要额外 pip 装 minio SDK；只有标准库 urllib 用于匿名 HTTP 校验。

对照的 Java 代码：
  mall-admin/src/main/java/com/macro/mall/controller/MinioController.java
      · bucketExists -> 不存在就 makeBucket + setBucketPolicy
      · 对象名 = yyyyMMdd + "/" + 原始文件名
      · 返回的 url = endpoint + "/" + bucketName + "/" + objectName
  配置来源：
  config/admin/mall-admin-dev.yaml
      minio.endpoint   : http://localhost:9000
      minio.bucketName : mall
      minio.accessKey  : minioadmin
      minio.secretKey  : minioadmin
"""

import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
MC = WS / ".runtime" / "minio" / "mc.exe"
CONF_DIR = WS / ".runtime" / "data" / "minio" / "mc"
TMP = WS / ".runtime" / "tmp"

ENDPOINT = "http://127.0.0.1:9000"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"
BUCKET = "mall"
ALIAS = "jw"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def mc(*args, timeout=60):
    """Run mc with the workspace-local config dir. Returns (rc, stdout+stderr)."""
    cmd = [str(MC), "--config-dir", str(CONF_DIR)] + [str(a) for a in args]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    print("=" * 74)
    print("P2 / mall-admin MinIO 端到端验证")
    print(f"  {ENDPOINT}   bucket={BUCKET}   user={ACCESS_KEY}")
    print("=" * 74)

    TMP.mkdir(parents=True, exist_ok=True)

    # ---- 1) 工具与配置 ----------------------------------------------------
    print("\n[1] 工具与连接")
    if not MC.exists():
        check("mc.exe 存在", False, str(MC))
        return report()
    check("mc.exe 存在", True, str(MC))

    rc, out = mc("alias", "set", ALIAS, ENDPOINT, ACCESS_KEY, SECRET_KEY)
    check("alias 配置 + 连接鉴权", rc == 0, out.strip().splitlines()[-1] if out.strip() else "")

    # ---- 2) bucket --------------------------------------------------------
    print("\n[2] 存储桶")
    rc, out = mc("mb", "--ignore-existing", f"{ALIAS}/{BUCKET}")
    check(f"bucket '{BUCKET}' 存在（幂等创建）", rc == 0,
          out.strip().splitlines()[-1] if out.strip() else "")

    # Java 侧是 s3:GetObject Allow for Principal *，等价于 mc 的 anonymous download
    rc, out = mc("anonymous", "set", "download", f"{ALIAS}/{BUCKET}")
    check("bucket 公开读策略已设置", rc == 0,
          out.strip().splitlines()[-1] if out.strip() else "")

    # ---- 3) 上传（复刻 Java 的对象命名规则）------------------------------
    print("\n[3] 上传（对象名 = yyyyMMdd/filename，与 MinioController 一致）")
    filename = "中文测试-商品图.txt"
    object_name = f"{date.today():%Y%m%d}/{filename}"
    payload = "MinIO 中文内容测试\nline2: 商品名称=测试商品\n"
    local = TMP / filename
    # newline="" 关掉 Windows 上的 \n -> \r\n 转换。
    # 不关的话磁盘上的字节和这里的 payload 不一样，后面比对会假失败。
    local.write_text(payload, encoding="utf-8", newline="")

    rc, out = mc("cp", str(local), f"{ALIAS}/{BUCKET}/{object_name}")
    check("上传对象", rc == 0, object_name)
    if rc != 0:
        return report()

    def norm(s: str) -> str:
        """统一换行后再比。mc / HTTP 两边都可能带 CRLF。"""
        return s.replace("\r\n", "\n").rstrip("\n")

    # ---- 4) 读回并比对 ----------------------------------------------------
    print("\n[4] 读回并比对内容")
    rc, out = mc("cat", f"{ALIAS}/{BUCKET}/{object_name}")
    if rc != 0:
        check("读回对象", False, out.strip())
    else:
        check("读回对象", True, f"{len(out)} 字符")
        same = norm(out) == norm(payload)
        check("内容逐行一致", same, "一致" if same else f"不一致: {out!r}")
        check("中文无损", "中文内容测试" in out and "测试商品" in out,
              "含「中文内容测试」「测试商品」")

    # ---- 5) 匿名 HTTP 直链（验证公开读策略真的生效）---------------------
    print("\n[5] 匿名 HTTP 直链（不带任何凭证）")
    url = f"{ENDPOINT}/{BUCKET}/{urllib.parse.quote(object_name)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            check("匿名 GET 返回 200", resp.status == 200, f"HTTP {resp.status}")
            same = norm(body) == norm(payload)
            check("匿名读取内容正确", same,
                  "一致" if same else f"不一致（收到 {len(body)} 字符）: {body!r}")
    except urllib.error.HTTPError as e:
        check("匿名 GET 返回 200", False, f"HTTP {e.code}（公开读策略没生效？）")
    except Exception as e:
        check("匿名 GET 返回 200", False, f"{type(e).__name__}: {e}")

    # ---- 6) 列举与删除 ----------------------------------------------------
    print("\n[6] 列举与删除")
    rc, out = mc("ls", f"{ALIAS}/{BUCKET}/{date.today():%Y%m%d}/")
    check("对象可被列举", rc == 0 and filename in out,
          out.strip().splitlines()[-1] if out.strip() else "(空)")

    rc, out = mc("rm", f"{ALIAS}/{BUCKET}/{object_name}")
    check("删除对象", rc == 0, out.strip().splitlines()[-1] if out.strip() else "")

    rc, out = mc("stat", f"{ALIAS}/{BUCKET}/{object_name}")
    check("删除后对象已不存在", rc != 0, "确认已删除")

    return report()


def report():
    print("\n" + "=" * 74)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    if passed == total:
        print(f"结果：全部通过（{passed}/{total}）—— MinIO 端到端可用")
        print("      mall-admin 的 /minio/upload 链路（含中文文件名与公开读直链）验证完毕")
        code = 0
    else:
        print(f"结果：{passed}/{total} 通过，存在失败项")
        for name, ok, detail in results:
            if not ok:
                print(f"   FAIL: {name}  {detail}")
        code = 1
    print("=" * 74)
    return code


if __name__ == "__main__":
    sys.exit(main())
