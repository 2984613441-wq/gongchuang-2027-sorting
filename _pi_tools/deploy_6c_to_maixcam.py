#!/usr/bin/env python3
"""把 6 类 cvimodel 部署到 MaixCAM（一条命令）。

## 为什么单独写这个

MaixCAM 只在 iPhone 热点上（172.20.10.9）。笔记本会**自动切回校园网**
（`CDUT_WiFi`），这时连不上。本脚本会：
  1. 先检查/尝试连 iPhone 热点
  2. 检查 MaixCAM 可达
  3. 上传 cvimodel + mud
  4. 校验设备端大小与 MD5
  5. 生成 6 类版的看图脚本并上传

## 用法

```bash
python _pi_tools/deploy_6c_to_maixcam.py
python _pi_tools/deploy_6c_to_maixcam.py --skip-network
```

前置（手动一次）：**打开 iPhone 个人热点**，笔记本连它。
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "_deploy_maixcam"
MAIX = "root@172.20.10.9"
MODELS = "/root/my_models"

CVIMODEL = DEPLOY / "yolo11n_6c_448_cv181x.cvimodel"
MUD = DEPLOY / "yolo11n_6c_448_cv181x.mud"

SSH = ["-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=no"]
SCP = ["-o", "ConnectTimeout=20", "-o", "StrictHostKeyChecking=no"]


def run(cmd: list[str], **kw) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60, **kw)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as exc:
        return 1, str(exc)


def wifi_ssid() -> str:
    rc, out = run(["netsh", "wlan", "show", "interfaces"])
    for line in out.splitlines():
        if "SSID" in line and ":" in line and "BSSID" not in line:
            return line.split(":", 1)[1].strip()
    return ""


def ipv4_list() -> list[str]:
    rc, out = run(["ipconfig"])
    ips = []
    for line in out.splitlines():
        if "IPv4" in line and ":" in line:
            ips.append(line.split(":", 1)[1].strip())
    return ips


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="部署 6 类模型到 MaixCAM")
    ap.add_argument("--skip-network", action="store_true",
                    help="跳过网络检查（假定已连热点）")
    args = ap.parse_args(argv)

    print("=" * 74)
    print("  部署 6 类 cvimodel 到 MaixCAM")
    print("=" * 74)

    # ── 0) 本地产物检查 ──────────────────────────────────────────
    print()
    print("  [0/5] 本地产物检查")
    for f in (CVIMODEL, MUD):
        if not f.is_file():
            print("    ❌ 缺文件: %s" % f)
            return 1
        sz = f.stat().st_size
        md5 = hashlib.md5(f.read_bytes()).hexdigest()
        print("    ✅ %-40s %8d 字节  md5=%s" % (f.name, sz, md5))

    # ── 1) 网络 ──────────────────────────────────────────────────
    print()
    print("  [1/5] 网络检查")
    if not args.skip_network:
        ssid = wifi_ssid()
        ips = ipv4_list()
        print("    当前 SSID : %s" % (ssid or "(未知)"))
        print("    本机 IP   : %s" % ", ".join(ips))
        on_hotspot = any(ip.startswith("172.20.10.") for ip in ips)
        if not on_hotspot:
            print()
            print("    ⚠️ 不在 iPhone 热点网段（172.20.10.x）")
            print("       尝试连接已保存的 iPhone 配置 …")
            rc, out = run(["netsh", "wlan", "connect", "name=iPhone"])
            print("       %s" % (out.strip().splitlines()[-1] if out.strip() else ""))
            time.sleep(8)
            ips = ipv4_list()
            on_hotspot = any(ip.startswith("172.20.10.") for ip in ips)
            print("       重试后 IP : %s" % ", ".join(ips))
            if not on_hotspot:
                print()
                print("    ❌ 连不上 iPhone 热点。请手工操作：")
                print("       ① 打开 iPhone 的【个人热点】")
                print("       ② 笔记本 WiFi 选中 iPhone 并连接")
                print("       ③ 重新跑本脚本")
                print()
                print("       ⚠️ Windows 会自动切回 CDUT_WiFi，")
                print("          连上热点后最好【忘记】CDUT_WiFi，否则会被抢回去。")
                return 1
        print("    ✅ 在热点网段")

    # ── 2) 设备可达 ──────────────────────────────────────────────
    print()
    print("  [2/5] MaixCAM 可达性")
    rc, out = run(["ping", "-n", "2", "-w", "2000", "172.20.10.9"])
    if rc != 0 and "TTL" not in out:
        print("    ❌ ping 不通 172.20.10.9")
        print("       检查 MaixCAM 是否开机、是否连上同一热点")
        return 1
    print("    ✅ ping 通")

    rc, out = run(["ssh"] + SSH + [MAIX, "echo OK"])
    if rc != 0 or "OK" not in out:
        print("    ❌ SSH 不通: %s" % out.strip()[:200])
        return 1
    print("    ✅ SSH 通")

    # ── 3) 上传 ──────────────────────────────────────────────────
    print()
    print("  [3/5] 上传 cvimodel + mud")
    rc, out = run(["scp"] + SCP + [
        str(CVIMODEL), str(MUD), "%s:%s/" % (MAIX, MODELS)])
    if rc != 0:
        print("    ❌ scp 失败: %s" % out.strip()[:400])
        return 1
    print("    ✅ 上传完成")

    # ── 4) 设备端校验 ────────────────────────────────────────────
    print()
    print("  [4/5] 设备端校验")
    local_md5 = hashlib.md5(CVIMODEL.read_bytes()).hexdigest()
    rc, out = run(["ssh"] + SSH + [
        MAIX,
        "ls -l %s/yolo11n_6c_448_cv181x.* && "
        "md5sum %s/yolo11n_6c_448_cv181x.cvimodel && "
        "grep labels %s/yolo11n_6c_448_cv181x.mud"
        % (MODELS, MODELS, MODELS)])
    print("    " + out.strip().replace("\n", "\n    "))
    if local_md5 in out:
        print("    ✅ MD5 一致（本地 %s）" % local_md5)
    else:
        print("    ⚠️ MD5 不一致或没读到，请人工核对")

    # ── 5) 生成 6 类看图脚本 ─────────────────────────────────────
    print()
    print("  [5/5] 生成并上传 6 类看图脚本")
    src = ROOT / "_pi_tools" / "maixcam_scripts" / "yolo_box_view.py"
    if not src.is_file():
        print("    ⚠️ 找不到 yolo_box_view.py，跳过")
    else:
        txt = src.read_text(encoding="utf-8")
        txt6 = txt.replace('"yolo11n_7c_448_cv181x"', '"yolo11n_6c_448_cv181x"')
        txt6 = txt6.replace('"yolo11n_8c_448"', '"yolo11n_6c_448_cv181x"')
        dst = ROOT / "_pi_tools" / "maixcam_scripts" / "yolo_box_view_6c.py"
        dst.write_text(txt6, encoding="utf-8", newline="\n")
        rc, out = run(["scp"] + SCP + [str(dst), "%s:/root/" % MAIX])
        if rc != 0:
            print("    ❌ 上传失败: %s" % out.strip()[:300])
        else:
            print("    ✅ 已上传 /root/yolo_box_view_6c.py")

    print()
    print("=" * 74)
    print("  ✅ 部署完成")
    print("=" * 74)
    print("  下一步：MaixVision 打开 /root/yolo_box_view_6c.py 运行")
    print("  屏幕上应显示 6 类：cube/cuboid/cylinder/pentagonal_prism/")
    print("                      cone/tetrahedron")
    print("  ⚠️ cone 会一直是 0（训练时无数据），属预期")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
