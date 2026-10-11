#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单条诊断计步运动的**原始输出**采集（点 3 缺失证据之一）。

用法：python3 pi_step_timing.py [steps] [hz] [watch秒]      默认 400 500 5

它做两件事并把板子回的每一行原文打印出来（带相对时间）：
  1) MOTION ARM          —— 打开 10 秒的运动授权窗口
  2) MOVE X DIR0 STEPS <n> HZ <hz>

🔴 安全：会真的动。400 步 = 5mm。X/Y 没有限位开关，跑之前机构必须在行程正中，
   人守急停。默认只动 5mm。
⚠️ 已知局限（必须连同结果一起引用，别当成结论）：
   · 诊断路径的 DONE 由 ISR 回调直接写入，**绕过轴驱动的 latch 消费**
     —— 所以本脚本「正常报完成」**不能**证明生产路径的 latch 交接无故障。
   · 板子 STATUS 是 1Hz，**无法分辨** 400 步到底是 0.49558 秒（200→2000→200 Hz
     梯形曲线模型）还是 0.80 秒（恒速 500Hz）—— 本脚本不回答步频问题。
   · 链路必须在停的状态下跑（第二个进程开串口会把链路挤死）。
"""

import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200
STEPS = int(sys.argv[1]) if len(sys.argv) > 1 else 400
HZ = int(sys.argv[2]) if len(sys.argv) > 2 else 500
WATCH = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0


def clean(raw):
    line = "".join(ch for ch in raw if 32 <= ord(ch) < 127).strip()
    return line[:140]


port = serial.Serial(PORT, BAUD, timeout=0.05)


def drain(seconds):
    out = bytearray()
    end = time.time() + seconds
    while time.time() < end:
        waiting = port.in_waiting
        chunk = port.read(waiting if waiting else 1)
        if chunk:
            out.extend(chunk)
    return bytes(out)


drain(1.5)  # 丢掉在途的旧 STATUS 半行

for cmd in ("MOTION ARM", "MOVE X DIR0 STEPS %d HZ %d" % (STEPS, HZ)):
    print(">>> %s   @%s" % (cmd, time.strftime("%H:%M:%S")))
    t0 = time.time()
    port.write((cmd + "\r\n").encode())
    chunk = drain(1.2 if cmd.startswith("MOTION") else WATCH)
    for raw in chunk.decode("ascii", "replace").splitlines():
        line = clean(raw)
        if line:
            print("    +%.3fs  %s" % (time.time() - t0, line))

port.close()
print("=== 结束（未做任何后续动作）===")
