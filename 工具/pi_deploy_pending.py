#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一上电即可跑的"待部署改动"推送与自测脚本（2026-09-22 DSH 出）。

默认 **dry-run**（只比对、只打印，不动 Pi）；确认无误后加 --apply 才真推送。

它做两件事：
  A. 屏幕方案 C 的两处改动（本机已改完、零运动验收全绿）
     · 电控/deploy/run_chain.py                     → /home/pi/电控/deploy/run_chain.py
     · 电控/src/electrical_control/rpi/display_hdmi.py → /home/pi/电控/src/electrical_control/rpi/display_hdmi.py
     步骤：比对 md5 → Pi 上备份 → 推送 → 复核 md5 → Pi 侧只读预检（--info 与四栏渲染前置数据）
  B. 一键启动（本机已改完：ssh→本地执行、13/13 host 测试绿）
     · 工具/pi_side/pi_onkey.py  → /home/pi/pi_onkey.py
     · 工具/pi_side/pi-onkey.service → /etc/systemd/system/pi-onkey.service（User=pi）
     步骤：推送 → 装服务 → 只看状态，**不自动 enable**（要先由用户在场做 H3~H5 验收）

用法：
    py -3 工具/pi_deploy_pending.py            # dry-run：只比对与打印计划
    py -3 工具/pi_deploy_pending.py --apply    # 真推送
    py -3 工具/pi_deploy_pending.py --apply --only screen   # 只推屏幕那两处
    py -3 工具/pi_deploy_pending.py --apply --only onkey    # 只推一键启动
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PI = "pi@172.20.10.8"

SCREEN = [
    ("电控/deploy/run_chain.py", "/home/pi/电控/deploy/run_chain.py"),
    ("电控/src/electrical_control/rpi/display_hdmi.py",
     "/home/pi/电控/src/electrical_control/rpi/display_hdmi.py"),
]
ONKEY = [
    ("工具/pi_side/pi_onkey.py", "/home/pi/pi_onkey.py"),
    ("工具/pi_side/pi-onkey.service", "/home/pi/pi-onkey.service"),
]


def _ssh_raw(remote_cmd: str, stdin_text: str | None = None, *, timeout: int = 60) -> str:
    """跑一条远端命令；大载荷走 **stdin**（Windows 命令行有 32K 上限，挂参数会 WinError 206）。"""
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=10", PI, remote_cmd],
        input=(stdin_text or "").encode("utf-8"),
        capture_output=True, timeout=timeout,
    )
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    return out


def ssh(remote: str, *, timeout: int = 60) -> str:
    """把远端脚本 base64 后经 stdin 送过去执行（避免 PowerShell 引号地狱 + 长度上限）。"""
    b64 = base64.b64encode(remote.replace("\r\n", "\n").encode("utf-8")).decode()
    return _ssh_raw("base64 -d | bash", b64 + "\n", timeout=timeout)


def ssh_write(data: bytes, remote_path: str, *, timeout: int = 120) -> str:
    """把本地字节经 stdin 写入远端文件（同样避开命令行长度上限）。"""
    b64 = base64.b64encode(data).decode()
    return _ssh_raw(f"base64 -d > '{remote_path}'; echo 写入完成", b64 + "\n", timeout=timeout)


def md5_local(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def pi_md5(remote_path: str) -> str | None:
    out = ssh(f"md5sum '{remote_path}' 2>/dev/null | cut -d' ' -f1")
    for line in out.splitlines():
        line = line.strip()
        if len(line) == 32 and all(c in "0123456789abcdef" for c in line):
            return line
    return None


def push_one(local_rel: str, remote_path: str, apply: bool) -> bool:
    local = ROOT / local_rel
    if not local.exists():
        print(f"  ✗ 本机缺文件：{local_rel}")
        return False
    want = md5_local(local)
    have = pi_md5(remote_path)
    same = (have == want)
    print(f"  {local_rel}")
    print(f"    本机 md5 = {want}")
    print(f"    Pi   md5 = {have or '（不存在/读不到）'}   ⇒ {'已一致 ✓' if same else '需要推送 ✗'}")
    if not apply:
        return True
    if same:
        return True
    stamp = _ssh_raw("date +%Y%m%d-%H%M%S").strip()
    bak = f"{remote_path}.bak-before-20260922-{stamp}"
    print(f"    备份 → {bak}")
    print("    " + ssh(f"cp -p '{remote_path}' '{bak}' 2>/dev/null; echo 备份完成").strip())
    print("    " + ssh_write(local.read_bytes(), remote_path).strip())
    got = pi_md5(remote_path)
    ok = (got == want)
    print(f"    推送后 Pi md5 = {got} ⇒ {'对齐 ✓' if ok else '不一致 ✗ 请回滚：cp ' + bak + ' ' + remote_path}")
    return ok


def precheck_screen() -> None:
    print("\n[Pi 侧只读预检]")
    out = ssh(
        "echo -n 'throttled='; vcgencmd get_throttled\n"
        "PYTHONPATH=/home/pi/电控/src python3 -m electrical_control.rpi.display_hdmi --info 2>&1 | head -2\n"
        "echo -n '货物图片: '; ls /home/pi/images/ 2>/dev/null | tr '\\n' ' '; echo\n"
        "echo -n 'names.json: '; head -c 120 /home/pi/电控/deploy/names.json 2>/dev/null; echo\n"
        "echo -n '链是否在跑: '; pgrep -f '[r]un_chain.py' >/dev/null && echo 在跑 || echo 未跑\n",
        timeout=40,
    )
    print(out.strip() or "  （无输出：Pi 可能未上电）")


def deploy_onkey(apply: bool) -> None:
    print("\n[B 一键启动] 文件推送" + ("（dry-run 不执行）" if not apply else ""))
    for rel, remote in ONKEY:
        push_one(rel, remote, apply)
    if not apply:
        return
    print("  安装服务（**不 enable、不 start** —— H3~H5 验收要用户在场）")
    print("  " + ssh(
        "sudo cp /home/pi/pi-onkey.service /etc/systemd/system/pi-onkey.service && "
        "sudo systemctl daemon-reload && echo 服务已安装; "
        "sudo systemctl status pi-onkey.service --no-pager 2>&1 | head -3").strip())
    print("  ⚠️ 服务内 User= 必须为 pi（p_go8.sh 要读 /dev/serial0；pkill 同用户）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真推送（默认只 dry-run）")
    ap.add_argument("--only", choices=["screen", "onkey"], default=None)
    args = ap.parse_args()

    print("=" * 70)
    print(f"待部署改动推送（{'APPLY' if args.apply else 'DRY-RUN'}）  目标 {PI}")
    print("=" * 70)

    if args.only in (None, "screen"):
        print("\n[A 屏幕方案 C] 两处改动")
        for rel, remote in SCREEN:
            push_one(rel, remote, args.apply)
        if args.apply:
            precheck_screen()
    if args.only in (None, "onkey"):
        deploy_onkey(args.apply)

    print("\n完成。实机验收（用户在场）见：")
    print("  · 屏幕：跑一轮 ⇒ 屏上逐件出现四栏（序号/货物名称/图片/分拣成功总数量）")
    print("  · 一键启动：按一下 ⇒ 日志出现 p_go8.sh 的 HOME→PARK +145mm；中途弹起 ⇒ pkill 且板子状态不变")
    return 0


if __name__ == "__main__":
    sys.exit(main())
