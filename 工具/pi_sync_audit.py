#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pi ↔ 工作区 部署对账（2026-09-22）。

为什么要它：2026-09-22 实测发现 Pi 上有【2 个文件静默过期】——
`pixel_to_device.py`（旧到 Sep 19）与 `vision_ingest.py`（少一条拒识原因日志）。
后果不是"跑不起来"，而是**行为/日志与工作区不一致**，导致排查时反复怀疑
"改了怎么没效果"。这类漂移必须先被看见，再谈改代码。

用法（在工作区根执行）：
    python3 工具/pi_sync_audit.py                 # 只对账，不改任何东西
    python3 工具/pi_sync_audit.py --deploy FILE   # 需要时：备份 + 推送 + 双向校验

退出码：0 = 全部一致；1 = 有不一致（可用于赛前检查清单）；2 = 根本没连上 Pi（未比对）。
"""
from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys
from pathlib import Path

PI = "pi@172.20.10.8"
PI_ROOT = "/home/pi/电控"
LOCAL_ROOT = Path(__file__).resolve().parents[1] / "电控"
# 运行期需要与工作区严格一致的东西；deploy/ 下的开发自检脚本不在此列
SUBDIRS = ("src", "deploy")

_HASH_SH = """#!/bin/sh
cd %s || exit 1
find %s -name '*.py' | sort | while read -r f; do
  case "$f" in
    *.bak*|*__pycache__*) continue ;;
  esac
  printf '%%s %%s\\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f"
done
""" % (PI_ROOT, " ".join(SUBDIRS))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _remote_hashes() -> dict[str, str]:
    """让 Pi 跑一段固定的 sh（base64 传过去，绕开引号被啃的坑），回传 path→sha。"""
    b64 = base64.b64encode(_HASH_SH.encode()).decode()
    cmd = "echo %s | base64 -d > /tmp/_h.sh; sh /tmp/_h.sh" % b64
    out = subprocess.run(["ssh", "-o", "ConnectTimeout=20", PI, cmd],
                         capture_output=True, text=True, encoding="utf-8").stdout
    table = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            table[parts[1].strip()] = parts[0]
    return table


def _local_hashes() -> dict[str, str]:
    table = {}
    for sub in SUBDIRS:
        for f in sorted((LOCAL_ROOT / sub).rglob("*.py")):
            s = str(f).replace("\\", "/")
            if any(x in s for x in (".bak", "__pycache__", ".pytest_cache")):
                continue
            table[str(f.relative_to(LOCAL_ROOT)).replace("\\", "/")] = _sha(f)
    return table


def main(argv: list[str]) -> int:
    if "--deploy" in argv:
        rel = argv[argv.index("--deploy") + 1]
        local, remote = LOCAL_ROOT / rel, "%s/%s" % (PI_ROOT, rel)
        b64 = base64.b64encode((LOCAL_ROOT / rel).read_bytes()).decode()
        subprocess.run(["ssh", PI, "cp -p %s %s.bak-before-deploy-$(date +%%Y%%m%%d-%%H%%M%%S)" % (remote, remote)])
        # 🔴 2026-09-22 修：base64 **必须走 stdin**，不能塞进命令行。
        #   旧写法 `ssh "echo <b64> | base64 -d > <remote>"` 把整个 base64 放进 argv ——
        #   Windows 命令行上限约 32KB ⇒ 25KB 的源文件（base64 后 ~34KB）就报
        #   `FileNotFoundError: [WinError 206] 文件名或扩展名太长`，
        #   而 83KB 的 deploy/run_chain.py 必然更崩。
        #   走 stdin 后与文件大小无关。
        pushed = subprocess.run(["ssh", PI, "base64 -d > %s" % remote],
                                input=b64.encode(), check=False)
        if pushed.returncode != 0:
            print("❌ 推送失败（ssh 退出码 %d）：%s" % (pushed.returncode, rel))
            return 1
        got = subprocess.run(["ssh", PI, "sha256sum %s" % remote],
                             capture_output=True, text=True).stdout.split()[0]
        ok = got == _sha(local)
        print("%s %s  local=%s pi=%s" % ("✅" if ok else "❌", rel, _sha(local)[:16], got[:16]))
        return 0 if ok else 1

    remote, local = _remote_hashes(), _local_hashes()
    # 🔴 2026-09-22：**空表必须与"全一致"区分开**。ssh 不通（Pi 离线/掉线）时
    # _remote_hashes() 返回空 dict ⇒ stale=[]、extra=[]、内容不一致=0 —— 看起来像"全对"，
    # 而实际上一个文件都没比过。这个工具是赛前检查门，假通过比不通过更危险。
    if not remote:
        print("❌ 拿不到 Pi 的哈希表（ssh 失败 / Pi 离线 / 未连上 172.20.10.8）")
        print("   ⇒ 本次【一个文件都没有比对过】；那个 0 不代表一致。")
        print("   先确认 `ssh %s echo OK` 能通，再重跑本脚本。" % PI)
        return 2
    stale = sorted(r for r in local if r in remote and remote[r] != local[r])
    missing = sorted(r for r in local if r not in remote)
    extra = sorted(r for r in remote if r not in local)
    same = sum(1 for r in local if remote.get(r) == local[r])

    # deploy/ 下的开发自检脚本本来就不部署到 Pi（Pi 只跑 deploy/run_chain.py）
    # ⇒ 它们"缺失"是设计如此，不该让退出码变红，否则这个工具没法当赛前检查门用。
    missing_runtime = [r for r in missing if not r.startswith("deploy/")]

    print("一致 = %d   内容不一致 = %d   Pi 上没有 = %d（其中运行期必需 %d）   Pi 上多出 = %d"
          % (same, len(stale), len(missing), len(missing_runtime), len(extra)))
    for tag, items in (("⚠️ Pi 上是旧版（工作区更新）", stale),
                       ("⚠️ 运行期文件在 Pi 上缺失", missing_runtime),
                       ("ℹ️ 未部署的开发脚本（设计如此，无害）",
                        [r for r in missing if r.startswith("deploy/")]),
                       ("ℹ️ 只在 Pi 上（工作区没有）", extra)):
        if items:
            # 用 ASCII 冒号：全角"："在 Windows GBK 控制台下 print 会抛 UnicodeEncodeError
            print("\n%s:" % tag)
            for r in items:
                print("   %s" % r)
    if not stale and not missing_runtime:
        print("\n✅ 部署与工作区一致，可以放心按工作区版本排查。")
    return 1 if (stale or missing_runtime) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
