#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板子诊断探针：把给定的 ASCII 命令逐条发过去并打印【原始应答】。

只发你给它的命令，不做任何隐含动作。用法：
    python3 /home/pi/pi_diag_probe.py PING INPUTS STATUS "MOTION ARM" STATUS

为什么需要它：`ERR MOTION_NOT_ARMED_OR_INHIBITED` 有两个成因（授权没用上 / 被抑制），
必须把 INPUTS 与 MOTION ARM 的【原始应答】都拿到才能分清，不能靠猜。
"""
import serial
import sys
import time

cmds = sys.argv[1:]
if not cmds:
    print("用法: pi_diag_probe.py <cmd1> [cmd2 ...]")
    sys.exit(2)

s = serial.Serial("/dev/serial0", 115200, timeout=0.5)
time.sleep(0.3)

for c in cmds:
    s.reset_input_buffer()
    s.write((c + "\r\n").encode("ascii"))
    time.sleep(0.45)
    raw = s.read(8000).decode("ascii", "replace")
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    print("=== %-14s -> %s" % (c, lines if lines else "(空应答)"))

s.close()
