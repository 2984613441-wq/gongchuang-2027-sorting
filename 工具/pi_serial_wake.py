#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""串口/板子无响应时的诊断：谁占着口、设备在不在、灌数据有没有回音。"""
import glob
import os
import subprocess
import time

import serial

PORT = "/dev/serial0"

print("=== 设备 ===")
for pat in (PORT, "/dev/ttyS0", "/dev/ttyAMA0", "/dev/serial1"):
    try:
        real = os.path.realpath(pat)
        print("  %-16s -> %-16s exists=%s" % (pat, real, os.path.exists(real)))
    except OSError as exc:
        print("  %-16s 解析失败: %s" % (pat, exc))

print("\n=== 谁占着串口 ===")
found = False
for pid in glob.glob("/proc/[0-9]*"):
    try:
        for fd in glob.glob(pid + "/fd/*"):
            try:
                tgt = os.readlink(fd)
            except OSError:
                continue
            if "ttyS0" in tgt or "serial0" in tgt:
                cmd = open(pid + "/cmdline", "rb").read().replace(b"\0", b" ").decode(
                    "utf-8", "replace").strip()
                print("  pid=%s  %s  -> %s" % (pid.split("/")[-1], cmd, tgt))
                found = True
                break
    except OSError:
        continue
if not found:
    print("  （没有其它进程占用）")

print("\n=== 灌数据试回音（10 秒）===")
try:
    s = serial.Serial(PORT, 115200, timeout=0.3)
except Exception as exc:  # noqa: BLE001
    print("  打不开串口:", exc)
    raise SystemExit(1)

s.reset_input_buffer()
got_any = False
for i in range(10):
    s.write(b"\r\nPING\r\nSTATUS\r\n")
    s.flush()
    time.sleep(0.7)
    data = s.read(4096)
    if data:
        got_any = True
        txt = "".join(ch for ch in data.decode("ascii", "replace")
                      if 32 <= ord(ch) < 127 or ch in "\r\n")
        print("  第%d轮收到 %d 字节:" % (i + 1, len(data)))
        for ln in txt.splitlines()[:4]:
            if ln.strip():
                print("     ", ln.strip()[:110])
        break
    else:
        print("  第%d轮：0 字节" % (i + 1))
s.close()

if not got_any:
    print("\n=> 串口能打开但板子 10 秒内一个字都没回。")
    print("   最可能：① 主控被堵转带挂（本项目已发生 3 次）② 板子掉电/复位中")
    print("   处理：X/Y 无硬件限位，先确认没顶在硬限位上；")
    print("         板子 RESET 按钮可以按（不会丢位置，步进是开环相对量）；")
    print("         不要直接断电，先 RESET 试。")
