#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台架：让 X 轴走指定步数（DIR0 = +X 方向）。80 步/mm。

用法： python3 pi_move_x.py <步数>
安全：慢速 1000Hz；跑之前请确认滑台在安全位置、手在急停上。
"""
import sys
import time

import serial

STEPS = int(sys.argv[1])
MM = STEPS / 80.0

s = serial.Serial("/dev/serial0", 115200, timeout=0.5)
time.sleep(0.3)


def send(cmd, wait=0.5):
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(700).decode("ascii", "replace").strip()


print("X 走 %d 步 = %.1f mm（DIR0 = +X，1000Hz 慢速）" % (STEPS, MM))
print("PING ->", send("PING"))
print("ARM  ->", send("MOTION ARM"))
print("MOVE ->", send("MOVE X DIR0 STEPS %d HZ 1000" % STEPS, 0.4))

t0 = time.time()
last = ""
while time.time() - t0 < 20.0:
    last = send("STATUS", 0.3)
    if "STEP_REMAIN=0" in last and "MODE=0" in last:
        break
    time.sleep(0.2)
print("用时 %.2fs" % (time.time() - t0))
print("末态: %s" % last[:160])
print()
print(">>> 看看滑台现在到哪了；若要继续往 +X 走，再跑一次即可")
s.close()
