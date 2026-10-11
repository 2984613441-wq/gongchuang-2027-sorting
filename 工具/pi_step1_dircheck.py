#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第一步：从手工推到位的 HOME 内角，做 5 mm 方向核对。

前情（2026-09-19 现场）：用户断电/松轴后把 XY 用手推到了内角 HOME，
真值 = 逻辑 (-95.0, -97.5)。板子的逻辑位置已失真，但台架 MOVE 是相对步数，
所以这一步只核对"往哪个方向动"，不做大位移——
X/Y 没有限位开关，方向发错就是往硬限位上顶（已顶挂过 3 次）。

预期：DIR0 让 X 增大（离开 HOME 往托盘里），DIR1 让 Y 增大。
80 步/mm，400 步 = 5.0 mm。

用法： python3 pi_step1_dircheck.py
"""
import time

import serial

PORT = "/dev/serial0"
CAL = "/home/pi/电控/calibration_config.ini"
STEPS = 400          # 80 步/mm -> 5.0 mm
HZ = 800

s = serial.Serial(PORT, 115200, timeout=0.5)
time.sleep(0.3)


def send(cmd, wait=0.5):
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(900).decode("ascii", "replace").strip()


def jog(axis, direction, expect):
    print("\n=== MOVE %s %s STEPS %d (=5.0 mm) HZ %d  [预期 %s] ===" %
          (axis, direction, STEPS, HZ, expect))
    arm = send("MOTION ARM")
    print("ARM  ->", arm)
    if "OK" not in arm:
        print("!! ARM 没成功，跳过这一步（不动电机）")
        return
    print("MOVE ->", send("MOVE %s %s STEPS %d HZ %d" % (axis, direction, STEPS, HZ), 0.4))
    t0 = time.time()
    res = "?"
    while time.time() - t0 < 6.0:
        txt = send("STATUS", 0.2)
        if "STEP_REMAIN=0" in txt:
            for tok in txt.split():
                if tok.startswith("STEP_RESULT="):
                    res = tok.split("=", 1)[1]
            break
        time.sleep(0.1)
    print("用时 %.2fs  STEP_RESULT=%s  (1=成功)" % (time.time() - t0, res))


print("PING ->", send("PING"))
jog("X", "DIR0", "X 增大 5 mm，离开 HOME 往托盘中间")
jog("Y", "DIR1", "Y 增大 5 mm，离开 HOME 往托盘中间")

print("\n--- 当前标定原始行（只读，供核对）---")
try:
    with open(CAL, "r", encoding="utf-8") as fh:
        for ln in fh:
            if any(k in ln for k in ("a11", "a22", "tx", "ty", "camera_height")):
                print("   ", ln.rstrip())
except OSError as exc:
    print("    读不到:", exc)

s.close()
print("\n完成。请报告：X 实际往哪边动了多少？Y 实际往哪边动了多少？")
